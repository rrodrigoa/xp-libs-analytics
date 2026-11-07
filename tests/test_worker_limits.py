from types import SimpleNamespace

import pytest

from xp_libs_analytics import AnalyticsError, Limits
from xp_libs_analytics.engine.worker import restrict_process


@pytest.mark.parametrize("failure", ["create", "set", "assign", None])
def test_windows_job_api_enforces_memory_cpu_and_fails_closed(monkeypatch, failure):
    import ctypes

    from xp_libs_analytics.engine import worker

    observed = {}

    class Fn:
        def __init__(self, result):
            self.result = result

        def __call__(self, *args):
            return self.result

    class SetInfo(Fn):
        def __call__(self, handle, kind, pointer, size):
            info = pointer._obj
            observed.update(
                memory=info.process_memory, flags=info.basic.flags, cpu=info.basic.process_time
            )
            return self.result

    kernel = SimpleNamespace(
        CreateJobObjectW=Fn(0 if failure == "create" else 123),
        SetInformationJobObject=SetInfo(0 if failure == "set" else 1),
        AssignProcessToJobObject=Fn(0 if failure == "assign" else 1),
        GetCurrentProcess=Fn(456),
    )
    with monkeypatch.context() as m:
        m.setattr(worker.sys, "platform", "win32")
        m.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
        if failure:
            with pytest.raises(AnalyticsError) as caught:
                restrict_process(Limits())
            assert caught.value.code == "EXECUTION_BACKEND_ERROR"
        else:
            assert restrict_process(Limits()) == 123
    if failure != "create":
        assert observed == {"memory": 1024 * 1024 * 1024, "flags": 0x102, "cpu": 150_000_000}


def test_posix_rlimits(monkeypatch):
    import importlib

    from xp_libs_analytics.engine import worker

    calls = []
    resource = SimpleNamespace(
        RLIMIT_AS=1, RLIMIT_CPU=2, setrlimit=lambda key, bounds: calls.append((key, bounds))
    )
    with monkeypatch.context() as m:
        m.setattr(worker.sys, "platform", "linux")
        m.setattr(importlib, "import_module", lambda _: resource)
        assert restrict_process(Limits()) is None
    assert calls == [(1, (1024 * 1024 * 1024, 1024 * 1024 * 1024)), (2, (15, 15))]
