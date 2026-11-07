import json
from pathlib import Path

import pytest
import yaml
from fastmcp import Client

from xp_libs_analytics.errors import CATALOG
from xp_libs_analytics.mcp.server import create_server

pytestmark = pytest.mark.integration


async def call(client, name, args=None):
    result = await client.call_tool(name, args or {}, raise_on_error=False)
    assert result.structured_content is not None, result
    return result.structured_content


@pytest.mark.asyncio
async def test_real_client_all_tools_skill_and_Y23(engine):
    async with Client(create_server(engine, uploads=True)) as client:
        tools = await client.list_tools()
        assert len(tools) == 9
        for tool in tools:
            if tool.name in {
                "analytics_query",
                "analytics_validate_query",
                "analytics_explain_query",
            }:
                assert tool.input_schema["properties"]["query_yaml"]["type"] == "string"
        resources = await client.list_resources()
        assert len(resources) == 32
        skill = await client.read_resource("analytics://skill/generic-analytics")
        assert "NO_DATA" in skill[0].text
        language = await client.read_resource("analytics://query-language/v1")
        assert "ratio_if" in language[0].text
        matching = await client.read_resource("analytics://string-matching/v1")
        assert "RapidFuzz" in matching[0].text
        index = await client.read_resource("analytics://examples/index")
        assert len(json.loads(index[0].text)) == 28
        example = await client.read_resource("analytics://examples/01_count_all.yaml")
        assert "analytics.query/v1" in example[0].text
        capabilities = await call(client, "analytics_capabilities")
        assert capabilities["authoring_format"] == "yaml"
        loaded = await call(
            client, "analytics_load_json", {"name": "uploaded", "data": '[{"x": 2}]'}
        )
        handle = loaded["name"]
        assert (await call(client, "analytics_describe", {"name": handle}))["records"] == 1
        text = yaml.safe_dump(
            {
                "version": "analytics.query/v1",
                "dataset": {"name": handle},
                "aggregations": [{"op": "count", "as": "n"}],
            }
        )
        assert (await call(client, "analytics_validate_query", {"query_yaml": text}))[
            "status"
        ] == "OK"
        assert (await call(client, "analytics_explain_query", {"query_yaml": text}))[
            "status"
        ] == "OK"
        assert (await call(client, "analytics_query", {"query_yaml": text}))["rows"] == [{"n": 1}]
        for code in CATALOG:
            info = await call(client, "analytics_error_info", {"code": code})
            assert info == {"code": code, "message": CATALOG[code]}
        assert (await call(client, "analytics_unregister_dataset", {"name": handle}))[
            "status"
        ] == "OK"
        error = await client.call_tool("analytics_describe", {"name": handle}, raise_on_error=False)
        assert (
            error.is_error and error.structured_content["error"]["code"] == "DATASET_NAME_UNKNOWN"
        )


@pytest.mark.asyncio
async def test_mcp_disabled_upload_and_invalid_arguments(engine):
    async with Client(create_server(engine)) as client:
        assert (await call(client, "analytics_load_json", {"name": "uploaded", "data": "[]"}))[
            "error"
        ]["code"] == "ACCESS_UPLOAD_DISABLED"
        for args in [{}, {"query_yaml": {}}, {"query_yaml": "a: 1", "principal": "admin"}]:
            result = await call(client, "analytics_query", args)
            assert result["error"]["code"] == "MCP_INVALID_TOOL_CALL"
        result = await call(client, "unknown_tool")
        assert result["error"]["code"] == "MCP_INVALID_TOOL_CALL"


@pytest.mark.asyncio
async def test_all_examples_through_mcp(engine):
    from xp_libs_analytics.parser import parse_yaml

    async with Client(create_server(engine)) as client:
        for path in sorted(Path("examples/queries").glob("*.yaml")):
            data = (
                "matching_events.json"
                if int(path.stem[:2]) >= 18
                else "mixed_types.json"
                if path.stem.startswith("16_")
                else "events.json"
            )
            handle = engine.register_records(
                "dataset_1", json.loads(Path("examples/data", data).read_text(encoding="utf-8"))
            )
            document = parse_yaml(path.read_text(encoding="utf-8"))
            document["dataset"]["name"] = handle.name
            text = yaml.safe_dump(document)
            result = await call(client, "analytics_query", {"query_yaml": text})
            assert result["status"] in ("OK", "NO_DATA"), result
            engine.unregister_dataset(handle.name)


@pytest.mark.asyncio
async def test_session_isolation_and_real_worker():
    server = create_server(uploads=True)
    async with Client(server) as owner:
        loaded = await call(
            owner, "analytics_load_json", {"name": "uploaded", "data": '[{"x": 3}]'}
        )
        handle = loaded["name"]
        text = yaml.safe_dump(
            {
                "version": "analytics.query/v1",
                "dataset": {"name": handle},
                "aggregations": [{"op": "count", "as": "n"}],
            }
        )
        result = await call(owner, "analytics_query", {"query_yaml": text})
        assert result.get("rows") == [{"n": 1}], result
        async with Client(create_server()) as foreign:
            result = await call(foreign, "analytics_describe", {"name": handle})
            assert result["error"]["code"] == "DATASET_NAME_UNKNOWN"


@pytest.mark.asyncio
async def test_authenticated_host_resolver_revocation():
    from xp_libs_analytics import Principal

    principal = [Principal("authenticated-user")]
    server = create_server(uploads=True, principal_resolver=lambda: principal[0])
    async with Client(server) as client:
        loaded = await call(
            client, "analytics_load_json", {"name": "uploaded", "data": '[{"x": 1}]'}
        )
        principal[0] = Principal("authenticated-user", fields=frozenset())
        assert (await call(client, "analytics_describe", {"name": loaded["name"]}))["fields"] == {}
        principal[0] = Principal("different-user")
        assert (await call(client, "analytics_describe", {"name": loaded["name"]}))["error"][
            "code"
        ] == "DATASET_NAME_UNKNOWN"


@pytest.mark.asyncio
async def test_stdio_transport():
    import sys

    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(
        sys.executable, ["-m", "xp_libs_analytics.mcp.server", "--allow-uploads"], keep_alive=False
    )
    async with Client(transport) as client:
        assert (await call(client, "analytics_capabilities"))["mode"] == "snapshot"
        handle = (await call(client, "analytics_load_json", {"name": "uploaded", "data": "[{}]"}))[
            "name"
        ]
        text = yaml.safe_dump(
            {
                "version": "analytics.query/v1",
                "dataset": {"name": handle},
                "aggregations": [{"op": "count", "as": "n"}],
            }
        )
        result = await call(client, "analytics_query", {"query_yaml": text})
        assert result.get("rows") == [{"n": 1}], result
