"""Synthetic data admission and deterministic SDK-derived oracles."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import yaml

from xp_libs_analytics import AnalyticsEngine, Limits, Principal

from .scenarios import ROOT, Scenario

CLOCK = datetime(2026, 11, 6, 11, tzinfo=UTC)


def records(scenario: Scenario) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in (ROOT / "datasets" / scenario.fixture).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [{scenario.field_renames.get(k, k): v for k, v in row.items()} for row in rows]


def bind_query(query: dict[str, Any], name: str) -> str:
    document = {"version": "analytics.query/v1", "dataset": {"name": name}, **query}
    return yaml.safe_dump(json.loads(json.dumps(document)), sort_keys=False)


def make_engine(scenario: Scenario, *, isolated: bool = False) -> tuple[AnalyticsEngine, str]:
    fields = frozenset(scenario.visible_fields) if scenario.visible_fields is not None else None
    allowed = {"max_result_bytes", "max_groups", "max_windows", "max_distinct"}
    if not set(scenario.policy) <= allowed:
        raise ValueError("Unsupported evaluation policy override")
    engine = AnalyticsEngine(
        limits=replace(Limits(max_queries_per_minute=1000), **scenario.policy),
        principal=Principal(id="evaluation", fields=fields),
        clock=lambda: CLOCK,
        isolated=isolated,
    )
    handle = engine.register_records("observations", records(scenario))
    return engine, handle.name


def oracle(scenario: Scenario) -> dict[str, Any] | None:
    if scenario.expected.query is None:
        return None
    engine, handle = make_engine(scenario)
    return engine.query_yaml(bind_query(scenario.expected.query, handle))
