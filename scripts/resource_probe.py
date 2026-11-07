"""Hostile-input probes under OS limits, with measured RSS and hard termination."""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path
from time import monotonic, sleep

import psutil
import yaml

from xp_libs_analytics import AnalyticsEngine, AnalyticsError, Limits
from xp_libs_analytics.engine.worker import restrict_process
from xp_libs_analytics.parser import parse_yaml


def probe(sender, name):
    limits = Limits(timeout_seconds=1, memory_bytes=512 * 1024 * 1024)
    job = restrict_process(limits)
    try:
        if name == "memory":
            bytearray(1024 * 1024 * 1024)
        elif name == "cpu":
            while True:
                pass
        elif name == "yaml_depth":
            parse_yaml("a: " + "[" * 1000 + "1" + "]" * 1000)
        elif name == "wide_input":
            AnalyticsEngine().register_records("dataset_1", [{str(i): i for i in range(100_000)}])
        elif name in {"groups", "overlap", "distinct"}:
            engine = AnalyticsEngine()
            handle = engine.register_records(
                "dataset_2", [{"k": i, "t": "2026-11-06T00:00:00Z"} for i in range(10001)]
            )
            document = {
                "version": "analytics.query/v1",
                "dataset": {"name": handle.name},
                "aggregations": [{"op": "count", "as": "n"}],
            }
            if name == "groups":
                document["group_by"] = [{"field": "/k", "as": "key"}]
            elif name == "distinct":
                document["aggregations"] = [{"op": "count_distinct", "field": "/k", "as": "n"}]
            else:
                document.update(
                    casts=[
                        {"field": "/t", "to": "datetime", "format": "rfc3339", "on_error": "reject"}
                    ],
                    time_range={"field": "/t", "last_minutes": 60},
                    window={"type": "sliding", "size": "1h", "step": "1s"},
                )
            result = engine.validate_query(yaml.safe_dump(document))
            sender.send(result["error"]["code"])
            return
        sender.send("UNEXPECTED_SUCCESS")
    except AnalyticsError as exc:
        sender.send(exc.code.value)
    except MemoryError:
        sender.send("RESOURCE_MEMORY_LIMIT")
    finally:
        sender.close()
        del job


def main():
    results = []
    context = mp.get_context("spawn")
    for name in ["yaml_depth", "wide_input", "groups", "overlap", "distinct", "memory", "cpu"]:
        receiver, sender = context.Pipe(False)
        process = context.Process(target=probe, args=(sender, name))
        start = monotonic()
        process.start()
        sender.close()
        peak = 0
        while process.is_alive() and monotonic() - start < 4:
            try:
                peak = max(peak, psutil.Process(process.pid).memory_info().rss)
            except psutil.NoSuchProcess:
                pass
            sleep(0.005)
        killed = process.is_alive()
        if killed:
            process.terminate()
        process.join(2)
        outcome = "OS_TERMINATED" if process.exitcode else "UNKNOWN"
        try:
            if receiver.poll():
                outcome = receiver.recv()
        except (EOFError, BrokenPipeError):
            pass
        assert outcome not in {"UNKNOWN", "UNEXPECTED_SUCCESS"}, (name, outcome)
        assert peak < 512 * 1024 * 1024
        results.append(
            {
                "probe": name,
                "outcome": outcome,
                "wall_seconds": monotonic() - start,
                "peak_rss_bytes": peak,
                "parent_terminated": killed,
                "exit_code": process.exitcode,
            }
        )
        receiver.close()
        process.close()
    path = Path("docs/evidence/resource-probes.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
