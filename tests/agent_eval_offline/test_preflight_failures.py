from types import SimpleNamespace

import pytest
from inspect_ai.model import ModelOutput
from inspect_ai.tool import ToolDef

from evals.agent_skill import task
from evals.agent_skill.scenarios import load_scenarios


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "listing_unsupported",
        "listing_denied",
        "missing_model",
        "no_native_tools",
        "bad_probe_args",
        "missing_mcp",
    ],
)
async def test_preflight_failure_classification(failure, monkeypatch):
    import openai

    class StatusError(Exception):
        def __init__(self, status):
            self.status_code = status

    class Models:
        async def list(self):
            if failure == "listing_unsupported":
                raise StatusError(404)
            if failure == "listing_denied":
                raise StatusError(403)
            return SimpleNamespace(
                data=[SimpleNamespace(id="other" if failure == "missing_model" else "test")]
            )

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
            if failure == "no_native_tools":
                return ModelOutput.from_content("mockllm", "No tool calling")
            return ModelOutput.for_tool_call(
                "mockllm",
                "harmless_probe",
                {"value": "wrong" if failure == "bad_probe_args" else "probe-ok"},
            )

    class Server(Client):
        async def tools(self):
            if failure == "missing_mcp":
                return []

            def named(name):
                async def empty():
                    return "{}"

                return ToolDef(empty, name=name, description=name).as_tool()

            return [
                named(n) for n in load_scenarios(scenario_id="aggregate-count")[0].allowed_tools
            ]

    monkeypatch.setattr(openai, "AsyncOpenAI", Client)
    monkeypatch.setattr(openai, "APIStatusError", StatusError)
    monkeypatch.setattr(task, "runtime_model", lambda *args: Model())
    monkeypatch.setattr(task, "server_for", lambda _: Server())
    if failure == "listing_unsupported":
        result = await task.preflight("http://private.invalid/v1", "test", "", 1)
        assert result["model_listing_supported"] is False
    else:
        with pytest.raises((ValueError, StatusError)):
            await task.preflight("http://private.invalid/v1", "test", "", 1)
