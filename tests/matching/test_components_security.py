from dataclasses import replace

import pytest

from xp_libs_analytics import AnalyticsError
from xp_libs_analytics.matching.compiler import uses, validate_rules
from xp_libs_analytics.matching.models import Normalization
from xp_libs_analytics.matching.patterns import regex_flags, validate_regex
from xp_libs_analytics.models import Contains, Eq
from xp_libs_analytics.policy import Limits

from .support import execute, fuzzy, leaf, make


def test_shared_validator_guards_direct_typed_clients():
    for node, types, expected in [
        (Eq(op="eq", field="/absent", value="Peter"), {}, "DATA_FIELD_UNKNOWN"),
        (
            Contains(op="contains", field="/x", value="Peter"),
            {"/x": "mixed"},
            "DATA_FIELD_TYPE_CONFLICT",
        ),
        (
            Contains(op="contains", field="/x", value="Peter"),
            {"/x": "object"},
            "DATA_FIELD_NOT_SCALAR",
        ),
    ]:
        with pytest.raises(AnalyticsError) as error:
            validate_rules([node], types, Limits())
        assert error.value.code == expected
    assert uses(Eq(op="eq", field="/x", value=1)) == []
    with pytest.raises(AnalyticsError) as error:
        validate_rules(
            [
                Contains(
                    op="contains", field="/x", value="  ", normalization=Normalization(trim=True)
                )
            ],
            {"/x": "string"},
            Limits(),
        )
    assert error.value.code == "MATCH_PATTERN_INVALID"


def test_all_null_sources_and_empty_candidate_maps_preserve_unknown():
    engine = make([{"actor": {"name": None}}, {}])
    assert execute(engine, [fuzzy()])["rows"] == [{"n": 0}]
    assert execute(engine, [{"op": "not", "condition": fuzzy()}])["rows"] == [{"n": 0}]
    assert execute(engine, [leaf("contains", "Peter", normalization={"trim": True})])["rows"] == [
        {"n": 0}
    ]


def test_regex_flag_lexer_and_literal_unicode_expansion_are_bounded():
    assert regex_flags(r"[(?s)]\(\?s\)(?i:Peter)(?P<cap>x)") == ["i"]
    assert regex_flags("(?i)Peter(?-i)") == ["i", "-i"]
    assert execute(make([{"actor": {"name": "("}}]), [leaf("regex", "[(?s)]")])["rows"] == [
        {"n": 1}
    ]
    assert execute(make(), [leaf("regex", "(?i:Peter)")])["rows"] == [{"n": 12}]
    with pytest.raises(AnalyticsError):
        validate_regex("x" * 10000, Limits(), translated=True)
    assert execute(make(), [leaf("eq", "ßß", normalization={"case_sensitive": False})])["rows"] == [
        {"n": 0}
    ]
    assert (
        execute(
            make(max_match_literal_chars=3),
            [leaf("eq", "ßß", normalization={"case_sensitive": False})],
        )["error"]["code"]
        == "MATCH_PATTERN_INVALID"
    )
    assert execute(
        make([{"actor": {"name": "Straße"}}]),
        [leaf("regex", "STRASSE", normalization={"case_sensitive": False})],
    )["rows"] == [{"n": 0}]


def test_expanded_match_nodes_obey_existing_32_node_budget():
    row = {f"f{i}": "Peter" for i in range(10)}
    node = {
        "match": {
            "fields": ["/" + key for key in row],
            "patterns": [{"op": "eq", "value": "Peter"}] * 4,
        }
    }
    assert execute(make([row]), [node])["error"]["code"] == "MATCH_COMPLEXITY_BUDGET_EXCEEDED"


def test_regex_syntax_is_not_casefolded_and_internal_flags_do_not_consume_user_budget():
    assert execute(
        make([{"actor": {"name": "A"}}]),
        [leaf("regex", r"\D", normalization={"case_sensitive": False})],
    )["rows"] == [{"n": 1}]
    assert execute(
        make([{"actor": {"name": "1"}}]),
        [leaf("regex", r"\D", normalization={"case_sensitive": False})],
    )["rows"] == [{"n": 0}]
    assert execute(
        make([{"actor": {"name": "P" * 512}}]),
        [leaf("regex", "p" * 512, normalization={"case_sensitive": False})],
    )["rows"] == [{"n": 1}]


def test_raw_and_diagnostic_cardinality_cannot_bypass_budgets():
    engine = make(max_match_diagnostic_candidates=1)
    result = execute(engine, [fuzzy()], options={"matching_details": {"include": True}})
    assert result["error"]["code"] == "MATCH_CANDIDATE_BUDGET_EXCEEDED"
    engine = make(max_match_diagnostic_values=1)
    assert execute(engine)["rows"] == [{"n": 28}]
    assert (
        execute(
            engine, [fuzzy()], options={"matching_details": {"include": True, "top_values": 2}}
        )["error"]["code"]
        == "MATCH_COMPLEXITY_BUDGET_EXCEEDED"
    )


@pytest.mark.parametrize(
    "payload",
    [
        "DROP TABLE events; --",
        "__import__('os').system('whoami')",
        "../private",
        "${SECRET}",
        "Pete.*",
        "%Peter%",
    ],
)
def test_hostile_literals_are_data(payload):
    engine = make([{"actor": {"name": payload}}])
    assert execute(engine, [leaf("eq", payload)])["rows"] == [{"n": 1}]
    assert execute(engine, [leaf("contains", payload)])["rows"] == [{"n": 1}]


def test_rust_nested_quantifier_bounded_and_pattern_errors_do_not_echo():
    engine = make([{"actor": {"name": "a" * 1000 + "!"}}])
    assert execute(engine, [leaf("regex", r"(a+)+$")])["rows"] == [{"n": 0}]
    assert (
        execute(engine, [leaf("regex", "a{999999999}")])["error"]["code"] == "MATCH_REGEX_INVALID"
    )
    engine.limits = replace(engine.limits, max_match_value_chars=10)
    assert (
        execute(engine, [leaf("regex", "a")])["error"]["code"] == "MATCH_CANDIDATE_BUDGET_EXCEEDED"
    )


def test_invalid_regex_is_rejected_before_snapshot_records_are_read(monkeypatch):
    from xp_libs_analytics.ingest import Snapshot

    engine = make()

    def forbidden(_):
        raise AssertionError("Invalid pattern must not read input records")

    monkeypatch.setattr(Snapshot, "records", forbidden)
    assert execute(engine, [leaf("regex", "[")])["error"]["code"] == "MATCH_REGEX_INVALID"


def test_query_options_reject_top_k_and_unauthorized_model_overrides():
    engine = make()
    for kwargs in [
        {"top_k": 1},
        {"options": {"matching_details": {"include": True, "top_k": 1}}},
        {"options": {"min_fuzzy_score": 0}},
        {"options": {"context_id": "foreign"}},
    ]:
        assert execute(engine, [fuzzy()], **kwargs)["error"]["code"] == "QUERY_MALFORMED"
    for field in ["top_k", "limit"]:
        assert execute(engine, [{**fuzzy(), field: 1}])["error"]["code"] == "QUERY_MALFORMED"


def test_same_names_different_contexts_and_no_global_fuzzy_cache():
    engine = make([{"actor": {"name": "Peter"}}])
    with engine.create_context() as other:
        other.register_records("matching", [{"actor": {"name": "William"}}])
        assert execute(engine, [fuzzy()])["rows"] == [{"n": 1}]
        assert execute(other, [fuzzy()])["rows"] == [{"n": 0}]
    assert execute(engine, [fuzzy()])["rows"] == [{"n": 1}]
