from dataclasses import replace

import pytest
from fastmcp import Client
from rapidfuzz import fuzz

from xp_libs_analytics.mcp.server import create_server

from .support import execute, fuzzy, leaf, make, records, text


def multi(fields=None, patterns=None, **kwargs):
    return {
        "match": {
            "fields": fields or ["/actor/name", "/actor/email"],
            "patterns": patterns
            or [
                {"op": "word", "value": "Peter"},
                {"op": "fuzzy", "value": "Peter", "algorithm": "ratio", "min_score": 80},
            ],
            **kwargs,
        }
    }


@pytest.mark.parametrize("op", ["count_if", "sum_if", "avg_if", "ratio_if"])
@pytest.mark.parametrize("rule", [fuzzy(), leaf("word"), leaf("regex", r"\APeter\z"), multi()])
def test_conditional_matching_and_all_denominators(op, rule):
    rows = [
        {"actor": {"name": "Peter", "email": "Peter@example.invalid"}, "x": 2},
        {"actor": {"name": "Pter", "email": "other@example.invalid"}, "x": 4},
        {"actor": {"name": None, "email": None}, "x": 6},
        {"x": None},
        {"actor": {"name": "Peter"}},
    ]
    agg = {"op": op, "as": "metric", "where": rule}
    if op != "count_if":
        agg["field"] = "/x"
    actual = execute(make(rows), aggregations=[{"op": "count", "as": "all"}, agg])
    fuzzy_rule = rule.get("op") == "fuzzy" or "match" in rule
    expected = {
        "count_if": 3 if fuzzy_rule else 2,
        "sum_if": 6 if fuzzy_rule else 2,
        "avg_if": 3.0 if fuzzy_rule else 2.0,
        "ratio_if": 2 / 3 if fuzzy_rule else 1 / 3,
    }[op]
    assert actual["rows"] == [{"all": 5, "metric": expected}]


@pytest.mark.parametrize("count", [1, 2, 10])
def test_any_fields_patterns_no_double_count_and_logical_not(count):
    fields = [f"/f{i}" for i in range(count)]
    rows = [{f"f{i}": "Peter" for i in range(count)}, {f"f{i}": None for i in range(count)}, {}]
    rule = multi(fields, [{"op": "eq", "value": "Peter"}, {"op": "contains", "value": "Peter"}])
    assert execute(make(rows), [rule])["rows"] == [{"n": 1}]
    assert execute(make(rows), [{"op": "not", "condition": rule}])["rows"] == [{"n": 0}]


def test_multi_and_not_contains_composition_and_unknown():
    rows = [
        {"a": "Peter", "b": "other", "system": False},
        {"a": "Peter", "b": None, "system": True},
        {"a": None, "b": None, "system": False},
    ]
    rule = {
        "op": "and",
        "conditions": [
            multi(["/a", "/b"], [{"op": "not_contains", "value": "William"}]),
            {"op": "not", "condition": {"field": "/system", "op": "eq", "value": True}},
        ],
    }
    assert execute(make(rows), [rule])["rows"] == [{"n": 1}]


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"fields": ["/actor/name"] * 2}, "QUERY_INVALID_LITERAL"),
        ({"fields": []}, "QUERY_MALFORMED"),
        ({"mode": "all"}, "QUERY_MALFORMED"),
        (
            {"patterns": [{"op": "eq", "value": "Peter", "normalization": {"trim": True}}]},
            "MATCH_NORMALIZATION_INVALID",
        ),
        (
            {"patterns": [{"op": "fuzzy", "value": "Peter", "min_score": 85}]},
            "MATCH_FUZZY_ALGORITHM_INVALID",
        ),
    ],
)
def test_multi_invalid_contract(updates, code):
    node = multi()
    node["match"].update(updates)
    assert execute(make(), [node])["error"]["code"] == code


def test_matching_grouping_having_order_limits_and_quality():
    rows = [
        {"name": "Peter", "group": "a", "x": 2},
        {"name": "Pter", "group": "a", "x": 4},
        {"name": "Peter", "group": "b", "x": 10},
        {"name": "Other", "group": "b", "x": 100},
        {"name": "Peter", "group": "a", "x": None},
        {"name": "Peter", "group": "a"},
    ]
    node = {**fuzzy(), "field": "/name"}
    aggregations = [
        {"op": "count", "as": "n"},
        {"op": "sum", "field": "/x", "as": "sum"},
        {"op": "avg", "field": "/x", "as": "mean"},
        {"op": "p95", "field": "/x", "as": "p95"},
        {"op": "count_distinct", "field": "/name", "as": "distinct"},
        {"op": "missing_count", "field": "/x", "as": "missing"},
        {"op": "null_count", "field": "/x", "as": "nulls"},
    ]
    result = execute(
        make(rows),
        [node],
        aggregations,
        group_by=[{"field": "/group", "as": "g"}],
        having=[{"field": "n", "op": "gt", "value": 1}],
        order_by=[{"field": "mean", "direction": "desc"}],
        limit=1,
    )
    assert result["rows"] == [
        {
            "g": "a",
            "n": 4,
            "sum": 6,
            "mean": 3.0,
            "p95": pytest.approx(3.9),
            "distinct": 2,
            "missing": 1,
            "nulls": 1,
            "group_key_status": {"g": "present"},
        }
    ]
    assert result["evidence"]["matched_rows"] == 5
    assert (
        execute(make(rows), [node], having=[leaf("word")])["error"]["code"]
        == "QUERY_HAVING_INVALID"
    )


