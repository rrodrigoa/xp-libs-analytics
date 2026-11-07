import json
from datetime import UTC, datetime

import pytest
import yaml

from xp_libs_analytics import AnalyticsEngine, Limits


@pytest.fixture
def engine():
    return AnalyticsEngine(
        clock=lambda: datetime(2026, 11, 6, 11, tzinfo=UTC),
        limits=Limits(max_queries_per_minute=10_000),
    )


def query_text(handle, aggregations=None, **kwargs):
    document = {
        "version": "analytics.query/v1",
        "dataset": {"name": handle.name},
        "aggregations": aggregations or [{"op": "count", "as": "n"}],
        **kwargs,
    }
    return yaml.safe_dump(json.loads(json.dumps(document)), sort_keys=False)


def run(engine, rows, aggregations=None, **kwargs):
    handle = engine.register_records("dataset_1", rows)
    result = engine.query_yaml(query_text(handle, aggregations, **kwargs))
    engine.unregister_dataset(handle.name)
    assert result["status"] != "ERROR", result
    return result
