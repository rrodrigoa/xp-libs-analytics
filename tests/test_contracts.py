import json
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import query_text, run

from xp_libs_analytics import Limits, Principal
from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.interfaces import (
    InlineJsonSource,
    InMemoryObjectSource,
    InputPort,
    JsonResultSink,
    OutputPort,
    QueryDefinition,
    QueryExecution,
    SourceDescriptor,
)
from xp_libs_analytics.models import AnalyticsQuery


def test_schema_snapshot():
    assert AnalyticsQuery.model_json_schema() == json.loads(
        Path("tests/fixtures/query-schema.json").read_text()
    )


def test_ports_source_sink_substitution(engine):
    for source in [InlineJsonSource(), InMemoryObjectSource()]:
        records = source.read('[{"arbitrary": 1}]', Principal(), Limits())
        handle = engine.register_records("dataset_5", records)
        with engine._prepare(query_text(handle)) as (plan, _, _):
            pass  # Plan owns immutable projected values after resolution.
        definition = QueryDefinition("definition", plan)
        execution = QueryExecution("execution", definition.id, "RUNNING")
        assert execution.definition_id == definition.id
        assert InputPort(handle.name).mode == "snapshot"
        assert OutputPort().format == "json"
        assert SourceDescriptor("inline", "host", "local", "hash").redacted is False
        result = engine.query_yaml(query_text(handle))
        assert JsonResultSink().write(result, Principal()) == result
        engine.unregister_dataset(handle.name)


def test_sdk_file_capabilities_status_error_boundaries(engine, tmp_path, monkeypatch):
    handle = engine.register_records("dataset_1", [{"x": 1}])
    path = tmp_path / "q.yaml"
    path.write_text(query_text(handle))
    assert engine.query_file(path)["rows"] == [{"n": 1}]
    assert engine.query_file(path.with_suffix(".txt"))["error"]["code"] == "QUERY_MALFORMED"
    assert (
        engine.query_file(path.with_name("missing.yaml"))["error"]["code"] == "QUERY_YAML_INVALID"
    )
    path.write_bytes(b"\xff")
    assert engine.query_file(path)["error"]["code"] == "QUERY_YAML_INVALID"
    assert len(engine.capabilities()["aggregations"]) == 20
    engine.limits = replace(engine.limits, min_samples=2)
    assert engine.query_yaml(query_text(handle))["status"] == "INSUFFICIENT_DATA"

    def failure(*args):
        raise RuntimeError("PRIVATE RECORD")

    monkeypatch.setattr(engine, "_prepare", failure)
    assert engine.query_yaml(query_text(handle))["error"]["code"] == "EXECUTION_BACKEND_ERROR"
    assert engine.validate_query(query_text(handle))["error"]["code"] == "INTERNAL_ERROR"


def test_group_internal_alias_collisions(engine):
    for alias in ["gp0", "a0", "v0", "p0", "g0"]:
        result = run(engine, [{"x": 1}, {}], group_by=[{"field": "/x", "as": alias}])
        assert len(result["rows"]) == 2
        assert alias in result["rows"][0]


@pytest.mark.parametrize(
    "field,op,value,code",
    [
        ("/object", "eq", 1, "DATA_FIELD_NOT_SCALAR"),
        ("/mixed", "eq", 1, "DATA_FIELD_TYPE_CONFLICT"),
        ("/b", "gt", True, "QUERY_OPERATOR_TYPE"),
        ("/t", "eq", "naive", "QUERY_OPERATOR_TYPE"),
    ],
)
def test_predicate_semantic_types(engine, field, op, value, code):
    h = engine.register_records(
        "dataset_2",
        [{"object": {}, "mixed": 1, "b": True, "t": "2026-11-06T00:00:00Z"}, {"mixed": "a"}],
    )
    casts = [{"field": "/t", "to": "datetime", "format": "rfc3339", "on_error": "reject"}]
    result = engine.query_yaml(
        query_text(h, casts=casts, filters=[{"field": field, "op": op, "value": value}])
    )
    assert result["error"]["code"] == code


def test_date_predicate_and_mixed_null_diagnostics(engine):
    h = engine.register_records(
        "dataset_3", [{"t": "2026-11-06T00:00:00Z", "x": 1}, {"x": "a"}, {"x": None}, {}]
    )
    result = engine.query_yaml(
        query_text(
            h,
            casts=[{"field": "/t", "to": "datetime", "format": "rfc3339", "on_error": "reject"}],
            filters=[{"field": "/t", "op": "eq", "value": "2026-11-06T00:00:00Z"}],
        ),
    )
    assert result["rows"] == [{"n": 1}]
    result = engine.query_yaml(query_text(h, filters=[{"field": "/x", "op": "is_null"}]))
    assert result["rows"] == [{"n": 2}]


def test_remaining_group_and_window_budget_branches(engine):
    from test_time import CAST, TIME

    h = engine.register_records("dataset_4", [{"x": {}, "t": "2026-11-06T10:00:00Z"}])
    assert (
        engine.query_yaml(query_text(h, group_by=[{"field": "/x", "as": "x"}]))["error"]["code"]
        == "QUERY_GROUP_INVALID"
    )
    engine.limits = replace(engine.limits, max_windows=1)
    args = {"casts": CAST, "time_range": TIME, "window": {"type": "tumbling", "size": "5m"}}
    assert engine.query_yaml(query_text(h, **args))["error"]["code"] == "RESOURCE_WINDOWS_LIMIT"
    engine.limits = replace(engine.limits, max_windows=10000, max_groups=1)
    assert engine.query_yaml(query_text(h, **args))["error"]["code"] == "QUERY_TOO_EXPENSIVE"


def test_parser_nontext_boundary():
    from xp_libs_analytics.parser import parse_yaml

    with pytest.raises(AnalyticsError) as caught:
        parse_yaml({})
    assert caught.value.code == "QUERY_MALFORMED"
