import json
import re

import pytest
from inspect_ai.model import ModelOutput, get_model

from evals.agent_skill.endpoint_security import private_execution
from evals.agent_skill.fixtures import bind_query
from evals.agent_skill.recovery import response_object
from evals.agent_skill.scenarios import load_scenarios
from evals.agent_skill.task import run_scenario


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identifier",
    [
        "aggregate-count",
        "recovery-unknown-field",
        "matching-misspelling",
        "recovery-matching-regex",
        "recovery-matching-score",
    ],
)
async def test_inspect_native_agent_with_mock_model_and_real_mcp(identifier):
    scenario = load_scenarios(scenario_id=identifier)[0]
    step = [0]

    def generate(messages, tools, tool_choice, config):
        handle = re.search(r"Authorized dataset name: ([\w-]+)", str(messages)).group(1)
        step[0] += 1
        if scenario.recovery and step[0] == 1:
            return ModelOutput.for_tool_call("mockllm", "analytics_describe", {"name": handle})
        if step[0] <= (2 if scenario.recovery else 1):
            return ModelOutput.for_tool_call(
                "mockllm",
                "analytics_query",
                {"query_yaml": bind_query(scenario.expected.query, handle)},
            )
        last = next(m for m in reversed(messages) if m.role == "tool")
        result = response_object(last.content)
        return ModelOutput.from_content(
            "mockllm",
            json.dumps({"outcome": "success", "rows": result["rows"], "explanation": "Measured"}),
        )

    with private_execution():
        async with get_model("mockllm/model", custom_outputs=generate, memoize=False) as model:
            result = await run_scenario(scenario, model, raise_infrastructure=True)
    assert result.status == "PASS", result
    if scenario.recovery:
        assert result.seeded_recovery
