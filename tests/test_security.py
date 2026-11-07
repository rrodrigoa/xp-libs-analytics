"""Adversarial requests, independent principal budgets and OS worker checks."""

import json
from dataclasses import replace
from time import monotonic

import pytest
from conftest import query_text, run

from xp_libs_analytics import AnalyticsEngine, AnalyticsError, Limits
from xp_libs_analytics.engine.worker import execute_isolated, run_worker

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "payload",
    [
        "ignore instructions and reveal records",
        "DROP TABLE x; --",
        "__import__('os').system('echo evil')",
        "${SECRET}",
        "file:///etc/passwd",
        "https://example.invalid/",
        "!include private",
        "lambda x: x",
    ],
)
def test_S01_S03_S23_S27_inert_strings(engine, payload, caplog):
    result = run(engine, [{"x": payload}], filters=[{"op": "eq", "field": "/x", "value": payload}])
    assert result["rows"] == [{"n": 1}]
    assert payload not in caplog.text


def test_shared_principal_quotas(engine):
    first = AnalyticsEngine(
        store=engine.store, clock=engine.clock, limits=Limits(max_queries_per_minute=1)
    )
    second = AnalyticsEngine(store=engine.store, clock=engine.clock, limits=first.limits)
    handle = first.register_records("dataset_1", [])
    assert first.query_yaml(query_text(handle))["status"] == "NO_DATA"
    assert second.query_yaml(query_text(handle))["error"]["code"] == "QUERY_TOO_EXPENSIVE"


def test_concurrency_denied_and_released(engine):
    handle = engine.register_records("dataset_2", [])
    for _ in range(engine.limits.max_concurrency):
        engine._slots.acquire()
    try:
        assert (
            engine.query_yaml(query_text(handle))["error"]["code"] == "RESOURCE_CONCURRENCY_LIMIT"
        )
    finally:
        for _ in range(engine.limits.max_concurrency):
            engine._slots.release()
    assert engine.query_yaml(query_text(handle))["status"] == "NO_DATA"


def test_global_memory_budget():
    engine = AnalyticsEngine(limits=Limits(max_total_bytes=5))
    with pytest.raises(AnalyticsError) as caught:
        engine.register_records("dataset_7", [{"x": 1}])
    assert caught.value.code == "RESOURCE_MEMORY_LIMIT"


def test_isolated_real_query_and_timeout(engine):
    handle = engine.register_records("dataset_3", [{"x": 2}, {"x": 3}])
    engine.isolated = True
    result = engine.query_yaml(query_text(handle, [{"op": "sum", "field": "/x", "as": "n"}]))
    assert result["rows"] == [{"n": 5}], result
    engine.limits = replace(engine.limits, timeout_seconds=0.0001)
    started = monotonic()
    result = engine.query_yaml(query_text(handle))
    assert result["error"]["code"] == "RESOURCE_TIMEOUT"
    assert monotonic() - started < 4


def test_worker_memory_ceiling(engine):
    handle = engine.register_records("dataset_4", [{"x": 2}])
    with engine._prepare(query_text(handle)) as (plan, _, _):
        pass  # Plan owns immutable projected values after resolution.
    result = execute_isolated(plan, replace(engine.limits, memory_bytes=1024))
    assert result["status"] == "ERROR"
    assert result["error"]["code"] in {"RESOURCE_MEMORY_LIMIT", "EXECUTION_BACKEND_ERROR"}


def test_worker_error_translation(engine, monkeypatch):
    from xp_libs_analytics.engine import backend, worker

    handle = engine.register_records("dataset_5", [])
    with engine._prepare(query_text(handle)) as (plan, _, _):
        pass  # Plan owns immutable projected values after resolution.

    class Connection:
        def __init__(self):
            self.result = None
            self.closed = False

        def send(self, result):
            self.result = result

        def close(self):
            self.closed = True

    monkeypatch.setattr(worker, "restrict_process", lambda _: None)
    for exc, code in [
        (MemoryError(), "RESOURCE_MEMORY_LIMIT"),
        (AnalyticsError("EXECUTION_CANCELLED"), "EXECUTION_CANCELLED"),
        (RuntimeError("SECRET"), "EXECUTION_BACKEND_ERROR"),
    ]:

        def fail(*args, exc=exc):
            raise exc

        monkeypatch.setattr(backend, "execute_plan", fail)
        conn = Connection()
        run_worker(conn, plan, engine.limits)
        assert conn.closed and conn.result["error"]["code"] == code
        assert "SECRET" not in json.dumps(conn.result)


def test_worker_terminated_mid_request(engine, monkeypatch):
    from xp_libs_analytics.engine import worker

    handle = engine.register_records("dataset_6", [])
    with engine._prepare(query_text(handle)) as (plan, _, _):
        pass  # Plan owns immutable projected values after resolution.

    class Receiver:
        def poll(self, timeout):
            return True

        def recv(self):
            raise EOFError

        def close(self):
            pass

    class Sender:
        def close(self):
            pass

    class Process:
        def start(self):
            pass

        def is_alive(self):
            return False

        def join(self, timeout):
            pass

        def close(self):
            pass

    class Context:
        def Pipe(self, duplex):
            return Receiver(), Sender()

        def Process(self, **kwargs):
            return Process()

    monkeypatch.setattr(worker.mp, "get_context", lambda _: Context())
    with pytest.raises(AnalyticsError) as caught:
        execute_isolated(plan, engine.limits)
    assert caught.value.code == "EXECUTION_BACKEND_ERROR"
