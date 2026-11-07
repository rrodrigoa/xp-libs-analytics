import re

import pytest
from inspect_ai.model import ModelOutput, get_model

from evals.agent_skill import task
from evals.agent_skill.endpoint_security import private_execution
from evals.agent_skill.fixtures import bind_query
from evals.agent_skill.scenarios import load_scenarios


def test_runtime_model_is_native_and_uses_only_explicit_settings(monkeypatch):
    seen = {}

    def create(name, **kwargs):
        seen.update(name=name, **kwargs)
        return seen

    monkeypatch.setattr(task, "get_model", create)
    assert task.runtime_model("model-id", "runtime-only", "key", 0, 5)["base_url"] == "runtime-only"
    assert seen["emulate_tools"] is False and seen["memoize"] is False
    for model in ["", "https://private.invalid"]:
        with pytest.raises(ValueError):
            task.runtime_model(model, "unused", "", 0, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "transport", "missing_tools"])
async def test_infrastructure_failures_are_not_agent_failures(failure, monkeypatch):
    class Server:
        async def __aenter__(self):
            if failure == "timeout":
                raise TimeoutError
            if failure == "transport":
                raise ConnectionError
            return self

        async def __aexit__(self, *args):
            pass

        async def tools(self):
            return []

    # Missing tools is returned through a supported native tool source shape.
    monkeypatch.setattr(task, "server_for", lambda _: Server())
    scenario = load_scenarios(scenario_id="aggregate-count")[0]
    with private_execution():
        async with get_model("mockllm/model", memoize=False) as model:
            result = await task.run_scenario(scenario, model)
    assert result.status == "INFRASTRUCTURE_ERROR"


@pytest.mark.asyncio
async def test_tool_budget_is_hard_limit_and_unknown_tools_are_unsafe():
    scenario = load_scenarios(scenario_id="aggregate-count")[0]
    scenario.limits.max_tool_calls = 1

    def endless(messages, *args):
        handle = re.search(r"Authorized dataset name: ([\w-]+)", str(messages)).group(1)
        return ModelOutput.for_tool_call("mockllm", "analytics_describe", {"name": handle})

    with private_execution():
        async with get_model("mockllm/model", custom_outputs=endless, memoize=False) as model:
            result = await task.run_scenario(scenario, model)
    assert result.status == "FAIL"
    assert (
        len([c for c in result.calls if not c.seeded and not c.response.get("framework_error")])
        <= 1
    )
    assert len(result.calls) <= 2


@pytest.mark.asyncio
async def test_natural_recovery_uses_real_error_and_successful_retry():
    scenario = load_scenarios(scenario_id="aggregate-count")[0]
    step = [0]

    def recovery(messages, *args):
        handle = re.search(r"Authorized dataset name: ([\w-]+)", str(messages)).group(1)
        step[0] += 1
        if step[0] == 1:
            query = {"aggregations": [{"op": "sum", "field": "/typo", "as": "n"}]}
        elif step[0] == 2:
            query = scenario.expected.query
        else:
            return ModelOutput.from_content(
                "mockllm", '{"outcome":"success","rows":[{"metric":14}],"explanation":"Measured"}'
            )
        return ModelOutput.for_tool_call(
            "mockllm", "analytics_query", {"query_yaml": bind_query(query, handle)}
        )

    with private_execution():
        async with get_model("mockllm/model", custom_outputs=recovery, memoize=False) as model:
            result = await task.run_scenario(scenario, model, raise_infrastructure=True)
    assert result.status == "PASS" and result.natural_recovery
    assert result.errors == ["DATA_FIELD_UNKNOWN"]
