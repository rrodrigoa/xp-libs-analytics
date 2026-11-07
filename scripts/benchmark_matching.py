"""Reproducible literal regression and matching workloads; no source values in evidence."""

import argparse
import json
import platform
import statistics
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import psutil
import yaml

from xp_libs_analytics import AnalyticsEngine, Limits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("docs/evidence/matching-benchmarks-v0.4.json")
    )
    parser.add_argument("--compare-baseline", type=Path)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--trusted-in-process", action="store_true")
    parser.add_argument("--repeats", type=int, default=9)
    args = parser.parse_args()
    engine = AnalyticsEngine(limits=Limits(max_queries_per_minute=10000))
    if args.trusted_in_process and not args.baseline:
        engine.limits = replace(engine.limits, force_matching_isolation=False)
    engine.register_records(
        "baseline",
        [
            {"text": "literal Peter" if i % 2 else "other", "group": str(i % 10), "x": i}
            for i in range(10000)
        ],
    )
    literal = {"field": "/text", "op": "contains", "value": "Peter"}
    fuzzy = {
        "field": "/text",
        "op": "fuzzy",
        "value": "literal Pter",
        "algorithm": "ratio",
        "min_score": 85,
    }
    cases = [("count", [], {}, 10000), ("literal", [literal], {}, 5000)]
    if not args.baseline:
        cases += [
            (
                "normalized",
                [
                    {
                        **literal,
                        "value": "PETER",
                        "normalization": {"case_sensitive": False, "unicode": "nfkc"},
                    }
                ],
                {},
                5000,
            ),
            ("regex", [{"field": "/text", "op": "regex", "value": "Peter$"}], {}, 5000),
            ("fuzzy", [fuzzy], {}, 5000),
            (
                "multi",
                [
                    {
                        "match": {
                            "fields": ["/text", "/group"],
                            "patterns": [
                                {
                                    "op": "fuzzy",
                                    "value": "literal Pter",
                                    "algorithm": "ratio",
                                    "min_score": 85,
                                }
                            ],
                            "mode": "any",
                        }
                    }
                ],
                {},
                5000,
            ),
            (
                "diagnostics",
                [fuzzy],
                {"options": {"matching_details": {"include": True, "top_values": 1}}},
                5000,
            ),
        ]
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor(),
        "logical_cpus": psutil.cpu_count(),
        "memory_bytes": psutil.virtual_memory().total,
        "trusted_in_process": args.trusted_in_process,
        "repeats": args.repeats,
        "measurements": {},
    }
    for name, filters, extra, expected in cases:
        query = yaml.safe_dump(
            {
                "version": "analytics.query/v1",
                "dataset": {"name": "baseline"},
                "filters": filters,
                "aggregations": [{"op": "count", "as": "n"}],
                **extra,
            }
        )
        engine.query_yaml(
            query
        )  # Warm imports/worker path; measured queries keep no cross-query cache.
        samples = []
        for _ in range(args.repeats):
            started = perf_counter()
            result = engine.query_yaml(query)
            samples.append((perf_counter() - started) * 1000)
            assert result.get("rows") == [{"n": expected}], result
        report["measurements"][name] = {
            "rows": 10000,
            "p50_ms": statistics.median(samples),
            "p95_ms": sorted(samples)[int(0.95 * len(samples))],
            "comparisons": result.get("matching", {}).get("comparisons", 0),
        }
    if args.compare_baseline:
        baseline = json.loads(args.compare_baseline.read_text())["measurements"]
        report["literal_regression_budget"] = {
            name: max(50.0, baseline[name]["p50_ms"] * 3) for name in ["count", "literal"]
        }
        report["literal_regression_pass"] = all(
            report["measurements"][name]["p50_ms"] <= bound
            for name, bound in report["literal_regression_budget"].items()
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if report.get("literal_regression_pass") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
