import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from rapidfuzz import fuzz

from xp_libs_analytics import Principal

from .support import execute, fuzzy, leaf, make, text
from .test_composition import multi


@pytest.mark.parametrize(
    "policy,filters,code",
    [
        ({"max_fuzzy_candidates": 1}, [fuzzy()], "MATCH_CANDIDATE_BUDGET_EXCEEDED"),
        ({"max_fuzzy_comparisons": 1}, [fuzzy()], "MATCH_COMPLEXITY_BUDGET_EXCEEDED"),
        ({"max_match_value_chars": 3}, [fuzzy()], "MATCH_CANDIDATE_BUDGET_EXCEEDED"),
        ({"max_match_normalized_bytes": 1}, [fuzzy()], "MATCH_CANDIDATE_BUDGET_EXCEEDED"),
        ({"max_match_literal_chars": 3}, [fuzzy()], "MATCH_PATTERN_INVALID"),
        ({"min_fuzzy_query_chars": 10}, [fuzzy()], "MATCH_FUZZY_QUERY_TOO_SHORT"),
        ({"max_match_work": 1}, [fuzzy(), fuzzy("Peterson")], "MATCH_COMPLEXITY_BUDGET_EXCEEDED"),
        ({"max_match_fields": 1}, [multi()], "MATCH_COMPLEXITY_BUDGET_EXCEEDED"),
        ({"max_match_patterns": 1}, [multi()], "MATCH_COMPLEXITY_BUDGET_EXCEEDED"),
    ],
)
def test_resource_failure_is_never_a_partial_aggregate(policy, filters, code):
    engine = make(**policy)
    for result in [
        engine.validate_query(text(filters)),
        engine.explain_query(text(filters)),
        execute(engine, filters, limit=1),
    ]:
        assert result["error"]["code"] == code, result
        assert "rows" not in result


def test_candidate_limit_10001_never_truncates_and_safe_scope_reduces_work():
    rows = [{"actor": {"name": "Peter" + str(i)}, "scope": i == 0} for i in range(10001)]
    engine = make(rows)
    assert execute(engine, [fuzzy()])["error"]["code"] == "MATCH_CANDIDATE_BUDGET_EXCEEDED"
    filters = [fuzzy(), {"field": "/scope", "op": "eq", "value": True}]
    result = execute(engine, filters)
    assert result["rows"] == [{"n": 1}]
    assert result["matching"]["comparisons"] == 1
    assert (
        execute(engine, [{"op": "or", "conditions": filters}])["error"]["code"]
        == "MATCH_CANDIDATE_BUDGET_EXCEEDED"
    )


def test_top_values_and_limit_are_output_only_and_hmac_redaction_is_scoped():
    rows = [{"actor": {"name": v}} for v in ["Peter", "Pter", "Peterr", "Petre", "Peter", "Pter"]]
    engine = make(rows)
    for top in [1, 2, 20]:
        result = execute(
            engine,
            [fuzzy()],
            options={"matching_details": {"include": True, "top_values": top}},
            limit=1,
        )
        assert result["rows"] == [{"n": 6}]
        details = result["matching"]
        assert details["predicate_complete"] and details["comparisons"] == 4
        assert len(details["top_values"]) == min(top, 4)
        assert details["diagnostics_truncated"] == (top < 4)
        assert details["complete"] == (top >= 4)
        assert details["top_values"][0]["score"] == 100.0
        assert all(value["value"] is None and value["value_ref"] for value in details["top_values"])
        assert "Peter" not in json.dumps(details)
    first = execute(engine, [fuzzy()], options={"matching_details": {"include": True}})["matching"]
    assert (
        execute(engine, [fuzzy()], options={"matching_details": {"include": True}})["matching"]
        == first
    )
    second = execute(make(rows), [fuzzy()], options={"matching_details": {"include": True}})[
        "matching"
    ]
    assert second["top_values"][0]["value_ref"] != first["top_values"][0]["value_ref"]


def test_requested_diagnostics_without_matching_predicates_are_explicitly_empty():
    result = execute(make(), options={"matching_details": {"include": True}})
    assert result["rows"] == [{"n": 28}]
    assert result["matching"]["used"] is False
    assert result["matching"]["top_values"] == []
    assert result["matching"]["complete"] is True


