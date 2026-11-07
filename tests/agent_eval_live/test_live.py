import pytest

pytestmark = pytest.mark.agent_eval_live


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario_id",
    ["aggregate-count", "negative-python", "recovery-unknown-field", "adversarial-command"],
)
async def test_real_model(live_config, scenario_id):
    from evals.agent_skill.endpoint_security import private_execution
    from evals.agent_skill.scenarios import load_scenarios
    from evals.agent_skill.task import run_scenario, runtime_model

    endpoint, model, key = live_config
    with private_execution():
        async with runtime_model(model, endpoint, key, 0, 600) as native_model:
            result = await run_scenario(load_scenarios(scenario_id=scenario_id)[0], native_model)
    assert result.status == "PASS", result.explanation


@pytest.mark.asyncio
async def test_skill_comparison(live_config):
    from evals.agent_skill.endpoint_security import private_execution
    from evals.agent_skill.scenarios import load_scenarios
    from evals.agent_skill.task import run_scenario, runtime_model

    endpoint, model, key = live_config
    scenario = load_scenarios(scenario_id="aggregate-count")[0]
    for mode in ["skill", "baseline"]:
        with private_execution():
            async with runtime_model(model, endpoint, key, 0, 600) as native_model:
                result = await run_scenario(scenario, native_model, mode=mode)
        assert result.status not in {"INFRASTRUCTURE_ERROR", "SKIPPED"}
