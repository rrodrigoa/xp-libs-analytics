import json
from dataclasses import replace

import pytest
from rapidfuzz import fuzz

from xp_libs_analytics import Principal
from xp_libs_analytics.errors import CATALOG

from .support import execute, fuzzy, leaf, make, records, text


@pytest.mark.parametrize(
    "op,value,expected",
    [
        ("eq", "Peter", 2),
        ("ne", "Peter", 24),
        ("contains", "Peter", 10),
        ("not_contains", "Peter", 16),
        ("starts_with", "Peter", 7),
        ("ends_with", "Peter", 4),
        ("word", "Peter", 8),
        ("like", "%Peter%", 10),
        ("ilike", "%peter%", 12),
        ("regex", r"\APeter\z", 2),
    ],
)
def test_fixed_fixture_counts(op, value, expected):
    result = execute(make(), [leaf(op, value)])
    assert result["rows"] == [{"n": expected}], result


@pytest.mark.parametrize(
    "op",
    [
        "eq",
        "ne",
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
        "word",
        "like",
        "ilike",
        "regex",
        "fuzzy",
    ],
)
def test_null_and_missing_remain_unknown_under_not(op):
    rows = [{"actor": {"name": "Peter"}}, {"actor": {"name": None}}, {}]
    rule = fuzzy() if op == "fuzzy" else leaf(op)
    positive = execute(make(rows), [rule])["rows"][0]["n"]
    negative = execute(make(rows), [{"op": "not", "condition": rule}])["rows"][0]["n"]
    assert positive + negative == 1


@pytest.mark.parametrize(
    "candidate,needle,normalization",
    [
        (" PETER ", "peter", {"case_sensitive": False, "trim": True}),
        ("Straße", "STRASSE", {"case_sensitive": False}),
        ("Jose\u0301", "José", {"unicode": "nfc"}),
        ("Ｐｅｔｅｒ", "Peter", {"unicode": "nfkc"}),
    ],
)
def test_normalized_exact_preserves_group_values(candidate, needle, normalization):
    engine = make([{"actor": {"name": candidate}}])
    result = execute(
        engine,
        [leaf("eq", needle, normalization=normalization)],
        group_by=[{"field": "/actor/name", "as": "original"}],
    )
    assert result["rows"] == [
        {"original": candidate, "n": 1, "group_key_status": {"original": "present"}}
    ]


@pytest.mark.parametrize(
    "op,value,expected",
    [
        ("contains", ".*", 1),
        ("contains", "%", 1),
        ("contains", "_", 1),
        ("like", r"Pet\%", 1),
        ("like", r"Pet\_", 1),
        ("like", r"Pet\\", 1),
        ("like", "Pet_r", 2),
        ("like", "Pet%", 6),
        ("eq", "", 1),
    ],
)
def test_literals_wildcards_escaping_and_multiline(op, value, expected):
    rows = [
        {"actor": {"name": v}} for v in ["Pete.*", "Pet%", "Pet_", "Pet\\", "Peter", "Pet\nr", ""]
    ]
    assert execute(make(rows), [leaf(op, value)])["rows"] == [{"n": expected}]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Peter", True),
        ("Peter-Johnson", True),
        ("Peter_Johnson", False),
        ("Peter's", True),
        ("Peter@example.invalid", True),
        ("Peterson", False),
        ("Peter\u0301", False),
    ],
)
def test_rust_unicode_word_boundaries(value, expected):
    assert execute(make([{"actor": {"name": value}}]), [leaf("word")])["rows"] == [
        {"n": int(expected)}
    ]


@pytest.mark.parametrize("algorithm", ["ratio", "wratio", "token_sort"])
def test_fuzzy_all_distinct_values_inclusive_cutoff_and_duplicates(algorithm, monkeypatch):
    scorer = {"ratio": fuzz.ratio, "wratio": fuzz.WRatio, "token_sort": fuzz.token_sort_ratio}[
        algorithm
    ]
    values = ["Peter", "Pter", "Peter Johnson", "Johnson Peter", "Peterson"]
    rows = [{"actor": {"name": v}} for v in values for _ in range(3)] + [
        {},
        {"actor": {"name": None}},
    ]
    threshold = scorer("Peter", "Pter", processor=None)
    expected = 3 * sum(scorer("Peter", v, processor=None) >= threshold for v in values)
    engine = make(rows)
    node = {**fuzzy(), "algorithm": algorithm, "min_score": threshold}
    result = execute(engine, [node])
    assert result["rows"] == [{"n": expected}]
    assert result["matching"]["comparisons"] == len(values)
    assert result["matching"]["predicate_complete"]


def test_casefold_length_changes_like_underscore():
    engine = make([{"actor": {"name": "ß"}}])
    assert execute(engine, [leaf("like", "_", normalization={"case_sensitive": False})])[
        "rows"
    ] == [{"n": 0}]
    assert execute(engine, [leaf("ilike", "__")])["rows"] == [{"n": 1}]
    assert execute(engine, [leaf("ilike", "SS", normalization={"unicode": "nfkc"})])["rows"] == [
        {"n": 1}
    ]


