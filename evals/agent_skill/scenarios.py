"""Strict scenario contracts and deterministic, semantics-preserving variations."""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from xp_libs_analytics.parser import parse_yaml

ROOT = Path(__file__).resolve().parent
TOOLS = frozenset(
    {
        "analytics_capabilities",
        "analytics_list_datasets",
        "analytics_describe",
        "analytics_validate_query",
        "analytics_explain_query",
        "analytics_query",
        "analytics_error_info",
        "analytics_unregister_dataset",
    }
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Budgets(Strict):
    max_turns: int = Field(default=12, ge=1, le=40)
    max_tool_calls: int = Field(default=12, ge=1, le=40)
    timeout: int = Field(default=300, ge=1, le=1800)


class Expected(Strict):
    outcome: Literal["success", "rejection", "clarification", "no_data"]
    query: dict[str, Any] | None = None
    error_codes: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=lambda: ["analytics_query"])
    explanation_terms: list[str] = Field(default_factory=list)
    unordered: bool = True


class Recovery(Strict):
    tool: str = "analytics_query"
    arguments: dict[str, Any] | None = None
    query: dict[str, Any] | None = None
    raw_yaml: str | None = None
    error_code: str
    discover_required: bool = True


class Scenario(Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    category: Literal[
        "positive", "negative", "temporal", "recovery", "adversarial", "skill_comparison"
    ]
    description: str
    fixture: str
    user_prompt: str
    expected: Expected
    allowed_tools: list[str] = Field(default_factory=lambda: sorted(TOOLS))
    limits: Budgets = Field(default_factory=Budgets)
    recovery: Recovery | None = None
    policy: dict[str, int] = Field(default_factory=dict)
    visible_fields: list[str] | None = None
    field_renames: dict[str, str] = Field(default_factory=dict)
    variation_seed: int = 0
    variation_trial: int = 0


def load_scenarios(suite: str = "all", scenario_id: str | None = None) -> list[Scenario]:
    scenarios = []
    for path in sorted((ROOT / "scenarios").glob("*.yaml")):
        document = parse_yaml(
            path.read_text(encoding="utf-8"),
            __import__("xp_libs_analytics").Limits(
                max_query_bytes=256_000,
                max_yaml_nodes=30_000,
                max_scalar_chars=10_000,
                max_collection_items=4096,
            ),
        )
        scenarios.extend(Scenario.model_validate(item) for item in document["scenarios"])
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate scenario identifiers")
    for s in scenarios:
        if not set(s.allowed_tools) <= TOOLS or not set(s.expected.required_tools) <= set(
            s.allowed_tools
        ):
            raise ValueError("Invalid tool allowlist")
        if not (ROOT / "datasets" / s.fixture).is_file() or Path(s.fixture).name != s.fixture:
            raise ValueError("Unknown fixture")
    selected = [
        s
        for s in scenarios
        if (suite == "all" or s.category == suite) and (scenario_id is None or s.id == scenario_id)
    ]
    if not selected:
        raise ValueError("No scenarios matched")
    return selected


def vary(scenario: Scenario, seed: int, trial: int) -> Scenario:
    rng = random.Random(f"{seed}:{scenario.id}:{trial}")  # noqa: S311 -- reproducible fixture wording
    lead = rng.choice(
        [
            "Please analyze the supplied snapshot. ",
            "Using the authorized data, ",
            "For this investigation, ",
        ]
    )
    data = scenario.model_dump()
    data.update(variation_seed=seed, variation_trial=trial)
    prompt = scenario.user_prompt
    if trial > 0 and scenario.category in {"positive", "temporal", "skill_comparison"}:
        mapping = {
            key: f"{label}_{trial}"
            for key, label in {
                "value": "measurement",
                "region": "area",
                "amount": "quantity",
                "ts": "recorded",
                "service": "component",
                "entity": "identifier",
            }.items()
        }

        def rewrite(value):
            if isinstance(value, dict):
                return {
                    k: (
                        "/" + mapping.get(v[1:], v[1:])
                        if k == "field" and isinstance(v, str) and v.startswith("/")
                        else rewrite(v)
                    )
                    for k, v in value.items()
                }
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            return value

        data["expected"] = rewrite(data["expected"])
        data["field_renames"] = mapping
        for old, new in mapping.items():
            prompt = re.sub(r"\b" + re.escape(old) + r"\b", new, prompt)
    data["user_prompt"] = lead + prompt
    return Scenario.model_validate(data)
