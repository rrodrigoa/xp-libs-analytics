from datetime import UTC, datetime, timedelta

import pytest
from conftest import query_text, run

BASE = datetime(2026, 11, 6, 10, tzinfo=UTC)
CAST = [{"field": "/t", "to": "datetime", "format": "rfc3339", "on_error": "reject"}]
TIME = {"field": "/t", "start": BASE.isoformat(), "end": (BASE + timedelta(minutes=10)).isoformat()}


@pytest.mark.parametrize(
    "window", [{"type": "tumbling", "size": "5m"}, {"type": "sliding", "size": "5m", "step": "1m"}]
)
def test_windows_independent_epoch_oracle(engine, window):
    times = [
        BASE - timedelta(microseconds=1),
        BASE,
        BASE + timedelta(seconds=299),
        BASE + timedelta(seconds=300),
        BASE + timedelta(seconds=599),
        BASE + timedelta(seconds=600),
    ]
    rows = [{"t": t.isoformat()} for t in reversed(times)]
    result = run(engine, rows, casts=CAST, time_range=TIME, window=window)
    expected = {}
    step = 60 if window["type"] == "sliding" else 300
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    for t in times:
        if BASE <= t < BASE + timedelta(minutes=10):
            seconds = (t - epoch).total_seconds()
            for offset in range(300 // step):
                start = int(seconds // step) * step - offset * step
                key = (epoch + timedelta(seconds=start)).isoformat().replace("+00:00", "Z")
                expected[key] = expected.get(key, 0) + 1
    assert {r["window_start"]: r["n"] for r in result["rows"]} == expected
    assert result["evidence"]["matched_rows"] == 4


def test_relative_range_half_open(engine):
    rows = [
        {"t": t} for t in ["2026-11-06T10:00:00Z", "2026-11-06T11:00:00Z", "2026-11-06T09:59:59Z"]
    ]
    result = run(engine, rows, casts=CAST, time_range={"field": "/t", "last_minutes": 60})
    assert result["rows"] == [{"n": 1}]
    assert result["evidence"]["resolved_time_range"] == {
        "start": "2026-11-06T10:00:00Z",
        "end": "2026-11-06T11:00:00Z",
    }


def test_offset_cast_and_empty_grid(engine):
    result = run(
        engine,
        [{"t": "2026-11-06T03:00:00-07:00"}],
        casts=CAST,
        time_range=TIME,
        window={"type": "tumbling", "size": "5m"},
        options={"include_empty_windows": True},
    )
    assert [r["n"] for r in result["rows"]] == [1, 0]


@pytest.mark.parametrize(
    "fmt,value",
    [("epoch_s", 1793959200), ("epoch_ms", 1793959200000), ("epoch_us", 1793959200000000)],
)
def test_epoch_units(engine, fmt, value):
    result = run(
        engine,
        [{"t": value}],
        casts=[{"field": "/t", "to": "datetime", "format": fmt, "on_error": "reject"}],
        time_range={"field": "/t", "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"},
    )
    assert result["status"] == "NO_DATA"


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"window": {"type": "tumbling", "size": "5m"}}, "QUERY_WINDOW_INVALID"),
        (
            {"window": {"type": "tumbling", "size": "2m"}, "time_range": TIME},
            "QUERY_WINDOW_INVALID",
        ),
        (
            {"window": {"type": "sliding", "size": "1m", "step": "5m"}, "time_range": TIME},
            "QUERY_WINDOW_INVALID",
        ),
        (
            {"window": {"type": "sliding", "size": "1h", "step": "1s"}, "time_range": TIME},
            "QUERY_WINDOW_INVALID",
        ),
        (
            {
                "time_range": {
                    "field": "/t",
                    "start": "2026-11-06T10:00:00",
                    "end": "2026-11-06T11:00:00Z",
                }
            },
            "QUERY_TIME_RANGE_INVALID",
        ),
        (
            {
                "time_range": {
                    "field": "/t",
                    "start": "2026-11-06T11:00:00Z",
                    "end": "2026-11-06T10:00:00Z",
                }
            },
            "QUERY_TIME_RANGE_INVALID",
        ),
        ({"time_range": {"field": "/t", "last_minutes": 0}}, "QUERY_TIME_RANGE_INVALID"),
    ],
)
def test_time_rejections(engine, changes, code):
    handle = engine.register_records("dataset_1", [{"t": BASE.isoformat()}])
    result = engine.query_yaml(query_text(handle, casts=CAST, **changes))
    assert result["error"]["code"] == code
