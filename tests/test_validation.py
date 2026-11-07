import json
from dataclasses import replace

import pytest
from conftest import query_text

from xp_libs_analytics import AnalyticsEngine, AnalyticsError
from xp_libs_analytics.engine.planner import cast_value
from xp_libs_analytics.errors import CATALOG, ErrorCode


@pytest.mark.parametrize(
    "updates,code",
    [
        ({"version": "other"}, "QUERY_VERSION_UNSUPPORTED"),
        ({"limit": 0}, "QUERY_LIMIT_INVALID"),
        ({"limit": "10"}, "QUERY_LIMIT_INVALID"),
        ({"sources": []}, "QUERY_UNSUPPORTED_FEATURE"),
        ({"joins": []}, "QUERY_UNSUPPORTED_FEATURE"),
        ({"unions": []}, "QUERY_UNSUPPORTED_FEATURE"),
        ({"continuous": True}, "QUERY_UNSUPPORTED_FEATURE"),
        ({"outputs": []}, "QUERY_UNSUPPORTED_FEATURE"),
        ({"udf": "lambda"}, "QUERY_MALFORMED"),
        ({"group_by": [{"field": "/x", "as": "key"}] * 5}, "QUERY_GROUP_INVALID"),
        (
            {"group_by": [{"field": "/x", "as": "a"}, {"field": "/x", "as": "b"}]},
            "QUERY_GROUP_INVALID",
        ),
        ({"aggregations": [{"op": "sum", "field": "/absent", "as": "n"}]}, "DATA_FIELD_UNKNOWN"),
        ({"aggregations": [{"op": "avg", "field": "/text", "as": "n"}]}, "QUERY_OPERATOR_TYPE"),
        ({"aggregations": [{"op": "count", "as": "window_start"}]}, "QUERY_ALIAS_INVALID"),
        ({"aggregations": [{"op": "count", "as": "a-b"}]}, "QUERY_ALIAS_INVALID"),
        ({"aggregations": [{"op": "count", "as": "n"}] * 2}, "QUERY_ALIAS_INVALID"),
        ({"aggregations": [{"op": "count", "as": "n", "field": "/x"}]}, "QUERY_MALFORMED"),
        ({"aggregations": [{"op": "avg"}]}, "QUERY_MALFORMED"),
        ({"filters": [{"op": "eq", "field": "x", "value": 1}]}, "QUERY_INVALID_POINTER"),
        ({"filters": [{"op": "eq", "field": "/x", "value": True}]}, "QUERY_OPERATOR_TYPE"),
        ({"filters": [{"op": "contains", "field": "/x", "value": "a"}]}, "QUERY_OPERATOR_TYPE"),
        ({"filters": [{"op": "in", "field": "/x", "values": [1, "a"]}]}, "QUERY_INVALID_LITERAL"),
        (
            {"filters": [{"op": "between", "field": "/x", "lower": 2, "upper": 1}]},
            "QUERY_INVALID_LITERAL",
        ),
        (
            {"filters": [{"op": "between", "field": "/x", "lower": None, "upper": 1}]},
            "QUERY_INVALID_LITERAL",
        ),
        ({"order_by": [{"field": "missing"}]}, "QUERY_ORDER_INVALID"),
        ({"order_by": [{"field": "n", "direction": "wrong"}]}, "QUERY_ORDER_INVALID"),
        ({"having": [{"field": "/x", "op": "eq", "value": 1}]}, "QUERY_HAVING_INVALID"),
        ({"having": [{"field": "n", "op": "contains", "value": "a"}]}, "QUERY_HAVING_INVALID"),
        ({"options": {"include_empty_windows": True}}, "QUERY_EMPTY_WINDOW_UNSUPPORTED"),
        (
            {"casts": [{"field": "/x", "to": "datetime", "on_error": "reject"}]},
            "DATA_CAST_UNSUPPORTED",
        ),
        (
            {
                "casts": [
                    {"field": "/x", "to": "float64", "format": "epoch_s", "on_error": "reject"}
                ]
            },
            "DATA_CAST_UNSUPPORTED",
        ),
        (
            {"casts": [{"field": "/x", "to": "float64", "on_error": "reject"}] * 2},
            "DATA_CAST_UNSUPPORTED",
        ),
    ],
)
def test_negative_contract(engine, updates, code):
    import yaml

    handle = engine.register_records("dataset_1", [{"x": 1, "text": "label"}])
    document = yaml.safe_load(query_text(handle))
    document.update(updates)
    text = yaml.safe_dump(json.loads(json.dumps(document)))
    for result in [
        engine.validate_query(text),
        engine.explain_query(text),
        engine.query_yaml(text),
    ]:
        assert result["error"]["code"] == code, result
        assert result["error"]["message"] == CATALOG[code]


@pytest.mark.parametrize(
    "rows,agg,code",
    [
        ([{"x": 1}, {"x": "1"}], "avg", "DATA_FIELD_TYPE_CONFLICT"),
        ([{"x": 1}, {"x": False}], "count_non_null", "DATA_FIELD_TYPE_CONFLICT"),
        ([{"x": []}], "sum", "DATA_FIELD_NOT_SCALAR"),
        ([{"x": {}}], "min", "DATA_FIELD_NOT_SCALAR"),
        ([{"x": True}], "min", "QUERY_OPERATOR_TYPE"),
    ],
)
def test_type_conflicts(engine, rows, agg, code):
    h = engine.register_records("dataset_2", rows)
    result = engine.query_yaml(query_text(h, [{"op": agg, "field": "/x", "as": "n"}]))
    assert result["error"]["code"] == code


