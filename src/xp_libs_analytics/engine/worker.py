"""A killable process with OS-enforced CPU/memory limits."""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
from typing import Any, cast

from xp_libs_analytics.engine.planner import LogicalPlan
from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.policy import Limits


def restrict_process(limits: Limits) -> Any:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("min_ws", ctypes.c_size_t),
                ("max_ws", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in ("r_ops", "w_ops", "o_ops", "r_bytes", "w_bytes", "o_bytes")
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", IO),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        handle = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x100 | 0x2  # PROCESS_MEMORY | PROCESS_TIME
        info.process_memory = limits.memory_bytes
        info.basic.process_time = int(limits.timeout_seconds * 10_000_000)
        if (
            not handle
            or not kernel.SetInformationJobObject(
                handle, 9, ctypes.byref(info), ctypes.sizeof(info)
            )
            or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())
        ):
            raise AnalyticsError("EXECUTION_BACKEND_ERROR")
        return handle  # Keep job alive for the process lifetime.
    import importlib

    resource = importlib.import_module("resource")

    resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
    cpu = max(1, int(limits.timeout_seconds))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    return None


def run_worker(connection: Any, plan: LogicalPlan, limits: Limits) -> None:
    os.environ["POLARS_MAX_THREADS"] = "2"
    try:
        job_handle = restrict_process(limits)
        from xp_libs_analytics.engine.backend import execute_plan

        result = execute_plan(plan, limits)
        connection.send(result)
        del job_handle
    except MemoryError:
        connection.send(AnalyticsError("RESOURCE_MEMORY_LIMIT").envelope())
    except AnalyticsError as exc:
        connection.send(exc.envelope())
    except Exception:
        connection.send(AnalyticsError("EXECUTION_BACKEND_ERROR").envelope())
    finally:
        connection.close()


def execute_isolated(plan: LogicalPlan, limits: Limits) -> dict[str, Any]:
    context = mp.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=run_worker, args=(sender, plan, limits), daemon=True)
    process.start()
    sender.close()
    try:
        try:
            if not receiver.poll(limits.timeout_seconds):
                raise AnalyticsError("RESOURCE_TIMEOUT")
            return cast(dict[str, Any], receiver.recv())
        except (EOFError, BrokenPipeError):
            raise AnalyticsError("EXECUTION_BACKEND_ERROR") from None
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        process.close()
