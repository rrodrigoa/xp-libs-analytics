import json
from pathlib import Path

import pytest
from conftest import run
from hypothesis import given, settings
from hypothesis import strategies as st
from oracle import aggregate, predicate

from xp_libs_analytics import AnalyticsEngine
from xp_libs_analytics.models import AGG_OPS
from xp_libs_analytics.models import LEGACY_FILTER_OPS as FILTER_OPS

ROWS = [
    {"x": 0, "text": "a.*é", "b": False},
    {"x": 1, "text": "Alpha", "b": True},
    {"x": 4, "text": "alphaé"},
    {"x": -3, "text": "é"},
    {"x": None, "text": None},
    {},
]


def leaf(op):
    n = {"op": op, "field": "/x"}
    if op in ("contains", "starts_with", "ends_with"):
        n.update(field="/text", value="é" if op != "starts_with" else "a")
    elif op in ("in", "not_in"):
        n["values"] = [0, 4]
    elif op == "between":
        n.update(lower=0, upper=4)
    elif op not in ("is_null", "is_not_null", "is_missing", "is_present"):
        n["value"] = 1
    return n


@pytest.mark.parametrize("op", FILTER_OPS)
def test_all_19_predicate_operators(engine, op):
    node = (
        {"op": op, "conditions": [leaf("gt"), leaf("lt")]}
        if op in ("and", "or")
        else {"op": "not", "condition": leaf("eq")}
        if op == "not"
        else leaf(op)
    )
    result = run(engine, ROWS, filters=[node])
    assert result["rows"] == [{"n": sum(predicate(r, node) is True for r in ROWS)}]


@pytest.mark.parametrize("op", AGG_OPS)
@pytest.mark.parametrize("rows", [ROWS, [{"x": None}, {}], [{"x": 8}], [{"x": 1}, {"x": 2.5}]])
def test_all_20_aggregate_operators(engine, op, rows):
    agg = {"op": op, "as": "metric"}
    if op not in ("count", "count_if"):
        agg["field"] = "/x"
    if op.endswith("_if"):
        agg["where"] = {"field": "/x", "op": "gt", "value": 0}
    value = run(engine, rows, [agg])["rows"][0]["metric"]
    expected = aggregate(rows, agg)
    assert value == pytest.approx(expected) if expected is not None else value is None


@pytest.mark.parametrize("op", ["in", "not_in"])
@pytest.mark.parametrize("values", [[1, None], [None], [1]])
def test_membership_unknown(engine, op, values):
    node = {"field": "/x", "op": op, "values": values}
    assert run(engine, ROWS, filters=[node])["rows"][0]["n"] == sum(
        predicate(r, node) is True for r in ROWS
    )


def test_pointer_empty_escaped_and_opaque_arrays(engine):
    rows = [{"": 3, "a/b": {"~x": 5}, "v0": 9, "items": [1, 2]}]
    result = run(
        engine,
        rows,
        [{"op": "sum", "field": "/a~1b/~0x", "as": "v0"}, {"op": "min", "field": "/", "as": "a0"}],
    )
    assert result["rows"] == [{"v0": 5, "a0": 3}]


def test_missing_and_null_groups_distinct(engine):
    result = run(engine, [{"x": 1}, {"x": None}, {}], group_by=[{"field": "/x", "as": "key"}])
    assert len(result["rows"]) == 3
    assert {r["group_key_status"]["key"] for r in result["rows"]} == {"present", "null", "missing"}


def test_sort_having_limit(engine):
    rows = [{"k": "a", "x": 1}, {"k": "b", "x": 3}, {"k": "c", "x": None}]
    result = run(
        engine,
        rows,
        [{"op": "sum", "field": "/x", "as": "total"}],
        group_by=[{"field": "/k", "as": "key"}],
        having=[{"field": "total", "op": "is_not_null"}],
        order_by=[{"field": "total", "direction": "desc", "nulls": "first"}],
        limit=1,
    )
    assert result["truncated"] and result["rows"][0]["key"] == "b"


@pytest.mark.parametrize(
    "path", sorted(Path("examples/queries").glob("*.yaml")), ids=lambda p: p.stem
)
def test_Y26_examples(engine, path):
    import yaml

    from xp_libs_analytics.parser import parse_yaml

    rows = json.loads(
        Path(
            "examples/data",
            "matching_events.json"
            if int(path.stem[:2]) >= 18
            else "mixed_types.json"
            if path.stem.startswith("16_")
            else "events.json",
        ).read_text(encoding="utf-8")
    )
    handle = engine.register_records("dataset_1", rows)
    document = parse_yaml(path.read_text(encoding="utf-8"))
    document["dataset"]["name"] = handle.name
    text = yaml.safe_dump(document)
    assert engine.validate_query(text)["status"] == "OK"
    result = engine.query_yaml(text)
    assert result["status"] in ("OK", "NO_DATA")
    first = result["rows"][0]
    if path.stem.startswith("01_"):
        assert first["rows"] == 12
    if path.stem.startswith("02_"):
        assert first == {"rows": 6, "observed": 5}
    if path.stem.startswith("08_"):
        assert next(iter(first.values())) == 0.3
    if path.stem.startswith("09_"):
        assert sorted(r["events"] for r in result["rows"]) == [1, 1, 1, 1, 3, 5]
    if path.stem.startswith("16_"):
        assert first["avg_metric"] == 7.25


@given(st.lists(st.one_of(st.none(), st.integers(-1000, 1000)), min_size=1, max_size=50))
@settings(max_examples=60, deadline=None, derandomize=True)
def test_H_reconciliation_shuffle_quantiles(values):
    engine = AnalyticsEngine()
    rows = [{"x": v} for v in values] + [{}]
    aggs = [
        {"op": op, "as": op, **({"field": "/x"} if op != "count" else {})}
        for op in (
            "count",
            "count_non_null",
            "null_count",
            "missing_count",
            "median",
            "p50",
            "p90",
            "p95",
            "p99",
            "sum",
        )
    ]
    a = run(engine, rows, aggs)["rows"][0]
    b = run(engine, list(reversed(rows)), aggs)["rows"][0]
    assert a == b
    assert a["count"] == a["count_non_null"] + a["null_count"] + a["missing_count"]
    assert a["p50"] == a["median"]
    if a["p50"] is not None:
        assert a["p50"] <= a["p90"] <= a["p95"] <= a["p99"]


def test_empty_snapshot_and_no_match(engine):
    assert run(engine, [])["status"] == "NO_DATA"
    assert run(engine, ROWS, filters=[{"field": "/x", "op": "gt", "value": 100}])["rows"] == [
        {"n": 0}
    ]
