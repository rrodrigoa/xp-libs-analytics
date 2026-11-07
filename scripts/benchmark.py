"""Reproducible synthetic snapshot benchmark; writes measurements, never source rows."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import threading
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import psutil
import yaml

from xp_libs_analytics import AnalyticsEngine, Limits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/benchmarks.json"))
    parser.add_argument("--repeats", type=int, default=9)
    args = parser.parse_args()
    process = psutil.Process()
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor(),
        "logical_cpus": psutil.cpu_count(),
        "total_memory_bytes": psutil.virtual_memory().total,
        "execution": (
            "trusted in-process SDK; full parse/type/cost planning included in query latency"
        ),
        "benchmarks": [],
    }
    for size in (1000, 10_000, 100_000):
        before = process.memory_info().rss
        peak = [before]
        stop = threading.Event()

        def sample(stop=stop, peak=peak) -> None:
            while not stop.wait(0.005):
                peak[0] = max(peak[0], process.memory_info().rss)

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        records = [
            {"group": str(i % 10), "value": i % 997, "nested": {"flag": i % 2 == 0}}
            for i in range(size)
        ]
        engine = AnalyticsEngine(limits=Limits(max_queries_per_minute=10000))
        started = perf_counter()
        handle = engine.register_records("dataset_1", records)
        ingest_ms = (perf_counter() - started) * 1000
        for kind in ("count", "grouped"):
            document = {
                "version": "analytics.query/v1",
                "dataset": {"name": handle.name},
                "aggregations": [{"op": "count", "as": "rows"}],
            }
            if kind == "grouped":
                document["group_by"] = [{"field": "/group", "as": "key"}]
                document["aggregations"] += [
                    {"op": "avg", "field": "/value", "as": "mean"},
                    {"op": "p95", "field": "/value", "as": "p95"},
                ]
            text = yaml.safe_dump(document)
            timings = []
            for _ in range(args.repeats):
                started = perf_counter()
                result = engine.query_yaml(text)
                timings.append((perf_counter() - started) * 1000)
                assert result["status"] == "OK", result
                assert sum(row["rows"] for row in result["rows"]) == size
            ordered = sorted(timings)
            report["benchmarks"].append(
                {
                    "rows": size,
                    "query": kind,
                    "repeats": args.repeats,
                    "ingestion_ms": ingest_ms,
                    "p50_ms": statistics.median(timings),
                    "p95_ms": ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))],
                    "peak_rss_bytes": peak[0],
                    "additional_peak_rss_bytes": peak[0] - before,
                }
            )
        engine.unregister_dataset(handle.name)
        stop.set()
        sampler.join()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
