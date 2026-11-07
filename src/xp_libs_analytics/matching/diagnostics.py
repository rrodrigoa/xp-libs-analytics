"""Policy-cleared, deterministic matching evidence; never part of record selection."""

import hashlib
import hmac
from typing import Any

import polars as pl
import rapidfuzz

from xp_libs_analytics.errors import AnalyticsError

from .compiler import MatchingCompiler, RuleUse, rule_config
from .normalize import VERSION, normalize

PRECEDENCE = {
    "eq": 0,
    "ne": 0,
    "word": 1,
    "starts_with": 2,
    "ends_with": 2,
    "contains": 3,
    "not_contains": 3,
    "like": 4,
    "ilike": 4,
    "regex": 5,
    "fuzzy": 6,
}
NAMES = {"eq": "exact", "ne": "not_exact", "starts_with": "prefix", "ends_with": "suffix"}


def matching_evidence(
    frame: pl.DataFrame,
    compiler: MatchingCompiler,
    rules: list[RuleUse],
    *,
    include: bool,
    top_values: int,
    raw: bool,
    key: bytes,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        **compiler.cost(rules),
        "predicate_complete": True,
        "algorithm_versions": {
            "rapidfuzz": rapidfuzz.__version__,
            "polars": pl.__version__,
            "normalization": VERSION,
        },
        "diagnostic_scope": "matching_leaf_hits_within_post_all_filters_pre_aggregation",
    }
    if not include:
        return result
    result["requires_isolation"] = True
    unique = {rule.key(): rule for rule in rules}
    hits: dict[tuple[str, str], dict[str, Any]] = {}
    for rule in unique.values():
        mask = frame.select(compiler.expression(rule).alias("matched")).get_column("matched")
        values = frame.get_column(compiler.columns[rule.field][0]).to_list()
        for row, (value, matched) in enumerate(zip(values, mask, strict=True)):
            if matched is not True:
                continue
            if (rule.field, value) not in hits and len(
                hits
            ) >= compiler.limits.max_match_diagnostic_candidates:
                raise AnalyticsError("MATCH_CANDIDATE_BUDGET_EXCEEDED")
            hit = hits.setdefault((rule.field, value), {"rows": set(), "rules": {}})
            hit["rows"].add(row)
            score = compiler.scores.get(rule.key(), {}).get(normalize(value, rule_config(rule)))
            hit["rules"][rule.key()] = (rule, score)
    ranked = []
    for (field, value), hit in hits.items():
        matched_rules = sorted(
            hit["rules"].values(),
            key=lambda item: (PRECEDENCE[item[0].op], -(item[1] or 0), item[0].key()),
        )
        primary, score = matched_rules[0]
        evidence = [
            {
                "match_type": NAMES.get(r.op, r.op),
                "normalization": rule_config(r).model_dump(),
                **({"algorithm": r.algorithm, "score": round(s, 6)} if s is not None else {}),
            }
            for r, s in matched_rules
        ]
        entry = {
            "field": field,
            "value": value if raw else None,
            "value_ref": hmac.new(key, (field + "\0" + value).encode(), hashlib.sha256).hexdigest(),
            "frequency": len(hit["rows"]),
            "match_type": NAMES.get(primary.op, primary.op),
            "normalization": rule_config(primary).model_dump(),
            "matched_rules": evidence,
            **(
                {"fuzzy": {"algorithm": primary.algorithm}, "score": round(score, 6)}
                if score is not None
                else {}
            ),
        }
        order = (
            PRECEDENCE[primary.op],
            -(score or 0),
            -entry["frequency"],
            normalize(value, rule_config(primary)),
            field,
            value,
        )
        ranked.append((order, entry))
    ranked.sort(key=lambda item: item[0])
    truncated = len(ranked) > top_values
    result.update(
        top_values=[{**entry, "truncated": truncated} for _, entry in ranked[:top_values]],
        diagnostics_truncated=truncated,
        complete=not truncated,
    )
    return result
