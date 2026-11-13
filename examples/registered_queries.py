"""Run both parameterized query forms through a local MCP client."""

import asyncio
from typing import Annotated

import polars as pl
from fastmcp import Client
from pydantic import BaseModel, Field

from xp_libs_analytics import AnalyticsEngine, ParameterizedYamlQuery, PolarsQuery
from xp_libs_analytics.mcp.server import create_server


class Minimum(BaseModel):
    minimum: Annotated[int, Field(ge=0, le=100)] = 2


def count_values(frame: pl.DataFrame, parameters: BaseModel) -> pl.DataFrame:
    assert isinstance(parameters, Minimum)  # noqa: S101 -- host-owned example contract
    return frame.filter(pl.col("/value") >= parameters.minimum).select(
        pl.len().cast(pl.Int64).alias("count")
    )


YAML_COUNT = ParameterizedYamlQuery(
    """version: analytics.query/v1
dataset: {name: observations}
filters:
  - {field: /value, op: gte, value: {$param: minimum}}
aggregations:
  - {op: count, as: count}
""",
    Minimum,
)
POLARS_COUNT = PolarsQuery("observations", ("/value",), count_values, Minimum, {"count": "integer"})


async def main() -> None:
    engine = AnalyticsEngine()
    engine.register_records("observations", [{"value": 1}, {"value": 3}, {"value": 4}])
    server = create_server(
        engine,
        registered_queries={"yaml_count": YAML_COUNT, "polars_count": POLARS_COUNT},
        generated_tools=True,
    )
    async with Client(server) as client:
        yaml_result = await client.call_tool(
            "analytics_query_by_key", {"key": "yaml_count", "parameters": {"minimum": 3}}
        )
        polars_result = await client.call_tool("analytics_registered_polars_count", {"minimum": 3})
        for result in (yaml_result, polars_result):
            if result.structured_content is None or result.structured_content["rows"] != [
                {"count": 2}
            ]:
                raise RuntimeError("Unexpected registered query result")
            print(result.structured_content["rows"])


if __name__ == "__main__":
    asyncio.run(main())
