import json
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

import polars as pl
import pytest
from fastmcp import Client
from pydantic import BaseModel, Field

from examples.registered_queries import POLARS_COUNT, YAML_COUNT, Minimum, count_values
from xp_libs_analytics import (
    AnalyticsEngine,
    AnalyticsError,
    Limits,
    ParameterizedYamlQuery,
    PolarsQuery,
)
from xp_libs_analytics.engine import worker
from xp_libs_analytics.engine.native import NativeWorkerRequest, import_reference, prepare_native
from xp_libs_analytics.mcp.server import create_server


class Choice(StrEnum):
    A = "a"


class Parameters(BaseModel):
    text: Annotated[str, Field(max_length=64)]
    when: datetime
    choice: Choice
    flags: Annotated[list[bool], Field(max_length=2)] = [True]


def summarize(frame: pl.DataFrame, parameters: BaseModel) -> pl.DataFrame:
    assert isinstance(parameters, Parameters)
    assert isinstance(parameters.when, datetime) and parameters.choice is Choice.A
    assert parameters.flags == [True]
    assert frame.columns == ["row_index", "/value", "present:/value"]
    return frame.select(
        pl.len().cast(pl.Int64).alias("rows"),
        (~pl.col("present:/value")).sum().cast(pl.Int64).alias("missing"),
        (pl.col("present:/value") & pl.col("/value").is_null()).sum().cast(pl.Int64).alias("null"),
    )


@pytest.mark.asyncio
async def test_generated_and_generic_mcp_tools_share_schema_and_validation(engine):
    engine.register_records("observations", [{"value": 1}, {"value": 3}, {"value": 4}])
    server = create_server(
        engine,
        registered_queries={"yaml": YAML_COUNT, "native": POLARS_COUNT},
        generated_tools=True,
    )
    async with Client(server) as client:
        tools = {tool.name: tool.input_schema for tool in await client.list_tools()}
        schema = await client.call_tool("analytics_describe_query", {"key": "yaml"})
        assert schema.structured_content["parameters_schema"] == tools["analytics_registered_yaml"]
        assert tools["analytics_registered_yaml"]["properties"]["minimum"]["maximum"] == 100
        for key in ("yaml", "native"):
            for tool, args in (
                ("analytics_query_by_key", {"key": key}),
                (f"analytics_registered_{key}", {"minimum": 3}),
            ):
                result = await client.call_tool(tool, args)
                assert result.structured_content["rows"] == [{"count": 2}]
            for parameters in (
                {"minimum": "3"},
                {"minimum": True},
                {"minimum": 101},
                {"dataset": "other"},
                {"transform": "evil.module"},
                {"schema": {}},
            ):
                for tool, args in (
                    ("analytics_query_by_key", {"key": key, "parameters": parameters}),
                    (f"analytics_registered_{key}", parameters),
                ):
                    result = await client.call_tool(tool, args, raise_on_error=False)
                    assert result.structured_content["error"]["code"] == "QUERY_PARAMETERS_INVALID"


def test_native_projection_parameters_isolation_and_full_aggregation():
    engine = AnalyticsEngine(
        isolated=True, native_transforms={"summary": summarize}, limits=Limits(max_rows=200)
    )
    engine.register_records(
        "observations", [{"value": 1, "secret": 5}] * 150 + [{"value": None}, {}]
    )
    query = PolarsQuery(
        "observations",
        ("/value",),
        summarize,
        Parameters,
        {"rows": "integer", "missing": "integer", "null": "integer"},
        max_output_rows=1,
    )
    params = {"text": "value", "when": "2026-11-12T00:00:00Z", "choice": "a"}
    result = engine.query_polars(query, params)
    assert result.get("rows") == [{"rows": 152, "missing": 1, "null": 1}], result
    assert (
        engine.query_polars(replace(query, transform=count_values), params)["error"]["code"]
        == "QUERY_NATIVE_ISOLATION_INVALID"
    )
    for invalid in ({"when": 0}, {"choice": "b"}, {"flags": [True, False, True]}, {"flags": [1]}):
        assert (
            engine.query_polars(query, params | invalid)["error"]["code"]
            == "QUERY_PARAMETERS_INVALID"
        )


def test_native_permissions_output_validation_and_telemetry():
    events = []
    engine = AnalyticsEngine(telemetry=events.append)
    engine.register_records("observations", [{"value": 3, "secret": {"nested": 4}}] * 2)
    restricted = engine._authorized_view(replace(engine.principal, fields=frozenset({"/value"})))
    denied = restricted.query_polars(replace(POLARS_COUNT, fields=("/secret/nested",)))
    assert denied["error"]["code"] == "ACCESS_FIELD_DENIED"
    invalid = engine.query_polars(replace(POLARS_COUNT, fields=("/secret",)))
    assert invalid["error"]["code"] == "QUERY_NATIVE_INPUT_INVALID"
    invalid = engine.query_polars(replace(POLARS_COUNT, output_schema={"count": "string"}))
    assert invalid["error"]["code"] == "QUERY_NATIVE_RESULT_INVALID"
    unbounded = replace(
        POLARS_COUNT,
        transform=lambda frame, _: frame.select(pl.col("/value").alias("count")),
        max_output_rows=1,
    )
    assert engine.query_polars(unbounded)["error"]["code"] == "RESOURCE_RESULT_LIMIT"
    assert engine.query_polars(POLARS_COUNT, {"minimum": 3})["status"] == "OK"
    assert events[-1]["outcome"] == "OK" and events[-1]["snapshot_revision"] == 1
    assert "minimum" not in str(events)


