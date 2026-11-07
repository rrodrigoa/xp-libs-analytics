"""Seed continuations with actual MCP failures, never invented catalog errors."""

from __future__ import annotations

import json
from typing import Any

from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ChatMessageUser
from inspect_ai.tool import ToolCall, ToolError

from .fixtures import bind_query
from .scenarios import Scenario


def response_object(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        text = "\n".join(getattr(v, "text", str(v)) for v in result)
    else:
        text = str(result)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {"framework_error": text}
    except ValueError:
        return {"framework_error": text or "Tool framework returned no content"}


async def execute_call(tool: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return response_object(await tool(**arguments))
    except ToolError as exc:
        # Inspect's native MCP adapter maps isError to ToolError with real JSON content.
        return response_object(str(exc))


async def seed_failure(
    scenario: Scenario, tools: dict[str, Any], handle: str
) -> tuple[list[Any], dict[str, Any]]:
    recovery = scenario.recovery
    if recovery is None:
        return [], {}
    args = recovery.arguments
    if args is None:
        text = (
            recovery.raw_yaml
            if recovery.raw_yaml is not None
            else bind_query(recovery.query or {}, handle)
        )
        args = {"query_yaml": text}
    args = {k: v.replace("{handle}", handle) if isinstance(v, str) else v for k, v in args.items()}
    response = await execute_call(tools[recovery.tool], args)
    if response.get("error", {}).get("code") != recovery.error_code:
        raise ValueError("Seeded MCP failure did not match the scenario contract")
    messages = [
        ChatMessageAssistant(
            content="I attempted this analytics call.",
            tool_calls=[ToolCall(id="seeded_failure", function=recovery.tool, arguments=args)],
        ),
        ChatMessageTool(
            content=json.dumps(response), tool_call_id="seeded_failure", function=recovery.tool
        ),
        ChatMessageUser(
            content=(
                "That call failed. Use the real error guidance to address the "
                "original request. Do not bypass access controls."
            )
        ),
    ]
    return messages, {
        "tool": recovery.tool,
        "arguments": args,
        "response": response,
        "seeded": True,
    }
