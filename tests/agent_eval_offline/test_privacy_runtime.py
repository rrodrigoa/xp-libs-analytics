import pytest
from inspect_ai.model import ModelOutput, get_model

from evals.agent_skill.endpoint_security import private_execution
from evals.agent_skill.scenarios import load_scenarios
from evals.agent_skill.task import run_scenario


@pytest.mark.asyncio
async def test_memory_only_inspect_logging_has_no_sqlite_spool(monkeypatch):
    import fsspec
    import inspect_ai._eval.task.log as log_module

    def forbidden(*args, **kwargs):
        raise AssertionError("Raw disk buffering must stay disabled")

    monkeypatch.setattr(log_module, "SampleBufferDatabase", forbidden)
    scenario = load_scenarios(scenario_id="aggregate-count")[0]

    def complete(messages, *args):
        return ModelOutput.from_content("mockllm", '{"outcome":"rejection","explanation":"test"}')

    with private_execution():
        async with get_model("mockllm/model", custom_outputs=complete, memoize=False) as model:
            result = await run_scenario(scenario, model, mode="baseline", raise_infrastructure=True)
    assert result.status == "FAIL"
    assert not any("xp-agent-eval" in name for name in fsspec.filesystem("memory").find("/"))