@pytest.mark.parametrize(
    "value,target,fmt,expected",
    [
        ("12.5", "float64", None, 12.5),
        ("12", "int64", None, 12),
        (1, "string", None, "1"),
        (True, "string", None, "true"),
        (False, "string", None, "false"),
    ],
)
def test_cast_success(value, target, fmt, expected):
    assert cast_value(value, target, fmt) == expected


@pytest.mark.parametrize(
    "value,target,fmt",
    [
        (True, "float64", None),
        ([], "string", None),
        ({}, "int64", None),
        ("nan", "float64", None),
        ("1e999", "float64", None),
        (2**53 + 1, "float64", None),
        ("9223372036854775808", "int64", None),
        (1.1, "int64", None),
        ("2026-11-06T10:00:00", "datetime", "rfc3339"),
        ("12", "datetime", "epoch_s"),
    ],
)
def test_cast_reject_and_null_accounting(engine, value, target, fmt):
    h = engine.register_records("dataset_3", [{"x": value}, {"x": None}, {}])
    spec = {"field": "/x", "to": target, "on_error": "reject"}
    if fmt:
        spec["format"] = fmt
    aggs = [
        {"op": op, "field": "/x", "as": op}
        for op in ["null_count", "missing_count", "count_non_null"]
    ]
    result = engine.query_yaml(query_text(h, aggs, casts=[spec]))
    assert result["error"]["code"] in ("DATA_CAST_FAILED", "DATA_FIELD_NOT_SCALAR")
    if type(value) in (dict, list):
        return
    spec["on_error"] = "null"
    result = engine.query_yaml(query_text(h, aggs, casts=[spec]))
    assert result["rows"] == [{"null_count": 2, "missing_count": 1, "count_non_null": 0}]
    assert result["evidence"]["field_quality"]["/x"]["cast_errors"] == 1
    assert result["warnings"] == ["DATA_CAST_FAILED"]


def test_predicate_budgets(engine):
    h = engine.register_records("dataset_4", [{"x": 1}])
    node = {"op": "eq", "field": "/x", "value": 1}
    for _ in range(4):
        node = {"op": "not", "condition": node}
    assert (
        engine.query_yaml(query_text(h, filters=[node]))["error"]["code"] == "QUERY_PREDICATE_LIMIT"
    )
    leaves = [{"op": "eq", "field": "/x", "value": 1}] * 20
    assert (
        engine.query_yaml(query_text(h, filters=[{"op": "and", "conditions": leaves}] * 2))[
            "error"
        ]["code"]
        == "QUERY_PREDICATE_LIMIT"
    )


def test_budgets_null_policy_output_and_quota(engine):
    h = engine.register_records("dataset_5", [{"x": i} for i in range(4)])
    engine.limits = replace(engine.limits, max_groups=2)
    assert (
        engine.query_yaml(query_text(h, group_by=[{"field": "/x", "as": "x"}]))["error"]["code"]
        == "RESOURCE_GROUPS_LIMIT"
    )
    engine.limits = replace(engine.limits, max_distinct=2)
    assert (
        engine.query_yaml(query_text(h, [{"op": "count_distinct", "field": "/x", "as": "n"}]))[
            "error"
        ]["code"]
        == "QUERY_TOO_EXPENSIVE"
    )
    engine.limits = replace(engine.limits, allow_null_cast=False)
    assert (
        engine.query_yaml(
            query_text(h, casts=[{"field": "/x", "to": "float64", "on_error": "null"}])
        )["error"]["code"]
        == "ACCESS_DENIED"
    )
    engine.limits = replace(engine.limits, max_result_bytes=1)
    assert engine.query_yaml(query_text(h))["error"]["code"] == "RESOURCE_RESULT_LIMIT"
    engine.limits = replace(engine.limits, max_queries_per_minute=1)
    assert engine.query_yaml(query_text(h))["error"]["code"] == "QUERY_TOO_EXPENSIVE"


@pytest.mark.parametrize("code", list(CATALOG))
def test_all_60_catalog_envelopes_and_code_enum(code):
    assert set(ErrorCode) == set(CATALOG)
    error = AnalyticsError(code, "$.filters[0]", line=1, column=2)
    result = error.envelope("correlation-id")
    assert result["query_id"] == "correlation-id"
    assert result["error"]["message"] == CATALOG[code]
    assert result["error"]["code"] == code
    assert result["error"]["path"] == "$.filters[0]"


def test_error_lookup_unknown():
    assert AnalyticsEngine.error_info("bad")["error"]["code"] == "MCP_INVALID_TOOL_CALL"


def test_sum_overflow_fails_clearly(engine):
    h = engine.register_records("dataset_6", [{"x": 2**63 - 1}, {"x": 1}])
    result = engine.query_yaml(query_text(h, [{"op": "sum", "field": "/x", "as": "n"}]))
    assert result["error"]["code"] == "EXECUTION_BACKEND_ERROR"
