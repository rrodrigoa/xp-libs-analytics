"""Per-query matching compiler: native expressions, exhaustive distinct fuzzy scoring."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import reduce
from typing import Any, cast

import polars as pl
from rapidfuzz import fuzz

from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.policy import Limits

from .models import MatchFieldsPredicate, Normalization, is_matching
from .normalize import normalize
from .patterns import like_regex, regex_flags, validate_regex


@dataclass(frozen=True)
class RuleUse:
    field: str
    op: str
    value: str
    normalization: Normalization
    algorithm: str | None = None
    min_score: float | None = None

    def key(self) -> str:
        return json.dumps(
            [
                self.field,
                self.op,
                self.value,
                self.normalization.model_dump(),
                self.algorithm,
                self.min_score,
            ],
            sort_keys=True,
        )


def leaves(node: Any) -> Iterator[Any]:
    if node.op in {"and", "or"}:
        for child in node.conditions:
            yield from leaves(child)
    elif node.op == "not":
        yield from leaves(node.condition)
    else:
        yield node


def uses(node: Any, types: dict[str, str] | None = None) -> list[RuleUse]:
    if isinstance(node, MatchFieldsPredicate):
        return [
            RuleUse(
                field,
                rule.op,
                rule.value,
                node.match.normalization,
                getattr(rule, "algorithm", None),
                getattr(rule, "min_score", None),
            )
            for field in node.match.fields
            for rule in node.match.patterns
        ]
    if not is_matching(node, types):
        return []
    if not isinstance(node.value, str):
        raise AnalyticsError(
            "MATCH_NORMALIZATION_INVALID"
            if getattr(node, "normalization", None) is not None
            else "QUERY_INVALID_LITERAL"
        )
    return [
        RuleUse(
            node.field,
            node.op,
            node.value,
            node.normalization or Normalization(),
            getattr(node, "algorithm", None),
            getattr(node, "min_score", None),
        )
    ]


def rule_config(rule: RuleUse) -> Normalization:
    config = rule.normalization
    if rule.op == "ilike":
        if config.case_sensitive and "case_sensitive" in config.model_fields_set:
            raise AnalyticsError("MATCH_NORMALIZATION_INVALID")
        config = config.model_copy(update={"case_sensitive": False})
    return config


def pattern(rule: RuleUse, limits: Limits) -> str:
    config = rule_config(rule)
    if rule.op == "regex":
        if len(rule.value.encode("utf-8")) > limits.max_regex_bytes:
            raise AnalyticsError("MATCH_REGEX_POLICY")
        if config.unicode != "none" or config.trim:
            raise AnalyticsError("MATCH_NORMALIZATION_INVALID")
        if (
            config.case_sensitive
            and "case_sensitive" in config.model_fields_set
            and "i" in regex_flags(rule.value)
        ):
            raise AnalyticsError("MATCH_NORMALIZATION_INVALID")
        value = rule.value if config.case_sensitive else "(?i)" + rule.value
        validate_regex(value, limits, wrapper_bytes=0 if config.case_sensitive else 4)
        return value
    value = normalize(rule.value, config)
    if rule.op in {"like", "ilike"}:
        value = like_regex(value)
    else:
        value = r"\b" + re.escape(value) + r"\b"
    validate_regex(value, limits, translated=True)
    return value


def validate_rules(nodes: list[Any], types: dict[str, str], limits: Limits) -> list[RuleUse]:
    result = []
    work = 0
    for node in nodes:
        if isinstance(node, MatchFieldsPredicate):
            body = node.match
            if len(set(body.fields)) != len(body.fields):
                raise AnalyticsError("QUERY_INVALID_LITERAL")
            if (
                len(body.fields) > limits.max_match_fields
                or len(body.patterns) > limits.max_match_patterns
            ):
                raise AnalyticsError("MATCH_COMPLEXITY_BUDGET_EXCEEDED")
        rules = uses(node, types)
        work += len(rules)
        if work > limits.max_match_work:
            raise AnalyticsError("MATCH_COMPLEXITY_BUDGET_EXCEEDED")
        for rule in rules:
            if rule.field not in types:
                raise AnalyticsError("DATA_FIELD_UNKNOWN")
            field_type = types[rule.field]
            if field_type == "mixed":
                raise AnalyticsError("DATA_FIELD_TYPE_CONFLICT")
            if field_type in {"array", "object"}:
                raise AnalyticsError("DATA_FIELD_NOT_SCALAR")
            if field_type not in {"string", "null"}:
                raise AnalyticsError(
                    "MATCH_NORMALIZATION_INVALID"
                    if rule.op in {"eq", "ne"}
                    else "QUERY_OPERATOR_TYPE"
                )
            if len(rule.value) > limits.max_match_literal_chars or (
                not rule.value and rule.op not in {"eq", "ne"}
            ):
                raise AnalyticsError("MATCH_PATTERN_INVALID")
            config = rule_config(rule)
            value = normalize(rule.value, config) if rule.op != "regex" else rule.value
            if len(value) > limits.max_match_literal_chars:
                raise AnalyticsError("MATCH_PATTERN_INVALID")
            if rule.op not in {"eq", "ne"} and not value:
                raise AnalyticsError("MATCH_PATTERN_INVALID")
            if rule.op == "fuzzy":
                if rule.min_score is None or rule.min_score < limits.min_fuzzy_score:
                    raise AnalyticsError("MATCH_FUZZY_THRESHOLD_INVALID")
                if len(value) < limits.min_fuzzy_query_chars:
                    raise AnalyticsError("MATCH_FUZZY_QUERY_TOO_SHORT")
            if rule.op in {"word", "like", "ilike", "regex"}:
                pattern(rule, limits)
            result.append(rule)
    return result


def conjuncts(node: Any) -> list[Any]:
    return (
        [c for child in node.conditions for c in conjuncts(child)] if node.op == "and" else [node]
    )


class MatchingCompiler:
    def __init__(
        self,
        frame: pl.DataFrame,
        columns: Mapping[str, tuple[str, str | None, str | None]],
        limits: Limits,
        *,
        score: bool,
    ) -> None:
        self.frame, self.columns, self.limits, self.score = frame, columns, limits, score
        self.expressions: dict[str, pl.Expr] = {}
        self.mappings: dict[tuple[str, str], dict[str, str]] = {}
        self.scores: dict[str, dict[str, float]] = {}
        self.checked: set[str] = set()
        self.comparisons = 0
        self.normalized_bytes = 0
        self.candidates = 0

    def column(self, field: str) -> pl.Expr:
        return pl.col(self.columns[field][0]).cast(pl.String)

    def check_values(self, field: str) -> None:
        if field not in self.checked:
            values = self.frame.get_column(self.columns[field][0]).cast(pl.String)
            if cast(int, values.str.len_chars().max() or 0) > self.limits.max_match_value_chars:
                raise AnalyticsError("MATCH_CANDIDATE_BUDGET_EXCEEDED")
            self.checked.add(field)

    def mapping(self, field: str, config: Normalization) -> dict[str, str]:
        key = (field, config.model_dump_json())
        if key not in self.mappings:
            self.check_values(field)
            values = self.frame.get_column(self.columns[field][0]).drop_nulls().unique().to_list()
            mapped = {}
            for value in sorted(values):
                normalized = normalize(value, config)
                self.normalized_bytes += len(normalized.encode("utf-8"))
                if (
                    len(normalized) > self.limits.max_match_value_chars
                    or self.normalized_bytes > self.limits.max_match_normalized_bytes
                ):
                    raise AnalyticsError("MATCH_CANDIDATE_BUDGET_EXCEEDED")
                mapped[value] = normalized
            self.mappings[key] = mapped
        return self.mappings[key]

    def normalized_column(self, field: str, config: Normalization) -> pl.Expr:
        self.check_values(field)
        col = self.column(field)
        if config == Normalization():
            return col
        mapped = self.mapping(field, config)
        return col.replace_strict(
            list(mapped), list(mapped.values()), default=None, return_dtype=pl.String
        )

    def expression(self, rule: RuleUse) -> pl.Expr:
        key = rule.key()
        if key in self.expressions:
            return self.expressions[key]
        config = rule_config(rule)
        col = (
            self.normalized_column(rule.field, config)
            if rule.op != "regex"
            else self.column(rule.field)
        )
        self.check_values(rule.field)
        value = rule.value if rule.op == "regex" else normalize(rule.value, config)
        if rule.op == "fuzzy":
            mapped = self.mapping(rule.field, config)
            distinct = sorted(set(mapped.values()))
            if len(distinct) > self.limits.max_fuzzy_candidates:
                raise AnalyticsError("MATCH_CANDIDATE_BUDGET_EXCEEDED")
            self.comparisons += len(distinct)
            self.candidates += len(distinct)
            if self.comparisons > self.limits.max_fuzzy_comparisons:
                raise AnalyticsError("MATCH_COMPLEXITY_BUDGET_EXCEEDED")
            scorer = {
                "ratio": fuzz.ratio,
                "wratio": fuzz.WRatio,
                "token_sort": fuzz.token_sort_ratio,
            }[rule.algorithm or "ratio"]
            scores = (
                {
                    candidate: float(
                        scorer(value, candidate, processor=None, score_cutoff=rule.min_score)
                    )
                    for candidate in distinct
                }
                if self.score
                else {}
            )
            qualified = {
                candidate: score
                for candidate, score in scores.items()
                if score >= (rule.min_score or 0)
            }
            self.scores[key] = qualified
            expr = pl.when(col.is_null()).then(None).otherwise(col.is_in(list(qualified)))
        elif rule.op in {"word", "like", "ilike", "regex"}:
            expr = col.str.contains(pattern(rule, self.limits), literal=False, strict=True)
        elif rule.op in {"eq", "ne"}:
            expr = col == pl.lit(value) if rule.op == "eq" else col != pl.lit(value)
        elif rule.op in {"contains", "not_contains"}:
            expr = col.str.contains(value, literal=True)
            if rule.op == "not_contains":
                expr = ~expr
        elif rule.op == "starts_with":
            expr = col.str.starts_with(value)
        else:
            expr = col.str.ends_with(value)
        self.expressions[key] = expr
        return expr

    def predicate(self, node: Any) -> pl.Expr:
        return reduce(lambda a, b: a | b, [self.expression(rule) for rule in uses(node)])

    def cost(self, rules: list[RuleUse]) -> dict[str, Any]:
        return {
            "used": bool(rules),
            "work_units": len(rules),
            "comparisons": self.comparisons,
            "distinct_candidates_examined": self.candidates,
            "normalized_bytes": self.normalized_bytes,
            "requires_isolation": any(r.op in {"fuzzy", "regex"} for r in rules),
            "candidate_scope": "time_and_independent_nonfuzzy_conjuncts",
        }


def prepare(
    query: Any,
    frame: pl.DataFrame,
    columns: Mapping[str, tuple[str, str | None, str | None]],
    types: dict[str, str],
    limits: Limits,
    ordinary: Callable[..., pl.Expr],
    *,
    score: bool,
) -> tuple[pl.DataFrame, MatchingCompiler, list[RuleUse]]:
    nodes = [
        node
        for root in list(query.filters)
        + [a.where for a in query.aggregations if hasattr(a, "where")]
        for node in leaves(root)
    ]
    rules = validate_rules(nodes, types, limits)
    compiler = MatchingCompiler(frame, columns, limits, score=score)
    if rules and limits.match_pushdown:
        safe = [
            c
            for root in query.filters
            for c in conjuncts(root)
            if not any(r.op == "fuzzy" for n in leaves(c) for r in uses(n, types))
        ]
        # Apply ordinary typed restrictions first; never push an OR/NOT child independently.
        safe.sort(key=lambda c: any(is_matching(n, types) for n in leaves(c)))
        for c in safe:
            frame = frame.filter(ordinary(c, columns, types, compiler))
            compiler.frame = frame
        compiler = MatchingCompiler(frame, columns, limits, score=score)
    for rule in rules:
        compiler.expression(rule)
    return frame, compiler, rules