@pytest.mark.parametrize(
    "window", [{"type": "tumbling", "size": "5m"}, {"type": "sliding", "size": "15m", "step": "5m"}]
)
def test_matching_temporal_boundaries_windows_and_relative_fixed_clock(window):
    engine = make()
    options = {
        "casts": [
            {"field": "/timestamp", "to": "datetime", "format": "rfc3339", "on_error": "reject"}
        ],
        "time_range": {
            "field": "/timestamp",
            "start": "2026-11-06T10:00:00Z",
            "end": "2026-11-06T10:10:00Z",
        },
        "window": window,
    }
    result = execute(engine, [leaf("contains")], **options)
    counts = [r["n"] for r in result["rows"]]
    assert counts == ([5, 4] if window["type"] == "tumbling" else [5, 9, 9, 4])
    assert result["evidence"]["matched_rows"] == 9
    assert result["matching"]["predicate_complete"]
    relative = execute(
        engine,
        [leaf("contains")],
        casts=options["casts"],
        time_range={"field": "/timestamp", "last_minutes": 60},
    )
    assert relative["rows"] == [{"n": 10}]
    assert (
        execute(
            engine,
            [leaf("contains")],
            **{
                **options,
                "time_range": {
                    **options["time_range"],
                    "start": "2026-11-06T10:15:00Z",
                    "end": "2026-11-06T10:20:00Z",
                },
            },
        )["status"]
        == "NO_DATA"
    )


def test_bad_cast_is_not_hidden_by_fuzzy_pushdown():
    rows = records() + [{"timestamp": "invalid", "actor": {"name": "other"}}]
    result = execute(
        make(rows),
        [fuzzy()],
        casts=[
            {"field": "/timestamp", "to": "datetime", "format": "rfc3339", "on_error": "reject"}
        ],
    )
    assert result["error"]["code"] == "DATA_CAST_FAILED"


@pytest.mark.parametrize(
    "filters",
    [
        [fuzzy()],
        [{"op": "or", "conditions": [fuzzy(), {"op": "eq", "field": "/status", "value": "ok"}]}],
        [{"op": "not", "condition": fuzzy()}],
        [
            {
                "op": "and",
                "conditions": [fuzzy(), {"op": "eq", "field": "/status", "value": "error"}],
            }
        ],
    ],
)
def test_pushdown_equivalence_under_or_not_and_conditional(filters):
    baseline = make(match_pushdown=False)
    optimized = make(match_pushdown=True)
    for engine in [baseline, optimized]:
        result = execute(
            engine,
            filters,
            [{"op": "count", "as": "n"}, {"op": "count_if", "where": fuzzy(), "as": "fuzzy"}],
        )
        assert "rows" in result, result
        if engine is baseline:
            expected = result["rows"]
        else:
            assert result["rows"] == expected


def test_distinct_scoring_cache_is_query_local_and_not_used_in_validation(monkeypatch):
    calls = []
    original = fuzz.ratio

    def score(a, b, **kwargs):
        calls.append(b)
        return original(a, b, **kwargs)

    monkeypatch.setattr(fuzz, "ratio", score)
    engine = make([{"actor": {"name": "Peter"}}] * 100 + [{"actor": {"name": "Pter"}}] * 100)
    aggs = [
        {"op": "count_if", "where": fuzzy(), "as": "a"},
        {"op": "count_if", "where": fuzzy(), "as": "b"},
    ]
    assert engine.validate_query(text(aggregations=aggs))["status"] == "OK"
    assert calls == []
    result = execute(engine, aggregations=aggs)
    assert result["rows"] == [{"a": 200, "b": 200}]
    assert sorted(calls) == ["Peter", "Pter"]
    assert result["matching"]["comparisons"] == 2
    calls.clear()
    engine.replace_records("matching", [{"actor": {"name": "William"}}])
    assert execute(engine, aggregations=aggs)["rows"] == [{"a": 0, "b": 0}]
    assert calls == ["William"]


@pytest.mark.asyncio
async def test_actual_mcp_matches_sdk_with_worker_and_no_tool_surface_expansion():
    engine = make()
    engine.limits = replace(engine.limits, force_matching_isolation=True)
    query = text([multi()], options={"matching_details": {"include": True, "top_values": 2}})
    sdk = engine.query_yaml(query)
    async with Client(create_server(engine)) as client:
        capabilities = (await client.call_tool("analytics_capabilities", {})).structured_content
        assert capabilities["matching"]["algorithms"] == ["ratio", "wratio", "token_sort"]
        assert "match" in capabilities["filters"]
        assert len(await client.list_tools()) == 9
        validated = await client.call_tool("analytics_validate_query", {"query_yaml": query})
        assert validated.structured_content["plan"]["matching"]["comparisons"] > 0
        actual = (
            await client.call_tool("analytics_query", {"query_yaml": query})
        ).structured_content
        assert sdk["rows"] == actual["rows"]
        assert sdk["matching"] == actual["matching"]
        error = await client.call_tool(
            "analytics_query", {"query_yaml": text([leaf("regex", "[")])}, raise_on_error=False
        )
        assert error.structured_content["error"]["code"] == "MATCH_REGEX_INVALID"
