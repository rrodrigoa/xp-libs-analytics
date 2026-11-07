"""Deterministic agent workflow fixtures, not a model-in-loop accuracy claim."""

import pytest
from conftest import query_text

pytestmark = pytest.mark.agent


@pytest.mark.parametrize(
    "operation",
    [
        "count",
        "count_non_null",
        "null_count",
        "missing_count",
        "count_distinct",
        "sum",
        "avg",
        "min",
        "max",
        "median",
        "p50",
        "p90",
        "p95",
        "p99",
        "stddev",
        "variance",
        "count_if",
        "sum_if",
        "avg_if",
        "ratio_if",
    ],
)
def test_discover_validate_execute_interpret_release(engine, operation):
    from oracle import aggregate

    rows = [{"arbitrary": 3}, {"arbitrary": 7}, {"arbitrary": None}, {}]
    handle = engine.register_records("dataset_1", rows)
    assert "/arbitrary" in engine.describe(handle.name)["fields"]
    agg = {"op": operation, "as": "metric"}
    if operation not in ("count", "count_if"):
        agg["field"] = "/arbitrary"
    if operation.endswith("_if"):
        agg["where"] = {"field": "/arbitrary", "op": "gt", "value": 4}
    text = query_text(handle, [agg])
    assert engine.validate_query(text)["status"] == "OK"
    result = engine.query_yaml(text)
    assert result["rows"][0]["metric"] == pytest.approx(aggregate(rows, agg))
    assert result["evidence"]["coverage"] == "UNKNOWN"
    engine.unregister_dataset(handle.name)


@pytest.mark.parametrize(
    "broken,code", [("average", "QUERY_UNKNOWN_OPERATOR"), ("sum", "DATA_FIELD_UNKNOWN")]
)
def test_safe_repair_without_authority_changes(engine, broken, code):
    handle = engine.register_records("dataset_2", [{"observed": 5}])
    text = query_text(handle, [{"op": broken, "field": "/guessed", "as": "metric"}])
    result = engine.validate_query(text)
    assert result["error"]["code"] == code
    assert engine.error_info(code)["message"] == result["error"]["message"]
    fields = engine.describe(handle.name)["fields"]
    field = next(iter(fields))
    repaired = query_text(handle, [{"op": "avg", "field": field, "as": "metric"}])
    assert engine.validate_query(repaired)["status"] == "OK"
    assert engine.query_yaml(repaired)["rows"] == [{"metric": 5.0}]
