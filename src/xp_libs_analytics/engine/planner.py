"""Type resolution and conservative admission before expression compilation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.ingest import Snapshot, flatten, kind, pointer_tokens
from xp_libs_analytics.matching.models import TEXT_OPS as MATCH_OPS
from xp_libs_analytics.matching.models import MatchFieldsPredicate, is_matching
from xp_libs_analytics.models import AnalyticsQuery, HavingPredicate, Predicate, RelativeTime
from xp_libs_analytics.policy import Limits, Principal

INTERVALS = {
    "1s": 1,
    "5s": 5,
    "10s": 10,
    "30s": 30,
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
}
NUMERIC_OPS = set("sum avg median p50 p90 p95 p99 stddev variance sum_if avg_if".split())
NULL_OPS = {"is_null", "is_not_null", "is_missing", "is_present"}
ORDER_OPS = {"gt", "gte", "lt", "lte", "between"}
TEXT_OPS = {"contains", "starts_with", "ends_with"}


def timestamp(value: Any) -> datetime:
    if type(value) is not str or not re.fullmatch(
        r"\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:[Zz]|[+-]\d\d:\d\d)", value
    ):
        raise ValueError
    return datetime.fromisoformat(value.upper().replace("Z", "+00:00")).astimezone(UTC)


def cast_value(value: Any, target: str, fmt: str | None) -> Any:
    if type(value) in (bool, dict, list):
        if target == "string" and type(value) is bool:
            return "true" if value else "false"
        raise ValueError
    if target == "string":
        return str(value)
    if target == "datetime":
        if fmt == "rfc3339":
            return timestamp(value)
        if type(value) not in (int, float):
            raise ValueError
        divisor = {"epoch_s": 1, "epoch_ms": 1000, "epoch_us": 1_000_000}[str(fmt)]
        return datetime.fromtimestamp(value / divisor, UTC)
    if target == "float64":
        if type(value) is str and re.fullmatch(r"[+-]?[0-9]+", value) and abs(int(value)) > 2**53:
            raise ValueError
        converted = float(value)
        if not math.isfinite(converted) or type(value) is int and abs(value) > 2**53:
            raise ValueError
        return converted
    converted = int(value)
    if not -(2**63) <= converted < 2**63 or type(value) is float and converted != value:
        raise ValueError
    return converted


def walk(predicate: Predicate | HavingPredicate) -> list[Predicate | HavingPredicate]:
    if predicate.op in ("and", "or"):
        return [predicate] + [n for c in getattr(predicate, "conditions") for n in walk(c)]
    if predicate.op == "not":
        return [predicate] + walk(getattr(predicate, "condition"))
    return [predicate]


def predicate_depth(predicate: Predicate | HavingPredicate) -> int:
    if predicate.op in ("and", "or"):
        return 1 + max(predicate_depth(c) for c in getattr(predicate, "conditions"))
    if predicate.op == "not":
        return 1 + predicate_depth(getattr(predicate, "condition"))
    return 1


def check_predicate(
    predicate: Predicate | HavingPredicate,
    types: dict[str, str],
    *,
    having: bool = False,
    limits: Limits | None = None,
) -> None:
    for node in walk(predicate):
        if node.op in ("and", "or", "not"):
            continue
        if not having and (
            node.op == "match"
            or node.op in MATCH_OPS - TEXT_OPS
            or getattr(node, "normalization", None) is not None
        ):
            from xp_libs_analytics.matching.compiler import validate_rules

            validate_rules([node], types, limits or Limits())
            continue
        if getattr(node, "field") not in types:
            raise AnalyticsError("QUERY_HAVING_INVALID" if having else "DATA_FIELD_UNKNOWN")
        field_type = types[getattr(node, "field")]
        if node.op in NULL_OPS:
            continue
        if field_type == "mixed":
            raise AnalyticsError("DATA_FIELD_TYPE_CONFLICT")
        if field_type in ("object", "array"):
            raise AnalyticsError("DATA_FIELD_NOT_SCALAR")
        if node.op in TEXT_OPS and field_type not in ("string", "null"):
            raise AnalyticsError("QUERY_OPERATOR_TYPE")
        if (
            node.op in TEXT_OPS
            and getattr(node, "value") is not None
            and type(getattr(node, "value")) is not str
        ):
            raise AnalyticsError("QUERY_INVALID_LITERAL")
        if node.op in ORDER_OPS and field_type == "boolean":
            raise AnalyticsError("QUERY_OPERATOR_TYPE")
        values = (
            getattr(node, "values")
            if node.op in ("in", "not_in")
            else [getattr(node, "lower"), getattr(node, "upper")]
            if node.op == "between"
            else [getattr(node, "value")]
        )
        literal_types = {kind(v) for v in values if v is not None}
        if len(literal_types) > 1 and not literal_types <= {"integer", "float"}:
            raise AnalyticsError("QUERY_INVALID_LITERAL")
        for value in values:
            if value is None or field_type == "null":
                continue
            compatible = kind(value) == field_type or {kind(value), field_type} <= {
                "integer",
                "float",
            }
            if field_type == "datetime":
                try:
                    timestamp(value)
                    compatible = True
                except ValueError:
                    compatible = False
            if not compatible:
                raise AnalyticsError("QUERY_OPERATOR_TYPE")
        if node.op == "between":
            lower, upper = getattr(node, "lower"), getattr(node, "upper")
            if lower is None or upper is None:
                raise AnalyticsError("QUERY_INVALID_LITERAL")
            if field_type == "datetime":
                lower, upper = timestamp(lower), timestamp(upper)
            if lower > upper:
                raise AnalyticsError("QUERY_INVALID_LITERAL")


@dataclass(frozen=True)
class LogicalPlan:
    version: str
    query_json: str
    fingerprint: str
    fields: tuple[str, ...]
    types: tuple[tuple[str, str], ...]
    columns: tuple[tuple[str, tuple[Any, ...]], ...]
    quality_json: str
    start: datetime | None
    end: datetime | None
    window_size: int
    window_step: int
    estimated_groups: int
    estimated_windows: int
    input_rows: int
    matching_cost_json: str = "{}"
    diagnostic_key: bytes = b""

    def explain(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "stages": [
                "scan",
                "project",
                "filter",
                "window",
                "aggregate",
                "having",
                "sort",
                "limit",
                "encode",
            ],
            "matching": json.loads(self.matching_cost_json),
            "cost": {
                "input_rows": self.input_rows,
                "groups": self.estimated_groups,
                "windows": self.estimated_windows,
                "expanded_rows": self.input_rows
                * max(1, self.window_size // max(1, self.window_step)),
            },
        }


def plan_query(
    query: AnalyticsQuery, snapshot: Snapshot, principal: Principal, limits: Limits, now: datetime
) -> LogicalPlan:
    if "read" not in principal.scopes:
        raise AnalyticsError("ACCESS_DENIED")
    schema = snapshot.schema()
    predicates = list(query.filters) + [a.where for a in query.aggregations if hasattr(a, "where")]
    nodes = [n for p in predicates for n in walk(p)]
    expanded_work = sum(
        len(n.match.fields) * len(n.match.patterns) if isinstance(n, MatchFieldsPredicate) else 1
        for n in nodes
    )
    if expanded_work > 32 and any(isinstance(n, MatchFieldsPredicate) for n in nodes):
        raise AnalyticsError("MATCH_COMPLEXITY_BUDGET_EXCEEDED")
    if len(nodes) > 32 or any(predicate_depth(p) > 4 for p in predicates):
        raise AnalyticsError("QUERY_PREDICATE_LIMIT")
    if sum(len(walk(p)) for p in query.having) > 10 or any(
        predicate_depth(p) > 4 for p in query.having
    ):
        raise AnalyticsError("QUERY_PREDICATE_LIMIT")
    fields = {n.field for n in nodes if hasattr(n, "field")}
    fields.update(
        field for n in nodes if isinstance(n, MatchFieldsPredicate) for field in n.match.fields
    )
    fields.update(a.field for a in query.aggregations if hasattr(a, "field"))
    fields.update(g.field for g in query.group_by)
    fields.update(c.field for c in query.casts)
    if query.time_range:
        fields.add(query.time_range.field)
    for field in sorted(fields):
        pointer_tokens(field, limits.max_depth)
        # Hidden and nonexistent fields are indistinguishable for restricted principals.
        if not principal.permits(field) or principal.fields is not None and field not in schema:
            raise AnalyticsError("ACCESS_FIELD_DENIED")
        if field not in schema:
            raise AnalyticsError("DATA_FIELD_UNKNOWN")
    details = query.options.matching_details
    if details.include and details.top_values > limits.max_match_diagnostic_values:
        raise AnalyticsError("MATCH_COMPLEXITY_BUDGET_EXCEEDED")
    matching_types = {p: schema[p]["type"] for p in fields}
    matching_types.update(
        (c.field, {"int64": "integer", "float64": "float"}.get(c.to, c.to)) for c in query.casts
    )
    if details.include_raw_values:
        match_fields = {
            field
            for n in nodes
            if is_matching(n, matching_types)
            for field in (
                n.match.fields if isinstance(n, MatchFieldsPredicate) else [getattr(n, "field")]
            )
        }
        if not details.include:
            raise AnalyticsError("QUERY_MALFORMED")
        if not limits.allow_match_raw_values or not match_fields <= principal.match_raw_fields:
            raise AnalyticsError("MATCH_DIAGNOSTICS_UNAUTHORIZED")
    # Check matching syntax against authorized post-cast types before reading records.
    has_matching = any(is_matching(n, matching_types) for n in nodes)
    if has_matching:
        from xp_libs_analytics.matching.compiler import validate_rules

        validate_rules(nodes, matching_types, limits)
    aliases = [g.alias for g in query.group_by] + [a.alias for a in query.aggregations]
    reserved = {"window_start", "window_end", "query_id", "group_key_status"}
    if len(set(aliases)) != len(aliases) or any(
        not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", a) or a in reserved for a in aliases
    ):
        raise AnalyticsError("QUERY_ALIAS_INVALID")
    if len({g.field for g in query.group_by}) != len(query.group_by):
        raise AnalyticsError("QUERY_GROUP_INVALID")
    if len({c.field for c in query.casts}) != len(query.casts):
        raise AnalyticsError("DATA_CAST_UNSUPPORTED")
    records = [flatten(r) for r in snapshot.records()]
    types = {p: schema[p]["type"] for p in fields}
    columns: dict[str, tuple[Any, ...]] = {}
    quality = {}
    cast_map = {c.field: c for c in query.casts}
    for i, p in enumerate(sorted(fields)):
        present = tuple(p in r for r in records)
        values = [r.get(p) for r in records]
        errors = 0
        cast = cast_map.get(p)
        if cast:
            if (cast.to == "datetime") != (cast.format is not None):
                raise AnalyticsError("DATA_CAST_UNSUPPORTED")
            if cast.on_error == "null" and not limits.allow_null_cast:
                raise AnalyticsError("ACCESS_DENIED")
            if types[p] in ("object", "array"):
                raise AnalyticsError("DATA_FIELD_NOT_SCALAR")
            for j, value in enumerate(values):
                if value is not None:
                    try:
                        values[j] = cast_value(value, cast.to, cast.format)
                    except (ValueError, TypeError, OverflowError, OSError):
                        if cast.on_error == "reject":
                            raise AnalyticsError("DATA_CAST_FAILED") from None
                        values[j] = None
                        errors += 1
            types[p] = {"int64": "integer", "float64": "float"}.get(cast.to, cast.to)
        if types[p] == "mixed" and p not in cast_map:
            # Presence/null diagnostics are allowed on mixed fields, typed use is not.
            typed_use = (
                any(g.field == p for g in query.group_by)
                or any(
                    getattr(a, "field", None) == p and a.op not in {"missing_count", "null_count"}
                    for a in query.aggregations
                )
                or any(getattr(n, "field", None) == p and n.op not in NULL_OPS for n in nodes)
            )
            if typed_use:
                raise AnalyticsError("DATA_FIELD_TYPE_CONFLICT")
        # Complex and mixed values only need presence and null flags for diagnostics.
        stored = tuple(
            None if isinstance(v, (dict, list)) or types[p] == "mixed" else v for v in values
        )
        columns[f"v{i}"] = stored
        columns[f"p{i}"] = present
        columns[f"n{i}"] = tuple(
            exists and value is None for exists, value in zip(present, values, strict=True)
        )
        quality[p] = {
            "present": sum(present),
            "missing": len(values) - sum(present),
            "null": sum(columns[f"n{i}"]),
            "valid": sum(v is not None for v in values),
            "cast_errors": errors,
        }
    for predicate in predicates:
        check_predicate(predicate, types, limits=limits)
    for a in query.aggregations:
        if not hasattr(a, "field"):
            continue
        t = types[a.field]
        if a.op not in ("missing_count", "null_count") and t in ("object", "array"):
            raise AnalyticsError("DATA_FIELD_NOT_SCALAR")
        if a.op in NUMERIC_OPS and t not in ("integer", "float", "null"):
            raise AnalyticsError("QUERY_OPERATOR_TYPE")
        if a.op in NUMERIC_OPS - {"sum", "sum_if"} and t == "integer":
            samples = columns[f"v{sorted(fields).index(a.field)}"]
            if any(v is not None and abs(v) > 2**53 for v in samples):
                raise AnalyticsError("QUERY_OPERATOR_TYPE")
        if a.op in ("min", "max") and t == "boolean":
            raise AnalyticsError("QUERY_OPERATOR_TYPE")
        if a.op == "count_distinct":
            distinct_values = columns[f"v{sorted(fields).index(a.field)}"]
            if len(set(distinct_values) - {None}) > limits.max_distinct:
                raise AnalyticsError("QUERY_TOO_EXPENSIVE")
    group_keys = []
    for g in query.group_by:
        if types[g.field] in ("object", "array"):
            raise AnalyticsError("QUERY_GROUP_INVALID")
        i = sorted(fields).index(g.field)
        group_keys.append(list(zip(columns[f"v{i}"], columns[f"p{i}"], strict=True)))
    groups = len(set(zip(*group_keys, strict=True))) if group_keys else 1
    if groups > limits.max_groups:
        raise AnalyticsError("RESOURCE_GROUPS_LIMIT")
    start = end = None
    if query.time_range:
        if types[query.time_range.field] != "datetime":
            raise AnalyticsError("DATA_TIMESTAMP_INVALID")
        try:
            if isinstance(query.time_range, RelativeTime):
                end = now.astimezone(UTC)
                start = end - timedelta(minutes=query.time_range.last_minutes)
            else:
                start, end = timestamp(query.time_range.start), timestamp(query.time_range.end)
            if start >= end or end - start > timedelta(days=1):
                raise ValueError
        except ValueError:
            raise AnalyticsError("QUERY_TIME_RANGE_INVALID") from None
    size = step = windows = 0
    if query.window:
        size = INTERVALS.get(query.window.size, 0)
        step = INTERVALS.get(getattr(query.window, "step", query.window.size), 0)
        if (
            start is None
            or end is None
            or not size
            or not step
            or step > size
            or size % step
            or size // step > 12
        ):
            raise AnalyticsError("QUERY_WINDOW_INVALID")
        windows = math.ceil((end - start).total_seconds() / step) + size // step
        if windows > limits.max_windows:
            raise AnalyticsError("RESOURCE_WINDOWS_LIMIT")
        if (
            groups * windows > limits.max_groups
            or snapshot.row_count * (size // step) > limits.max_expanded_rows
        ):
            raise AnalyticsError("QUERY_TOO_EXPENSIVE")
    if query.options.include_empty_windows and (not query.window or query.group_by):
        raise AnalyticsError("QUERY_EMPTY_WINDOW_UNSUPPORTED")
    result_types = {g.alias: types[g.field] for g in query.group_by}
    for a in query.aggregations:
        result_types[a.alias] = (
            "integer"
            if a.op
            in {
                "count",
                "count_non_null",
                "null_count",
                "missing_count",
                "count_distinct",
                "count_if",
            }
            else types[a.field]
            if a.op in ("min", "max", "sum", "sum_if")
            else "float"
        )
    if query.window:
        result_types.update(window_start="datetime", window_end="datetime")
    for h in query.having:
        check_predicate(h, result_types, having=True)
    if any(o.field not in result_types for o in query.order_by):
        raise AnalyticsError("QUERY_ORDER_INVALID")
    encoded = query.model_dump_json(by_alias=True, exclude_unset=True)
    result_plan = LogicalPlan(
        "analytics.plan/v1",
        encoded,
        hashlib.sha256(encoded.encode()).hexdigest(),
        tuple(sorted(fields)),
        tuple(sorted(types.items())),
        tuple(columns.items()),
        json.dumps(quality),
        start,
        end,
        size,
        step,
        groups,
        windows,
        snapshot.row_count,
    )
    if has_matching or details.include:
        from xp_libs_analytics.engine.backend import matching_cost

        cost = matching_cost(result_plan, limits)
        cost["requires_isolation"] = cost["requires_isolation"] or details.include
        result_plan = replace(
            result_plan,
            matching_cost_json=json.dumps(cost),
            diagnostic_key=hashlib.sha256(snapshot.handle.id.encode()).digest(),
        )
    return result_plan
