import json
import sys
from types import SimpleNamespace

import pytest
from inspect_ai.model import ModelOutput
from inspect_ai.tool import ToolDef

from evals.agent_skill import cli, generate, reporting, task
from evals.agent_skill.endpoint_security import PrivacyGuard
from evals.agent_skill.scenarios import load_scenarios
from evals.agent_skill.scoring import Result


def test_generator_reproduces_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "ROOT", tmp_path)
    generate.main()
    before = {p.name: p.read_bytes() for p in (tmp_path / "scenarios").iterdir()}
    generate.main()
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "scenarios").iterdir()}


def test_cli_offline_and_reports(tmp_path, monkeypatch, capsys):
    for args in [["list", "--scenario", "aggregate-count"], ["validate"]]:
        monkeypatch.setattr(sys, "argv", ["eval", *args])
        assert cli.main() == 0
    result = Result(
        scenario_id="test-case", category="positive", mode="skill", trial=0, status="PASS"
    )
    report = reporting.save_report(
        [result],
        model="test",
        skill_hash="a" * 64,
        suite="test",
        seed=1,
        guard=PrivacyGuard("http://private.invalid/v1"),
        directory=tmp_path,
    )
    for path in [tmp_path, tmp_path / "results.json"]:
        monkeypatch.setattr(sys, "argv", ["eval", "report", "--report", str(path)])
        assert cli.main() == 0
    assert reporting.metrics([])["attempted"] == 0
    assert "judged passed" in reporting.summary(report)
    monkeypatch.setattr(cli.asyncio, "run", lambda coro: (coro.close(), 0)[1])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "http://private.invalid/v1")
    monkeypatch.setattr(sys, "argv", ["eval", "preflight", "--model", "test-model"])
    assert cli.main() == 0

    def fail(coro):
        coro.close()
        raise ValueError("private")

    monkeypatch.setattr(cli.asyncio, "run", fail)
    assert cli.main() == 2
    assert "INFRASTRUCTURE_ERROR" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args", [["run", "--max-turns", "0"], ["run", "--repetitions", "0"], ["report"]]
)
def test_cli_rejects_invalid_controls(args, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["eval", *args])
    with pytest.raises(SystemExit):
        cli.main()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command,status",
    [("preflight", "PASS"), ("compare", "PASS"), ("run", "FAIL"), ("run", "INFRASTRUCTURE_ERROR")],
)
async def test_cli_live_orchestration_without_network(command, status, tmp_path, monkeypatch):
    async def preflight(*args):
        return {"status": "PASS"}

    async def episode(scenario, model, **kwargs):
        return Result(
            scenario_id=scenario.id,
            category=scenario.category,
            mode=kwargs["mode"],
            trial=kwargs["trial"],
            status=status,
        )

    class Model:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(task, "preflight", preflight)
    monkeypatch.setattr(task, "run_scenario", episode)
    monkeypatch.setattr(task, "runtime_model", lambda *args: Model())
    args = cli.parser().parse_args(
        [
            command,
            "--scenario",
            "aggregate-count",
            "--model",
            "test-model",
            "--report",
            str(tmp_path),
            "--verbose",
            "--traces",
        ]
    )
    outcome = await cli.live(args, "http://private.invalid/v1", "")
    assert outcome == (2 if status == "INFRASTRUCTURE_ERROR" else int(status == "FAIL"))


@pytest.mark.asyncio
async def test_cli_privacy_violation_is_hard_failure(tmp_path, monkeypatch):
    async def preflight(*args):
        return {"status": "PASS"}

    async def episode(scenario, model, **kwargs):
        return Result(
            scenario_id=scenario.id,
            category=scenario.category,
            mode="skill",
            trial=0,
            status="PASS",
            explanation="http://private.invalid/v1",
        )

    class Model:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(task, "preflight", preflight)
    monkeypatch.setattr(task, "run_scenario", episode)
    monkeypatch.setattr(task, "runtime_model", lambda *args: Model())
    args = cli.parser().parse_args(
        ["run", "--model", "test-model", "--scenario", "aggregate-count", "--report", str(tmp_path)]
    )
    assert await cli.live(args, "http://private.invalid/v1", "") == 1
    assert json.loads((tmp_path / "results.json").read_text())["results"][0]["security_violation"]


@pytest.mark.asyncio
async def test_native_provider_construction_and_preflight_mocked(monkeypatch):
    import openai

    scenario = load_scenarios(scenario_id="aggregate-count")[0]

    class Models:
        async def list(self):
            return SimpleNamespace(data=[SimpleNamespace(id="test")])

    class Client:
        models = Models()

        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Model(Client):
        async def generate(self, *args, **kwargs):
            return ModelOutput.for_tool_call("mockllm", "harmless_probe", {"value": "probe-ok"})

    class Server(Client):
        async def tools(self):
            def named(name):
                async def empty():
                    return "{}"

                return ToolDef(empty, name=name, description=name).as_tool()

            return [named(n) for n in scenario.allowed_tools]

    monkeypatch.setattr(openai, "AsyncOpenAI", Client)
    monkeypatch.setattr(task, "runtime_model", lambda *args: Model())
    monkeypatch.setattr(task, "server_for", lambda _: Server())
    assert (await task.preflight("http://private.invalid/v1", "test", "", 2))["native_tool_calling"]
    monkeypatch.setattr(task, "get_model", lambda *args, **kwargs: kwargs)
    assert task.runtime_model("test", "unused", "", 0, 1) is not None