def test_yaml_structural_binding_and_resource_limits(engine):
    engine.register_records("observations", [{"value": 3}])
    for text in (
        YAML_COUNT.yaml.replace("name: observations", "name: {$param: minimum}"),
        YAML_COUNT.yaml.replace("op: gte", "op: {$param: minimum}"),
        YAML_COUNT.yaml.replace("$param: minimum", "$param: unknown"),
        YAML_COUNT.yaml.replace("value: {$param: minimum}", "value: {$param: minimum, extra: 2}"),
    ):
        result = engine.query_parameterized(replace(YAML_COUNT, yaml=text))
        assert result["error"]["code"] == "QUERY_PARAMETER_BINDING_INVALID"
    tiny = AnalyticsEngine(limits=Limits(max_scalar_chars=16))
    assert (
        tiny.query_parameterized(YAML_COUNT, {"minimum": "x" * 17})["error"]["code"]
        == "QUERY_PARAMETERS_LIMIT"
    )
    assert (
        engine.query_parameterized(YAML_COUNT, {"minimum": float("inf")})["error"]["code"]
        == "QUERY_PARAMETERS_INVALID"
    )

    payload = "x\n  op: eq\ndataset: {name: another_dataset}"
    engine.replace_records("observations", [{"value": payload}, {"value": "other"}])
    template = ParameterizedYamlQuery(
        YAML_COUNT.yaml.replace("op: gte", "op: eq").replace("$param: minimum", "$param: text"),
        Parameters,
    )
    result = engine.query_parameterized(
        template, {"text": payload, "when": "2026-11-12T00:00:00Z", "choice": "a"}
    )
    assert result["rows"] == [{"count": 1}]


@pytest.mark.parametrize(
    "changes",
    [
        {"fields": ("/value", "/value")},
        {"output_schema": {}},
        {"transform": None},
        {"max_output_rows": 0},
    ],
)
def test_native_configuration_rejects_invalid_contracts(changes):
    with pytest.raises(ValueError):
        replace(POLARS_COUNT, **changes)


def test_native_unsupported_projection_and_invalid_output(engine):
    engine.register_records("observations", [{"value": 3}])
    missing = replace(POLARS_COUNT, fields=("/missing",))
    assert engine.query_polars(missing)["error"]["code"] == "DATA_FIELD_UNKNOWN"
    engine.limits = replace(engine.limits, max_expanded_rows=0)
    assert engine.query_polars(POLARS_COUNT)["error"]["code"] == "QUERY_TOO_EXPENSIVE"
    engine.limits = replace(engine.limits, max_expanded_rows=10, max_result_bytes=600)
    for frame, kind, code in [
        (pl.DataFrame({"wrong": [1]}), "integer", "QUERY_NATIVE_RESULT_INVALID"),
        (pl.DataFrame({"count": [float("inf")]}), "float", "QUERY_NATIVE_RESULT_INVALID"),
        (pl.DataFrame({"count": ["x" * 601]}), "string", "RESOURCE_RESULT_LIMIT"),
    ]:
        query = replace(
            POLARS_COUNT, transform=lambda *_, output=frame: output, output_schema={"count": kind}
        )
        assert engine.query_polars(query)["error"]["code"] == code

    engine.limits = replace(engine.limits, max_result_bytes=4096)
    frame = pl.DataFrame({"count": [datetime(2026, 11, 12, tzinfo=UTC)]})
    query = replace(POLARS_COUNT, transform=lambda *_: frame, output_schema={"count": "datetime"})
    assert engine.query_polars(query)["rows"] == [{"count": "2026-11-12T00:00:00Z"}]


def test_worker_dispatch_and_registry_identity(engine, monkeypatch):
    with pytest.raises(ValueError, match="importable"):
        AnalyticsEngine(native_transforms={"closure": lambda *_: None})

    def impostor(*_):
        pass

    impostor.__module__ = count_values.__module__
    impostor.__qualname__ = count_values.__qualname__
    with pytest.raises(ValueError, match="module binding"):
        import_reference(impostor)
    engine.register_records("observations", [{"value": 3}])
    with engine.registry.snapshot("observations") as snapshot:
        plan = prepare_native(POLARS_COUNT, snapshot, engine.principal, engine.limits)
    request = NativeWorkerRequest(
        plan, import_reference(count_values), import_reference(Minimum), b"{}"
    )

    class Connection:
        result = None
        closed = False

        def send_bytes(self, payload):
            self.result = json.loads(payload)

        def close(self):
            self.closed = True

    monkeypatch.setattr(worker, "restrict_process", lambda _: None)
    connection = Connection()
    worker.run_worker(connection, request, engine.limits)
    assert connection.closed and connection.result["rows"] == [{"count": 1}]
    with pytest.raises(AnalyticsError) as error:
        replace(request, transform=request.model).execute(engine.limits)
    assert error.value.code == "QUERY_NATIVE_ISOLATION_INVALID"
