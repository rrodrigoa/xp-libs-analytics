"""Optional real-agent evaluations. Endpoints are supplied only at runtime."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
from collections import Counter
from pathlib import Path

from .endpoint_security import PrivacyGuard, private_execution
from .fixtures import oracle
from .reporting import Report, save_report, summary
from .scenarios import ROOT, load_scenarios, vary
from .skill_loader import load_skill


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["list", "validate", "preflight", "run", "compare", "report"])
    p.add_argument(
        "--endpoint", help="Runtime-only OpenAI-compatible API base URL; prompts when omitted"
    )
    p.add_argument("--model", help="Runtime-only model ID; required for live commands")
    p.add_argument("--suite", default="all")
    p.add_argument("--scenario")
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--temperature", type=float, default=0)
    p.add_argument("--max-turns", type=int, default=12)
    p.add_argument("--max-tool-calls", type=int, default=12)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--report", type=Path)
    p.add_argument("--compare-skill", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument(
        "--traces", action="store_true", help="Explicitly export redacted Inspect message traces"
    )
    return p


def validate() -> dict:
    scenarios = load_scenarios()
    for s in scenarios:
        result = oracle(s)
        if result is not None and result["status"] == "ERROR":
            raise ValueError(f"Invalid oracle for {s.id}")
    _, skill_hash = load_skill()
    return {
        "status": "PASS",
        "scenarios": dict(Counter(s.category for s in scenarios)),
        "skill_hash": skill_hash,
    }


async def live(args, endpoint: str, credential: str):
    from .task import preflight, run_scenario, runtime_model

    guard = PrivacyGuard(endpoint, credential)
    with private_execution():
        check = await preflight(endpoint, args.model, credential, args.timeout)
    if args.command == "preflight":
        print(json.dumps(guard.sanitize(check), indent=2))
        return 0
    selected = load_scenarios(args.suite, args.scenario)
    results, traces = [], []
    modes = ["skill", "baseline"] if args.command == "compare" or args.compare_skill else ["skill"]
    for scenario in selected:
        for trial in range(args.repetitions):
            sample = vary(scenario, args.seed, trial)
            sample.limits.max_turns = min(sample.limits.max_turns, args.max_turns)
            sample.limits.max_tool_calls = min(sample.limits.max_tool_calls, args.max_tool_calls)
            sample.limits.timeout = args.timeout
            for mode in modes:
                with private_execution():
                    async with runtime_model(
                        args.model, endpoint, credential, args.temperature, args.timeout
                    ) as model:
                        result = await run_scenario(
                            sample,
                            model,
                            mode=mode,
                            trial=trial,
                            trace_out=traces if args.traces else None,
                        )
                if guard.sanitize(result.model_dump()) != result.model_dump():
                    result.security_violation = True
                    result.status = "FAIL"
                    result.explanation = "Sensitive runtime details appeared in an agent trace"
                results.append(result)
                if args.verbose:
                    print(
                        f"{result.scenario_id} [{mode}]: {result.status} ({result.duration:.1f}s)"
                    )
    _, skill_hash = load_skill()
    report = save_report(
        results,
        model=args.model,
        skill_hash=skill_hash,
        suite=args.suite,
        seed=args.seed,
        guard=guard,
        directory=args.report or ROOT / "reports" / __import__("uuid").uuid4().hex,
        traces=traces if args.traces else None,
    )
    print(summary(report))
    return (
        2
        if any(r.status == "INFRASTRUCTURE_ERROR" for r in results)
        else int(any(r.status == "FAIL" for r in results))
    )


def main() -> int:
    p = parser()
    args = p.parse_args()
    if (
        args.repetitions < 1
        or not 1 <= args.max_turns <= 40
        or not 1 <= args.max_tool_calls <= 40
        or not 1 <= args.timeout <= 1800
    ):
        p.error("Use positive repetitions, 1..40 turns/calls, and 1..1800 seconds")
    if args.command == "list":
        for scenario in load_scenarios(args.suite, args.scenario):
            print(f"{scenario.id}: {scenario.description}")
        return 0
    if args.command == "validate":
        print(json.dumps(validate(), indent=2))
        return 0
    if args.command == "report":
        if args.report is None:
            p.error("--report is required")
        path = args.report / "results.json" if args.report.is_dir() else args.report
        print(summary(Report.model_validate_json(path.read_text())))
        return 0
    if not args.model:
        p.error("--model is required for live commands")
    endpoint = args.endpoint or getpass.getpass("OpenAI-compatible API base URL (not saved): ")
    credential = os.environ.get("XP_ANALYTICS_EVAL_API_KEY", "")
    try:
        endpoint = PrivacyGuard(endpoint, credential).endpoint
        return asyncio.run(live(args, endpoint, credential))
    except Exception:
        print(
            "INFRASTRUCTURE_ERROR: preflight or evaluation failed. "
            "Check model availability, native tool calling and MCP connectivity. "
            "Runtime details suppressed for privacy."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
