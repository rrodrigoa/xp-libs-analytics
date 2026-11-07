"""Inspect native ReAct + native stdio MCP; raw execution stays in memory."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from time import monotonic
from typing import Any

from inspect_ai import Task, eval_async
from inspect_ai.agent import AgentPrompt, react, run
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageUser, GenerateConfig, ModelName, get_model
from inspect_ai.scorer import Target
from inspect_ai.solver import TaskState, solver
from inspect_ai.tool import ToolDef, ToolError, mcp_server_stdio, mcp_tools
from inspect_ai.util import LimitExceededError, turn_limit

from .fixtures import oracle
from .recovery import execute_call, response_object, seed_failure
from .scenarios import ROOT, Scenario
from .scoring import Call, Result, analytics_scorer
from .skill_loader import REPO, load_skill


def server_for(scenario: Scenario):
    safe_env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "PYTHONPATH",
            "VIRTUAL_ENV",
            "PYTHONUTF8",
        }
    }
    safe_env["PYTHONUTF8"] = "1"
    return mcp_server_stdio(
        name="xp_analytics",
        command=sys.executable,
        args=[
            "-m",
            "evals.agent_skill.server",
            "--scenario",
            scenario.id,
            "--seed",
            str(scenario.variation_seed),
            "--trial",
            str(scenario.variation_trial),
        ],
        cwd=REPO,
        env=safe_env,
    )


def instrument(tool: Any, calls: list[Call], maximum: int, budget: dict[str, bool] | None = None):
    definition = ToolDef(tool)

    async def invoke(**arguments: Any):
        if len([c for c in calls if not c.seeded]) >= maximum:
            if budget is not None:
                budget["exhausted"] = True
            raise ToolError("MCP call budget exhausted; no request was executed")
        try:
            result = await tool(**arguments)
            calls.append(
                Call(tool=definition.name, arguments=arguments, response=response_object(result))
            )
            return result
        except ToolError as exc:
            calls.append(
                Call(tool=definition.name, arguments=arguments, response=response_object(str(exc)))
            )
            raise

    return ToolDef(
        invoke,
        name=definition.name,
        description=definition.description,
        parameters=definition.parameters,
        parallel=False,
        max_output=0,
    ).as_tool()


def make_task(
    scenario: Scenario,
    prompt: str,
    tools: list[Any],
    model: Any,
    budget: dict[str, bool] | None = None,
) -> tuple[Task, Any]:
    async def continuing(state):
        return bool(state.output.message.tool_calls) and not (budget or {}).get("exhausted", False)

    agent = react(
        prompt=AgentPrompt(
            instructions=prompt, assistant_prompt=None, handoff_prompt=None, submit_prompt=None
        ),
        tools=tools,
        model=model,
        submit=False,
        on_continue=continuing,
    )
    dataset = MemoryDataset(
        [
            Sample(
                id=scenario.id,
                input=scenario.user_prompt,
                target=json.dumps(oracle(scenario)),
                metadata={"scenario_id": scenario.id},
            )
        ]
    )
    return Task(dataset=dataset, solver=agent, scorer=analytics_scorer(scenario)), agent


async def run_scenario(
    scenario: Scenario,
    model: Any,
    *,
    mode: str = "skill",
    trial: int = 0,
    trace_out: list[Any] | None = None,
    raise_infrastructure: bool = False,
) -> Result:
    """Native Inspect task with memory-only JSON logs and disk buffering disabled."""
    from uuid import uuid4

    import fsspec

    captured: list[Result] = []

    @solver
    def episode():
        async def execute(state, generate):
            captured.append(
                await _run_sample(
                    scenario,
                    model,
                    mode=mode,
                    trial=trial,
                    trace_out=trace_out,
                    raise_infrastructure=raise_infrastructure,
                    active_state=state,
                )
            )
            return state

        return execute

    task = Task(
        name="xp_agent_skill",
        dataset=MemoryDataset([Sample(id=scenario.id, input=scenario.user_prompt)]),
        solver=episode(),
        scorer=None,
    )
    location = "memory://xp-agent-eval/" + uuid4().hex
    try:
        logs = await eval_async(
            task,
            model=model,
            log_dir=location,
            log_format="json",
            log_realtime=False,
            log_model_api=False,
            log_samples=True,
            log_images=False,
            log_buffer=1,
            checkpoint=False,
            ctl_server=False,
            acp_server=False,
            max_samples=1,
            max_tasks=1,
            retry_on_error=0,
            fail_on_error=False,
            log_level="CRITICAL",
            log_level_transcript="CRITICAL",
        )
        if captured:
            return captured[0]
        if raise_infrastructure and logs[0].error:
            raise RuntimeError(logs[0].error.message)
        return Result(
            scenario_id=scenario.id,
            category=scenario.category,
            mode=mode,
            trial=trial,
            status="INFRASTRUCTURE_ERROR",
            explanation="Inspect sample did not complete",
        )
    finally:
        memory = fsspec.filesystem("memory")
        if memory.exists(location):
            memory.rm(location, recursive=True)


async def _run_sample(
    scenario: Scenario,
    model: Any,
    *,
    mode: str,
    trial: int,
    trace_out: list[Any] | None,
    raise_infrastructure: bool,
    active_state: Any,
) -> Result:
    started = monotonic()
    calls: list[Call] = []
    budget: dict[str, bool] = {}
    try:
        async with asyncio.timeout(scenario.limits.timeout):
            connection = server_for(scenario)
            async with connection:
                native = await mcp_tools(connection, tools=scenario.allowed_tools).tools()
                native_by_name = {ToolDef(t).name: t for t in native}
                if not set(scenario.allowed_tools) <= native_by_name.keys():
                    raise RuntimeError("MCP discovery incomplete")
                context = await execute_call(native_by_name["analytics_capabilities"], {})
                handle = context["evaluation_dataset"]["name"]
                prompt = (ROOT / "prompts/agent_system.md").read_text()
                if mode == "skill":
                    prompt += "\nProduct skill and references:\n" + load_skill()[0]
                task, agent = make_task(
                    scenario,
                    prompt,
                    [instrument(t, calls, scenario.limits.max_tool_calls, budget) for t in native],
                    model,
                    budget,
                )
                messages = [
                    ChatMessageUser(
                        content=(
                            f"Authorized dataset name: {handle}. "
                            f"Evaluation UTC clock: {context['evaluation_dataset']['clock']}.\n"
                            f"{task.dataset[0].input}"
                        )
                    )
                ]
                seed_messages, seeded = await seed_failure(scenario, native_by_name, handle)
                messages.extend(seed_messages)
                if seeded:
                    calls.append(Call.model_validate(seeded))
                state, limit = await run(
                    agent, messages, limits=[turn_limit(scenario.limits.max_turns)]
                )
                active_state.messages, active_state.output = state.messages, state.output
                observed = []
                responses = {
                    getattr(m, "tool_call_id", None): m for m in state.messages if m.role == "tool"
                }
                for message in state.messages:
                    for call in getattr(message, "tool_calls", None) or []:
                        reply = responses.get(call.id)
                        observed.append(
                            Call(
                                tool=call.function,
                                arguments=call.arguments,
                                response=response_object(
                                    reply.error.message if reply.error else reply.content
                                )
                                if reply is not None
                                else {"framework_error": "Missing tool response"},
                                seeded=call.id == "seeded_failure",
                            )
                        )
                calls[:] = observed
                task_state = TaskState(
                    model=ModelName(model),
                    sample_id=scenario.id,
                    epoch=1,
                    input=messages,
                    messages=state.messages,
                    output=state.output,
                    metadata={"calls": calls},
                )
                score = await analytics_scorer(scenario)(task_state, Target(task.dataset[0].target))
                result = Result.model_validate(score.metadata)
                result.mode, result.trial = mode, trial
                if limit is not None or budget.get("exhausted"):
                    result.status = "FAIL"
                    result.explanation = "Agent execution budget exhausted"
                if trace_out is not None:
                    trace_out.extend(m.model_dump(mode="json") for m in state.messages)
    except TimeoutError:
        result = Result(
            scenario_id=scenario.id,
            category=scenario.category,
            mode=mode,
            trial=trial,
            status="INFRASTRUCTURE_ERROR",
            calls=calls,
            explanation="Scenario timed out; no correctness judgment",
        )
    except LimitExceededError:
        result = Result(
            scenario_id=scenario.id,
            category=scenario.category,
            mode=mode,
            trial=trial,
            status="FAIL",
            calls=calls,
            explanation="Agent MCP call budget exhausted",
        )
    except Exception:
        if raise_infrastructure:
            raise
        result = Result(
            scenario_id=scenario.id,
            category=scenario.category,
            mode=mode,
            trial=trial,
            status="INFRASTRUCTURE_ERROR",
            calls=calls,
            explanation=(
                "Model provider, MCP transport, or harness failure; no correctness judgment"
            ),
        )
    result.duration = monotonic() - started
    return result


def runtime_model(model: str, endpoint: str, credential: str, temperature: float, timeout: int):
    if "://" in model or not model.strip():
        raise ValueError("Invalid model identifier")
    return get_model(
        f"openai-api/xp_eval/{model}",
        base_url=endpoint,
        api_key=credential or "not-required",
        memoize=False,
        emulate_tools=False,
        stream=False,
        config=GenerateConfig(
            temperature=temperature,
            max_tokens=4096,
            max_retries=0,
            timeout=timeout,
            parallel_tool_calls=False,
        ),
    )


async def preflight(endpoint: str, model: str, credential: str, timeout: int) -> dict[str, Any]:
    from inspect_ai.tool import tool
    from openai import APIStatusError, AsyncOpenAI

    @tool
    def harmless_probe():
        async def execute(value: str) -> str:
            """Return the supplied harmless probe text unchanged.

            Args:
                value: Harmless text to echo.
            """
            return value

        return execute

    # No fallback or emulated tools. All failures are translated by the CLI, never printed raw.
    async with AsyncOpenAI(
        base_url=endpoint, api_key=credential or "not-required", timeout=timeout, max_retries=0
    ) as client:
        listed = True
        try:
            models = await client.models.list()
            if model not in {m.id for m in models.data}:
                raise ValueError("Requested model was not listed")
        except APIStatusError as exc:
            if exc.status_code not in {404, 405, 501}:
                raise
            listed = False
    async with runtime_model(model, endpoint, credential, 0, timeout) as native_model:
        probe = harmless_probe()
        response = await native_model.generate(
            "Call harmless_probe once with value 'probe-ok'.",
            tools=[probe],
            tool_choice="any",
            cache=False,
        )
        if (
            not response.message.tool_calls
            or response.message.tool_calls[0].function != "harmless_probe"
        ):
            raise ValueError("Native tool calling is required; emulation is disabled")
        args = response.message.tool_calls[0].arguments
        if await probe(**args) != "probe-ok":
            raise ValueError("Native tool-call probe arguments were invalid")
    from .scenarios import load_scenarios

    scenario = load_scenarios(scenario_id="aggregate-count")[0]
    async with server_for(scenario) as server:
        names = {ToolDef(t).name for t in await server.tools()}
        if not set(scenario.allowed_tools) <= names:
            raise ValueError("MCP tools are missing")
    _, skill_hash = load_skill()
    return {
        "status": "PASS",
        "model_listing_supported": listed,
        "native_tool_calling": True,
        "mcp_tools": sorted(names),
        "skill_hash": skill_hash,
    }
