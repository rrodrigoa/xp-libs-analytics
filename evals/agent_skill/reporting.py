"""Allowlisted, privacy-checked JSON/JUnit summaries and paired metrics."""

from __future__ import annotations

import json
import math
import statistics
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .endpoint_security import PrivacyGuard
from .scenarios import Strict
from .scoring import Result


class Report(Strict):
    run_id: str
    timestamp: str
    model: str
    skill_hash: str
    suite: str
    seed: int
    results: list[Result]
    metrics: dict


def metrics(results: list[Result]) -> dict:
    judged = [r for r in results if r.status in {"PASS", "FAIL"}]

    def success(rows):
        return sum(r.status == "PASS" for r in rows) / len(rows) if rows else None

    durations = sorted(r.duration for r in results)
    recovery = [r for r in judged if r.category == "recovery"]
    positives = [r for r in judged if r.category in {"positive", "temporal", "skill_comparison"}]

    def rate(dimension):
        return (
            sum(r.dimensions.get(dimension, False) for r in judged) / len(judged)
            if judged
            else None
        )

    return {
        "attempted": len(results),
        "judged": len(judged),
        "successful": sum(r.status == "PASS" for r in judged),
        "infrastructure_errors": sum(r.status == "INFRASTRUCTURE_ERROR" for r in results),
        "skipped": sum(r.status == "SKIPPED" for r in results),
        "end_to_end_success_rate": success(judged),
        "positive_success_rate": success(positives),
        "first_call_correctness_rate": sum(r.first_call_correct for r in judged) / len(judged)
        if judged
        else None,
        "yaml_validation_success_rate": rate("yaml_validity"),
        "tool_selection_accuracy": rate("tool_selection"),
        "query_semantic_correctness": rate("query_semantics"),
        "result_correctness": rate("result_correctness"),
        "seeded_recovery_success_rate": success(recovery),
        "natural_recovery_success_count": sum(r.natural_recovery for r in judged),
        "natural_recovery_success_rate": (
            sum(r.natural_recovery for r in judged)
            / len(
                [
                    r
                    for r in judged
                    if any(not c.seeded and c.response.get("error") for c in r.calls)
                ]
            )
            if any(any(not c.seeded and c.response.get("error") for c in r.calls) for r in judged)
            else None
        ),
        "mean_tool_calls": statistics.mean(len(r.calls) for r in results) if results else 0,
        "mean_retries": statistics.mean(r.retries for r in results) if results else 0,
        "unsafe_tool_calls": sum(r.unsafe_tool_calls for r in results),
        "security_violations": sum(r.security_violation for r in results),
        "unsupported_analytical_claims": sum(
            not r.dimensions.get("final_answer", True) for r in judged
        ),
        "mean_duration": statistics.mean(durations) if durations else 0,
        "p95_duration": durations[max(0, math.ceil(0.95 * len(durations)) - 1)] if durations else 0,
        "skill_success_rate": success([r for r in judged if r.mode == "skill"]),
        "baseline_success_rate": success([r for r in judged if r.mode == "baseline"]),
    }


def save_report(
    results: list[Result],
    *,
    model: str,
    skill_hash: str,
    suite: str,
    seed: int,
    guard: PrivacyGuard,
    directory: Path,
    traces: list | None = None,
) -> Report:
    report = Report(
        run_id=uuid4().hex,
        timestamp=datetime.now(UTC).isoformat(),
        model=model,
        skill_hash=skill_hash,
        suite=suite,
        seed=seed,
        results=results,
        metrics=metrics(results),
    )
    clean = guard.sanitize(report.model_dump(mode="json"))
    guard.assert_safe(clean)
    report = Report.model_validate(clean)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "results.json").write_text(
        json.dumps(clean, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    xml = ET.Element(
        "testsuite",
        tests=str(len(results)),
        failures=str(sum(r.status == "FAIL" for r in results)),
        errors=str(sum(r.status == "INFRASTRUCTURE_ERROR" for r in results)),
        skipped=str(sum(r.status == "SKIPPED" for r in results)),
    )
    for result in report.results:
        case = ET.SubElement(
            xml,
            "testcase",
            name=f"{result.scenario_id}:{result.mode}:{result.trial}",
            time=str(result.duration),
        )
        if result.status != "PASS":
            ET.SubElement(
                case,
                {"FAIL": "failure", "INFRASTRUCTURE_ERROR": "error", "SKIPPED": "skipped"}[
                    result.status
                ],
                message=result.explanation,
            )
    guard.assert_safe(ET.tostring(xml, encoding="unicode"))
    ET.ElementTree(xml).write(directory / "junit.xml", encoding="utf-8", xml_declaration=True)
    if traces is not None:
        clean_traces = guard.sanitize(traces)
        guard.assert_safe(clean_traces)
        (directory / "traces.json").write_text(
            json.dumps(clean_traces, indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
    return report


def summary(report: Report) -> str:
    m = report.metrics
    return (
        f"{m['successful']}/{m['judged']} judged passed; "
        f"{m['infrastructure_errors']} infrastructure errors; "
        f"{m['security_violations']} security violations. "
        f"Skill={m['skill_success_rate']}, baseline={m['baseline_success_rate']}, "
        f"seeded recovery={m['seeded_recovery_success_rate']}"
    )
