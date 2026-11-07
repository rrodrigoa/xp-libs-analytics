"""Run synthetic examples through restricted YAML, strict AST and the complete SDK."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from xp_libs_analytics import AnalyticsEngine, AnalyticsQuery
from xp_libs_analytics.parser import parse_yaml

ROOT = Path(__file__).resolve().parent


def load_example(path: Path) -> dict[str, Any]:
    document = parse_yaml(path.read_text(encoding="utf-8"))
    AnalyticsQuery.model_validate(document)
    return document


def run_example(path: Path) -> dict[str, Any]:
    data = (
        "matching_events.json"
        if int(path.stem[:2]) >= 18
        else "mixed_types.json"
        if path.stem.startswith("16_")
        else "events.json"
    )
    engine = AnalyticsEngine()
    handle = engine.register_records(
        "example_data", (ROOT / "data" / data).read_text(encoding="utf-8")
    )
    try:
        document = load_example(path)
        result = engine.query_yaml(yaml.safe_dump(document, sort_keys=False))
        if result["status"] == "ERROR":
            raise RuntimeError(result["error"]["code"])
        return {"example": path.name, "result": result}
    finally:
        engine.unregister_dataset(handle.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--lint-only", action="store_true")
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--query", metavar="NAME")
    args = parser.parse_args()
    paths = sorted((ROOT / "queries").glob("*.yaml"))
    if args.list:
        print("\n".join(p.stem for p in paths))
    elif args.lint_only:
        for path in paths:
            load_example(path)
        print(f"PASS: restricted parser and strict AST validated {len(paths)} examples.")
    else:
        selected = paths if args.all else [p for p in paths if args.query in (p.name, p.stem)]
        if not selected:
            parser.error("Unknown example; use --list")
        for path in selected:
            print(json.dumps(run_example(path), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
