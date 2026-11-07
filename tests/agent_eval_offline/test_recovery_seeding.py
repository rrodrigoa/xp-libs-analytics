import pytest
from inspect_ai.tool import ToolDef

from evals.agent_skill.recovery import execute_call, seed_failure
from evals.agent_skill.scenarios import load_scenarios
from evals.agent_skill.task import server_for
from xp_libs_analytics.errors import CATALOG


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", load_scenarios("recovery"), ids=lambda s: s.id)
async def test_actual_inspect_mcp_seed_errors(scenario):
    async with server_for(scenario) as server:
        tools = {ToolDef(t).name: t for t in await server.tools()}
        context = await execute_call(tools["analytics_capabilities"], {})
        handle = context["evaluation_dataset"]["name"]
        messages, call = await seed_failure(scenario, tools, handle)
        assert call["response"]["error"]["code"] == scenario.recovery.error_code
        assert call["response"]["error"]["message"] == CATALOG[scenario.recovery.error_code]
        assert len(messages) == 3
        assert "expected" not in messages[-1].content
        from evals.agent_skill.fixtures import bind_query

        corrected = await execute_call(
            tools["analytics_query"], {"query_yaml": bind_query(scenario.expected.query, handle)}
        )
        from evals.agent_skill.fixtures import oracle

        assert corrected["rows"] == oracle(scenario)["rows"]
