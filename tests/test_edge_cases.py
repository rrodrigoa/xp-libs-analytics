import json
from dataclasses import replace

import pytest
from conftest import query_text, run

from xp_libs_analytics import AnalyticsError
from xp_libs_analytics.engine.backend import execute_plan
from xp_libs_analytics.engine.planner import check_predicate
from xp_libs_analytics.models import Eq


def test_precision_and_nonfinite_metrics(engine):
    h = engine.register_records("dataset_1", [{"x": 2**53 + 1}])
    result = engine.query_yaml(query_text(h, [{"op": "avg", "field": "/x", "as": "n"}]))
    assert result["error"]["code"] == "QUERY_OPERATOR_TYPE"
    h = engine.register_records("dataset_2", [{"x": "9007199254740993"}])
    result = engine.query_yaml(
        query_text(h, casts=[{"field": "/x", "to": "float64", "on_error": "reject"}])
    )
    assert result["error"]["code"] == "DATA_CAST_FAILED"
    h = engine.register_records("dataset_3", [{"x": 1e308}, {"x": 1e308}])
    result = engine.query_yaml(
        query_text(
            h,
            [{"op": "sum", "field": "/x", "as": "n"}],
            having=[{"field": "n", "op": "lt", "value": 0}],
        ),
    )
    assert result["error"]["code"] == "EXECUTION_BACKEND_ERROR"


def test_ratio_eligible_different_condition_field(engine):
    result = run(
        engine,
        [{"x": 1, "b": True}, {"x": None, "b": True}, {"x": 4, "b": False}],
        [
            {
                "op": "ratio_if",
                "field": "/x",
                "where": {"field": "/b", "op": "eq", "value": True},
                "as": "ratio",
            }
        ],
    )
    assert result["rows"] == [{"ratio": 0.5}]


def test_datetime_between_offsets_and_ordered_aggregates(engine):
    result = run(
        engine,
        [{"t": "2026-11-06T10:00:00Z"}],
        [
            {"op": "min", "field": "/t", "as": "minimum"},
            {"op": "max", "field": "/t", "as": "maximum"},
        ],
        casts=[{"field": "/t", "to": "datetime", "format": "rfc3339", "on_error": "reject"}],
        filters=[
            {
                "field": "/t",
                "op": "between",
                "lower": "2026-11-06T11:00:00+02:00",
                "upper": "2026-11-06T10:00:01Z",
            }
        ],
    )
    assert result["rows"] == [
        {"minimum": "2026-11-06T10:00:00Z", "maximum": "2026-11-06T10:00:00Z"}
    ]


def test_reject_nonscalar_literal_on_null_text_field(engine):
    h = engine.register_records("dataset_4", [{"x": None}])
    result = engine.query_yaml(
        query_text(h, filters=[{"field": "/x", "op": "contains", "value": 1}])
    )
    assert result["error"]["code"] == "QUERY_INVALID_LITERAL"


def test_compiler_defensive_checks(engine):
    from test_time import CAST, TIME

    h = engine.register_records(
        "dataset_5", [{"t": "2026-11-06T10:00:00Z", "x": 1}, {"t": "2026-11-06T10:05:00Z", "x": 2}]
    )
    with engine._prepare(query_text(h, group_by=[{"field": "/x", "as": "x"}])) as (plan, _, _):
        pass  # Plan owns immutable projected values after resolution.
    with pytest.raises(AnalyticsError) as caught:
        execute_plan(plan, replace(engine.limits, max_groups=1))
    assert caught.value.code == "RESOURCE_GROUPS_LIMIT"
    text = query_text(
        h,
        casts=CAST,
        time_range=TIME,
        window={"type": "tumbling", "size": "5m"},
        options={"include_empty_windows": True},
    )
    with engine._prepare(text) as (plan, _, _):
        pass  # Plan owns immutable projected values after resolution.
    broken = json.loads(plan.query_json)
    broken["time_range"] = None
    for invalid in [replace(plan, query_json=json.dumps(broken)), replace(plan, start=None)]:
        with pytest.raises(AnalyticsError) as caught:
            execute_plan(invalid, engine.limits)
        assert caught.value.code == "QUERY_WINDOW_INVALID"


def test_semantic_component_mixed_type_guard():
    with pytest.raises(AnalyticsError) as caught:
        check_predicate(Eq(op="eq", field="/x", value=1), {"/x": "mixed"})
    assert caught.value.code == "DATA_FIELD_TYPE_CONFLICT"


def test_private_unknown_yaml_key_not_echoed(engine):
    h = engine.register_records("dataset_6", [])
    result = engine.query_yaml(query_text(h) + "SECRET_TOKEN: other-secret\n")
    assert "SECRET_TOKEN" not in json.dumps(result)
    assert "other-secret" not in json.dumps(result)
    assert result["error"]["details"]["line"] >= 1