@pytest.mark.parametrize(
    "rule,code",
    [
        (leaf("contains", ""), "MATCH_PATTERN_INVALID"),
        (leaf("fuzzy", "", algorithm="ratio", min_score=85), "MATCH_FUZZY_QUERY_TOO_SHORT"),
        (leaf("word", ""), "MATCH_PATTERN_INVALID"),
        (leaf("fuzzy", "Li", algorithm="ratio", min_score=85), "MATCH_FUZZY_QUERY_TOO_SHORT"),
        ({**fuzzy(), "algorithm": "unknown"}, "MATCH_FUZZY_ALGORITHM_INVALID"),
        ({**fuzzy(), "min_score": True}, "MATCH_FUZZY_THRESHOLD_INVALID"),
        ({**fuzzy(), "min_score": -1}, "MATCH_FUZZY_THRESHOLD_INVALID"),
        ({**fuzzy(), "min_score": 101}, "MATCH_FUZZY_THRESHOLD_INVALID"),
        ({**fuzzy(), "min_score": 69}, "MATCH_FUZZY_THRESHOLD_INVALID"),
        (leaf("like", "Pet\\"), "MATCH_PATTERN_INVALID"),
        (leaf("like", r"Pet\x"), "MATCH_PATTERN_INVALID"),
        (leaf("like", "%"), "MATCH_REGEX_POLICY"),
        (leaf("regex", ".*"), "MATCH_REGEX_POLICY"),
        (leaf("regex", "["), "MATCH_REGEX_INVALID"),
        (leaf("regex", r"(?<=P)eter"), "MATCH_REGEX_INVALID"),
        (leaf("regex", r"(Peter)\1"), "MATCH_REGEX_INVALID"),
        (leaf("regex", "(?s)Peter"), "MATCH_REGEX_POLICY"),
        (leaf("regex", "P" * 513), "MATCH_REGEX_POLICY"),
        (leaf("regex", "Peter", normalization={"unicode": "nfc"}), "MATCH_NORMALIZATION_INVALID"),
        (leaf("regex", "Peter", normalization={"trim": True}), "MATCH_NORMALIZATION_INVALID"),
        (
            leaf("ilike", "Peter", normalization={"case_sensitive": True}),
            "MATCH_NORMALIZATION_INVALID",
        ),
        (
            leaf("regex", "(?i)Peter", normalization={"case_sensitive": True}),
            "MATCH_NORMALIZATION_INVALID",
        ),
        (leaf("eq", 1, normalization={"trim": True}), "MATCH_NORMALIZATION_INVALID"),
        (
            leaf("contains", "Peter", normalization={"unicode": "nfd"}),
            "MATCH_NORMALIZATION_INVALID",
        ),
    ],
)
def test_structured_errors_validate_explain_and_execute(rule, code):
    engine = make()
    for response in [
        engine.validate_query(text([rule])),
        engine.explain_query(text([rule])),
        execute(engine, [rule]),
    ]:
        assert response["error"]["code"] == code, response
        assert response["error"]["message"] == CATALOG[code]
        assert "Peter" not in json.dumps(response["error"]["details"])


def test_unknown_hidden_and_nonstring_fields_checked_before_any_match():
    engine = make(principal=Principal(fields=frozenset({"/actor/name"})))
    for field in ["/secret", "/absent"]:
        rule = {
            "match": {
                "fields": ["/actor/name", field],
                "patterns": [{"op": "contains", "value": "Peter"}],
            }
        }
        assert execute(engine, [rule])["error"]["code"] == "ACCESS_FIELD_DENIED"
    assert (
        execute(make(), [{**fuzzy(), "field": "/absent"}])["error"]["code"] == "DATA_FIELD_UNKNOWN"
    )
    for value, code in [
        (1, "QUERY_OPERATOR_TYPE"),
        ([], "DATA_FIELD_NOT_SCALAR"),
        ({}, "DATA_FIELD_NOT_SCALAR"),
    ]:
        assert execute(make([{"actor": {"name": value}}]), [fuzzy()])["error"]["code"] == code
    assert (
        execute(make([{"actor": {"name": "Peter"}}, {"actor": {"name": 1}}]), [fuzzy()])["error"][
            "code"
        ]
        == "DATA_FIELD_TYPE_CONFLICT"
    )


def test_safe_scalar_cast_and_no_entity_inference():
    engine = make([{"actor": {"name": 123}}])
    result = execute(
        engine,
        [leaf("contains", "23")],
        casts=[{"field": "/actor/name", "to": "string", "on_error": "reject"}],
    )
    assert result["rows"] == [{"n": 1}]
    for key in [
        "entity_resolution",
        "entity_inference",
        "resolve_entities",
        "identities",
        "aliases",
    ]:
        assert (
            execute(engine, **{key: True})["error"]["code"] == "MATCH_ENTITY_INFERENCE_UNSUPPORTED"
        )


def test_fixture_is_synthetic_and_includes_required_cases():
    rows = records()
    assert len(rows) >= 15
    assert len({r["service"] for r in rows}) == 2
    peters = [r for r in rows if r.get("actor", {}).get("name") == "Peter"]
    assert len({r["actor"]["id"] for r in peters}) == 2
    assert any(
        "\n" in r.get("actor", {}).get("name", "")
        for r in rows
        if isinstance(r.get("actor", {}).get("name"), str)
    )


def test_default_regex_case_mode_and_ilike_without_input_mutation():
    engine = make([{"actor": {"name": "peter"}}])
    for rule in [
        leaf("regex", "(?i)^Peter$"),
        leaf("regex", "^Peter$", normalization={"case_sensitive": False}),
    ]:
        assert execute(engine, [rule])["rows"] == [{"n": 1}]
    assert engine.describe("matching")["fields"]["/actor/name"]["type"] == "string"
    engine.limits = replace(engine.limits, allow_match_catch_all=True)
    assert execute(engine, [leaf("like", "%")])["rows"] == [{"n": 1}]
