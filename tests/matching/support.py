import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from xp_libs_analytics import AnalyticsEngine, Limits

CLOCK = datetime(2026, 11, 6, 11, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/matching_events.jsonl"


def records():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


def make(rows=None, *, principal=None, **policy):
    engine = AnalyticsEngine(
        limits=Limits(force_matching_isolation=False, max_queries_per_minute=10000, **policy),
        principal=principal,
        clock=lambda: CLOCK,
    )
    engine.register_records("matching", records() if rows is None else rows)
    return engine


def text(filters=None, aggregations=None, **kwargs):
    document = {
        "version": "analytics.query/v1",
        "dataset": {"name": "matching"},
        "filters": filters or [],
        "aggregations": aggregations or [{"op": "count", "as": "n"}],
        **kwargs,
    }
    return yaml.safe_dump(json.loads(json.dumps(document)), sort_keys=False, allow_unicode=True)


def execute(engine, filters=None, aggregations=None, **kwargs):
    return engine.query_yaml(text(filters, aggregations, **kwargs))


def leaf(op, value="Peter", **kwargs):
    return {"field": "/actor/name", "op": op, "value": value, **kwargs}


def fuzzy(value="Peter", **kwargs):
    return leaf("fuzzy", value, algorithm="ratio", min_score=80, **kwargs)
