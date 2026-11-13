import json
from dataclasses import replace

import httpx2
import pytest
import yaml
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from xp_libs_analytics import AnalyticsEngine, AnalyticsError, AnalyticsQuery, Limits, Principal
from xp_libs_analytics.mcp.server import create_server

QUERY = {
    "version": "analytics.query/v1",
    "dataset": {"name": "observations"},
    "aggregations": [{"op": "sum", "field": "/value", "as": "total"}],
}
TOOL = "analytics_query_by_key"


async def call(client, arguments, tool=TOOL):
    result = await client.call_tool(tool, arguments, raise_on_error=False)
    assert result.structured_content is not None
    return result.structured_content


@pytest.mark.asyncio
async def test_registered_paths_use_current_snapshot_and_capture_definitions(engine):
    engine.register_records("observations", [{"value": 2}, {"value": 4}])
    typed = AnalyticsQuery.model_validate(QUERY)
    queries = {"Yaml": yaml.safe_dump(QUERY), "Typed": typed}
    server = create_server(engine, registered_queries=queries)
    queries.clear()
    typed.aggregations.clear()
    async with Client(server) as client:
        assert {tool.name for tool in await client.list_tools()} == {TOOL, "analytics_error_info"}
        assert await client.list_resources() == []
        assert (await call(client, {"code": "ACCESS_DENIED"}, "analytics_error_info"))[
            "code"
        ] == "ACCESS_DENIED"
        for expected in (6, 9):
            results = [await call(client, {"key": key}) for key in ("Yaml", "Typed")]
            assert results[0]["rows"] == results[1]["rows"] == [{"total": expected}]
            assert results[0]["dataset"] == results[1]["dataset"]
            if expected == 6:
                engine.replace_records("observations", [{"value": 9}])
        assert results[1]["dataset"]["revision"] == 2


@pytest.mark.asyncio
async def test_registered_query_rejects_input_and_unsafe_yaml(engine):
    server = create_server(engine, registered_queries={"Known": "x: &anchor 1"})
    async with Client(server) as client:
        for args in (
            {},
            {"key": 1},
            {"key": "../secret.yaml"},
            {"key": "a" * 65},
            {"key": "Known", "context": "admin"},
            {"key": "Known", "query_yaml": "version: analytics.query/v1"},
        ):
            assert (await call(client, args))["error"]["code"] == "MCP_INVALID_TOOL_CALL"
        for key in ("unknownPrivateKey", "known"):
            result = await call(client, {"key": key})
            assert result["error"]["code"] == "ACCESS_DENIED"
            assert key not in json.dumps(result)
        assert (await call(client, {"key": "Known"}))["error"]["code"] == (
            "QUERY_YAML_ANCHOR_FORBIDDEN"
        )
        assert (await call(client, {"query_yaml": "a: 1"}, "analytics_query"))["error"][
            "code"
        ] == "MCP_INVALID_TOOL_CALL"


def test_invalid_registered_configuration():
    with pytest.raises(ValueError, match="Uploads"):
        create_server(uploads=True, registered_queries={})
    with pytest.raises(ValueError, match="Invalid registered query key"):
        create_server(registered_queries={"../query.yaml": "text"})
    with pytest.raises(AnalyticsError) as error:
        create_server(registered_queries={"bad": {}})
    assert error.value.code == "QUERY_MALFORMED"


@pytest.mark.asyncio
async def test_registered_queries_apply_context_policy_and_shared_quota():
    engine = AnalyticsEngine(limits=Limits(max_queries_per_minute=2))
    engine.register_records("observations", [{"value": 4}])
    restricted = engine._authorized_view(replace(engine.principal, fields=frozenset()))
    other = AnalyticsEngine(principal=Principal("other"), store=engine.store)
    current = [restricted]
    server = create_server(
        context_resolver=lambda: current[0],
        registered_queries={"total": AnalyticsQuery.model_validate(QUERY)},
    )
    async with Client(server) as client:
        args = {"key": "total"}
        assert (await call(client, args))["error"]["code"] == "ACCESS_FIELD_DENIED"
        current[0] = other
        assert (await call(client, args))["error"]["code"] == "DATASET_NAME_UNKNOWN"
        current[0] = engine
        assert (await call(client, args))["rows"] == [{"total": 4}]
        assert (await call(client, args))["error"]["code"] == "QUERY_TOO_EXPENSIVE"


@pytest.mark.asyncio
async def test_registered_query_over_http_requires_trusted_resolver(engine):
    engine.register_records("observations", [{"value": 4}])
    server = create_server(
        engine, registered_queries={"total": AnalyticsQuery.model_validate(QUERY)}
    )
    app = server.http_app(stateless_http=True, json_response=True)
    transport = StreamableHttpTransport(
        "http://localhost/mcp",
        httpx_client_factory=lambda **kwargs: httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), **kwargs
        ),
    )
    async with app.router.lifespan_context(app), Client(transport) as client:
        assert (await call(client, {"key": "total"}))["error"]["code"] == "ACCESS_DENIED"


def test_typed_sdk_revalidates_mutated_query_and_applies_size_budget(engine):
    query = AnalyticsQuery.model_validate(QUERY)
    tiny = AnalyticsEngine(limits=Limits(max_query_bytes=8))
    assert tiny.query_typed(query)["error"]["code"] == "QUERY_TOO_EXPENSIVE"
    query.aggregations.clear()
    assert engine.query_typed(query)["error"]["code"] == "QUERY_MALFORMED"