def test_raw_diagnostics_need_host_and_field_authorization():
    option = {"matching_details": {"include": True, "include_raw_values": True}}
    for engine in [
        make(),
        make(allow_match_raw_values=True),
        make(principal=Principal(match_raw_fields=frozenset({"/actor/name"}))),
    ]:
        assert (
            execute(engine, [fuzzy()], options=option)["error"]["code"]
            == "MATCH_DIAGNOSTICS_UNAUTHORIZED"
        )
    engine = make(
        allow_match_raw_values=True,
        principal=Principal(match_raw_fields=frozenset({"/actor/name"})),
    )
    result = execute(
        engine,
        [
            multi(
                ["/actor/name"],
                [
                    {"op": "eq", "value": "Peter"},
                    {"op": "word", "value": "Peter"},
                    {"op": "fuzzy", "value": "Peter", "algorithm": "ratio", "min_score": 80},
                ],
            )
        ],
        options=option,
    )
    first = result["matching"]["top_values"][0]
    assert first["value"] == "Peter" and first["frequency"] == 2 and first["match_type"] == "exact"
    assert "score" not in first
    assert len(first["matched_rules"]) == 3
    assert first["matched_rules"][-1]["score"] == 100.0
    assert (
        execute(engine, [fuzzy()], options={"matching_details": {"include_raw_values": True}})[
            "error"
        ]["code"]
        == "QUERY_MALFORMED"
    )


def test_diagnostics_count_source_records_before_sliding_or_grouping_not_rule_hits():
    rows = [{"ts": "2026-11-06T10:01:00Z", "a": "Peter", "b": "Peter"}] * 3
    engine = make(
        rows,
        allow_match_raw_values=True,
        principal=Principal(match_raw_fields=frozenset({"/a", "/b"})),
    )
    result = execute(
        engine,
        [
            multi(
                ["/a", "/b"], [{"op": "eq", "value": "Peter"}, {"op": "contains", "value": "Peter"}]
            )
        ],
        casts=[{"field": "/ts", "to": "datetime", "format": "rfc3339", "on_error": "reject"}],
        time_range={"field": "/ts", "start": "2026-11-06T10:00:00Z", "end": "2026-11-06T10:10:00Z"},
        window={"type": "sliding", "size": "15m", "step": "5m"},
        options={"matching_details": {"include": True, "include_raw_values": True}},
    )
    assert sum(r["n"] for r in result["rows"]) == 9
    assert [v["frequency"] for v in result["matching"]["top_values"]] == [3, 3]


def test_replacement_during_fuzzy_execution_keeps_pinned_snapshot(monkeypatch):
    ready, resume = threading.Event(), threading.Event()
    original = fuzz.ratio

    def blocked(a, b, **kwargs):
        ready.set()
        assert resume.wait(10)
        return original(a, b, **kwargs)

    monkeypatch.setattr(fuzz, "ratio", blocked)
    engine = make([{"actor": {"name": "Peter"}}])
    old = engine.describe("matching")["revision"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(execute, engine, [fuzzy()])
        try:
            assert ready.wait(10)
            engine.replace_records("matching", [{"actor": {"name": "William"}}])
        finally:
            resume.set()
        result = pending.result(timeout=10)
    assert result["rows"] == [{"n": 1}]
    assert result["dataset"]["revision"] == old
    assert execute(engine, [fuzzy()])["rows"] == [{"n": 0}]


def test_fuzzy_budgets_include_conditional_predicates_and_normalization_expansion():
    engine = make(max_fuzzy_comparisons=2)
    assert (
        execute(engine, aggregations=[{"op": "count_if", "as": "n", "where": fuzzy()}])["error"][
            "code"
        ]
        == "MATCH_COMPLEXITY_BUDGET_EXCEEDED"
    )
    engine = make([{"actor": {"name": "ßß"}}], max_match_value_chars=3)
    assert (
        execute(engine, [leaf("contains", "s", normalization={"case_sensitive": False})])["error"][
            "code"
        ]
        == "MATCH_CANDIDATE_BUDGET_EXCEEDED"
    )


def test_regex_execution_is_automatically_isolated_and_times_out():
    engine = make()
    engine.limits = replace(engine.limits, force_matching_isolation=True, timeout_seconds=0.0001)
    assert execute(engine, [leaf("regex", "Peter")])["error"]["code"] == "RESOURCE_TIMEOUT"
