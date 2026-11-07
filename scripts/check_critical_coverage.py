"""Enforce >=95% branch coverage for each critical executable module.

Branchless modules must instead meet the same statement coverage threshold.
Usage: python scripts/check_critical_coverage.py coverage.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_DIRS = (
    "src/xp_libs_analytics/matching/",
    "src/xp_libs_analytics/registry.py",
    "src/xp_libs_analytics/ingest/",
    "src/xp_libs_analytics/policy/",
    "src/xp_libs_analytics/models/",
    "src/xp_libs_analytics/engine/",
    "src/xp_libs_analytics/errors/",
    "src/xp_libs_analytics/parser/",
)
MIN_BRANCH_PCT = 95.0


def main() -> int:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    files: dict = data.get("files", {})
    failed = []
    for directory in REQUIRED_DIRS:
        matches = [
            stats for name, stats in files.items() if name.replace("\\", "/").startswith(directory)
        ]
        if not matches:
            failed.append(f"missing covered files: {directory}")
            continue
        for name, stats in files.items():
            if not name.replace("\\", "/").startswith(directory):
                continue
            summary = stats["summary"]
            total = summary["num_branches"]
            covered = summary["covered_branches"]
            if total == 0:
                total, covered = summary["num_statements"], summary["covered_lines"]
            if total == 0:
                continue
            pct = 100 * covered / total
            print(f"{name}: {pct:.2f}% ({covered}/{total})")
            if pct < MIN_BRANCH_PCT:
                failed.append(f"{name}: {pct:.2f}% < {MIN_BRANCH_PCT:.2f}%")
    if failed:
        print("Critical branch coverage FAILED:\n" + "\n".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
