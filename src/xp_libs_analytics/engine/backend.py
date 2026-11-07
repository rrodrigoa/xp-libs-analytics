"""Fixed factories only: no SQL, expressions from text, callbacks or UDFs."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from functools import reduce
from typing import Any, cast

import polars as pl

from xp_libs_analytics.engine.planner import LogicalPlan, timestamp
from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.matching.compiler import MatchingCompiler, RuleUse, prepare
from xp_libs_analytics.matching.diagnostics import matching_evidence
from xp_libs_analytics.matching.models import is_matching
from xp_libs_analytics.models import AnalyticsQuery, HavingPredicate, Predicate
from xp_libs_analytics.policy import Limits

DTYPES: dict[str, Any] = {
    "integer": pl.Int64,
    "float": pl.Float64,
    "string": pl.String,
    "boolean": pl.Boolean,
    "datetime": pl.Datetime("us", "UTC"),
    "null": pl.Null,
    "mixed": pl.Null,
    "object": pl.Null,
    "array": pl.Null,
}


def predicate_expr(
    node: Predicate | HavingPredicate,
    columns: Mapping[str, tuple[str, str | None, str | None]],
    types: dict[str, str],
    matcher: MatchingCompiler | None = None,
) -> pl.Expr:
    op = node.op
    if op in ("and", "or"):
        exprs = [predicate_expr(c, columns, types, matcher) for c in getattr(node, "conditions")]
        return reduce(lambda a, b: a & b if op == "and" else a | b, exprs)
    if op == "not":
        return ~predicate_expr(getattr(node, "condition"), columns, types, matcher)
    if matcher is not None and is_matching(node, types):
        return matcher.predicate(node)
    value_col, presence_col, null_col = columns[getattr(node, "field")]
    col = pl.col(value_col)
    if op == "is_missing":
        return ~pl.col(cast(str, presence_col))
    if op == "is_present":
        return pl.col(cast(str, presence_col))
    if op in ("is_null", "is_not_null"):
        expr = (pl.col(null_col) | ~pl.col(cast(str, presence_col))) if null_col else col.is_null()
        return expr if op == "is_null" else ~expr

    def literal(v: Any) -> Any:
        return timestamp(v) if types[getattr(node, "field")] == "datetime" and v is not None else v

    if op in ("in", "not_in"):
        # Null in a membership list propagates unknown for an unmatched value.
        values = [literal(v) for v in getattr(node, "values") if v is not None]
        expr = col.is_in(values)
        if None in getattr(node, "values"):
            expr = pl.when(expr).then(True).otherwise(None)
        expr = pl.when(col.is_null()).then(None).otherwise(expr)
        return ~expr if op == "not_in" else expr
    if op == "between":
        return col.is_between(
            literal(getattr(node, "lower")), literal(getattr(node, "upper")), closed="both"
        )
    v = literal(getattr(node, "value"))
    if op == "eq":
        return col == pl.lit(v)
    if op == "ne":
        return col != pl.lit(v)
    if op == "gt":
        return col > pl.lit(v)
    if op == "gte":
        return col >= pl.lit(v)
    if op == "lt":
        return col < pl.lit(v)
    if op == "lte":
        return col <= pl.lit(v)
    # String source predicates are compiled only by the shared matching layer.
    raise AnalyticsError("QUERY_OPERATOR_TYPE")


def aggregate_expr(
    a: Any,
    columns: Mapping[str, tuple[str, str | None, str | None]],
    types: dict[str, str],
    matcher: MatchingCompiler | None = None,
) -> pl.Expr:
    op = a.op
    if op == "count":
        return pl.len().cast(pl.Int64)
    if op == "count_if":
        return (
            predicate_expr(a.where, columns, types, matcher).fill_null(False).cast(pl.Int64).sum()
        )
    value_col, present_col, null_col = columns[a.field]
    col = pl.col(value_col)
    if op == "missing_count":
        return (~pl.col(cast(str, present_col))).cast(pl.Int64).sum()
    if op == "null_count":
        return pl.col(cast(str, null_col)).cast(pl.Int64).sum()
    if op == "count_non_null":
        return col.count().cast(pl.Int64)
    if op == "count_distinct":
        return col.drop_nulls().n_unique().cast(pl.Int64)
    if op == "ratio_if":
        numerator = (
            (predicate_expr(a.where, columns, types, matcher).fill_null(False) & col.is_not_null())
            .cast(pl.Int64)
            .sum()
        )
        return pl.when(col.count() > 0).then(numerator / col.count()).otherwise(None)
    if op in ("sum_if", "avg_if"):
        col = col.filter(predicate_expr(a.where, columns, types, matcher).fill_null(False))
    if op in ("sum", "sum_if"):
        numeric = col.cast(pl.Int128) if types[a.field] == "integer" else col.cast(pl.Float64)
        return pl.when(col.count() > 0).then(numeric.sum()).otherwise(None)
    if op in ("avg", "avg_if"):
        return col.cast(pl.Float64).mean()
    if op == "min":
        return col.min()
    if op == "max":
        return col.max()
    if op == "stddev":
        return col.cast(pl.Float64).std(ddof=1)
    if op == "variance":
        return col.cast(pl.Float64).var(ddof=1)
    q = {"median": 0.5, "p50": 0.5, "p90": 0.9, "p95": 0.95, "p99": 0.99}[op]
    return col.cast(pl.Float64).quantile(q, interpolation="linear")


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if type(value) is float and not math.isfinite(value):
        raise AnalyticsError("EXECUTION_BACKEND_ERROR")
    if type(value) is int and not -(2**63) <= value < 2**63:
        raise AnalyticsError("EXECUTION_BACKEND_ERROR")
    return value


def execute_plan(plan: LogicalPlan, limits: Limits) -> dict[str, Any]:
    query = AnalyticsQuery.model_validate_json(plan.query_json)
    frame, columns, types = frame_for(plan)
    if query.time_range:
        frame = frame.filter(
            pl.col(columns[query.time_range.field][0]).is_between(
                plan.start, plan.end, closed="left"
            )
        )
    rules: list[RuleUse] = []
    matcher = None
    if json.loads(plan.matching_cost_json).get("used") or query.options.matching_details.include:
        frame, matcher, rules = prepare(
            query, frame, columns, types, limits, predicate_expr, score=True
        )
    for predicate in query.filters:
        frame = frame.filter(predicate_expr(predicate, columns, types, matcher))
    matching = (
        matching_evidence(
            frame,
            matcher,
            rules,
            include=query.options.matching_details.include,
            top_values=query.options.matching_details.top_values,
            raw=query.options.matching_details.include_raw_values,
            key=plan.diagnostic_key,
        )
        if matcher
        else None
    )
    matched = frame.height
    group_cols = []
    rename = {}
    for i, g in enumerate(query.group_by):
        v, p, _ = columns[g.field]
        frame = frame.with_columns(pl.col(v).alias(f"_g{i}"), pl.col(p).alias(f"_gp{i}"))
        group_cols.extend([f"_g{i}", f"_gp{i}"])
        rename[f"_g{i}"] = g.alias
    if query.window:
        if query.time_range is None:
            raise AnalyticsError("QUERY_WINDOW_INVALID")
        time_col = pl.col(columns[query.time_range.field][0]).dt.epoch("us")
        step = plan.window_step * 1_000_000
        size = plan.window_size * 1_000_000
        aligned = (time_col // step) * step
        frame = frame.with_columns(
            pl.int_ranges(aligned - size + step, aligned + step, step).alias("_ws")
        )
        frame = frame.explode("_ws")
        frame = frame.with_columns(pl.col("_ws").cast(pl.Datetime("us", "UTC")))
        group_cols = ["_ws"] + group_cols
        rename["_ws"] = "window_start"
    agg_exprs = [
        aggregate_expr(a, columns, types, matcher).alias(f"_a{i}")
        for i, a in enumerate(query.aggregations)
    ]
    rename.update({f"_a{i}": a.alias for i, a in enumerate(query.aggregations)})
    if group_cols:
        result = frame.group_by(group_cols).agg(agg_exprs)
    else:
        result = frame.select(agg_exprs)
    if query.options.include_empty_windows:
        if plan.start is None or plan.end is None:
            raise AnalyticsError("QUERY_WINDOW_INVALID")
        step = plan.window_step
        first = math.floor(plan.start.timestamp() / step) * step - plan.window_size + step
        last = math.ceil(plan.end.timestamp() / step) * step
        grid = pl.DataFrame(
            {
                "_ws": pl.Series(
                    [datetime.fromtimestamp(s, UTC) for s in range(first, last, step)],
                    dtype=pl.Datetime("us", "UTC"),
                )
            }
        )
        result = grid.join(result, on="_ws", how="left")
        counts = [
            f"_a{i}"
            for i, a in enumerate(query.aggregations)
            if a.op.startswith("count") or a.op in ("null_count", "missing_count")
        ]
        if counts:
            result = result.with_columns(pl.col(counts).fill_null(0))
    for i, _ in enumerate(query.aggregations):
        metric_series = result[f"_a{i}"]
        if metric_series.dtype == pl.Int128:
            if any(
                v is not None and not -(2**63) <= cast(int, v) < 2**63
                for v in (metric_series.min(), metric_series.max())
            ):
                raise AnalyticsError("EXECUTION_BACKEND_ERROR")
        if metric_series.dtype.is_float() and not metric_series.is_finite().fill_null(True).all():
            raise AnalyticsError("EXECUTION_BACKEND_ERROR")
    result = result.rename(rename)
    if query.window:
        result = result.with_columns(
            (pl.col("window_start") + timedelta(seconds=plan.window_size)).alias("window_end")
        )
    if result.height > limits.max_groups:
        raise AnalyticsError("RESOURCE_GROUPS_LIMIT")
    result_columns = {name: (name, None, None) for name in result.columns}
    result_types = {
        name: (
            "datetime"
            if dtype.base_type() == pl.Datetime
            else "float"
            if dtype.is_float()
            else "integer"
            if dtype.is_integer()
            else "boolean"
            if dtype == pl.Boolean
            else "string"
        )
        for name, dtype in result.schema.items()
    }
    for h in query.having:
        result = result.filter(predicate_expr(h, result_columns, result_types))
    implicit = (
        (["window_start"] if query.window else [])
        + [g.alias for g in query.group_by]
        + [f"_gp{i}" for i in range(len(query.group_by))]
    )
    if implicit:
        result = result.sort(implicit, nulls_last=True, maintain_order=True)
    for order in reversed(query.order_by):
        result = result.sort(
            order.field,
            descending=order.direction == "desc",
            nulls_last=order.nulls == "last",
            maintain_order=True,
        )
    truncated = result.height > query.limit
    result = result.head(query.limit)
    rows = result.to_dicts()
    for row in rows:
        if query.group_by:
            row["group_key_status"] = {
                g.alias: "missing"
                if not row.pop(f"_gp{i}")
                else "null"
                if row[g.alias] is None
                else "present"
                for i, g in enumerate(query.group_by)
            }
    public_columns = [
        {
            "name": name,
            "type": (
                "int64"
                if dtype.is_integer()
                else "float64"
                if dtype.is_float()
                else "datetime"
                if dtype.base_type() == pl.Datetime
                else "boolean"
                if dtype == pl.Boolean
                else "string"
                if dtype == pl.String
                else "null"
            ),
        }
        for name, dtype in result.schema.items()
        if not name.startswith("_gp") or name in {g.alias for g in query.group_by}
    ]
    quality = json.loads(plan.quality_json)
    partial = bool(
        query.window
        and any(row["window_start"] < plan.start or row["window_end"] > plan.end for row in rows)
    )
    return cast(
        dict[str, Any],
        json_safe(
            {
                "status": "NO_DATA"
                if matched == 0
                else "INSUFFICIENT_DATA"
                if matched < limits.min_samples
                else "OK",
                "columns": public_columns,
                "rows": rows,
                "truncated": truncated,
                "evidence": {
                    "input_rows": plan.input_rows,
                    "matched_rows": matched,
                    "resolved_time_range": {"start": plan.start, "end": plan.end}
                    if plan.start
                    else None,
                    "field_quality": quality,
                    "coverage": "UNKNOWN",
                    "partial_boundary_windows": partial,
                },
                **({"matching": matching} if matching is not None else {}),
                "warnings": ["DATA_CAST_FAILED"]
                if any(q["cast_errors"] for q in quality.values())
                else [],
                "error": None,
            }
        ),
    )


def frame_for(
    plan: LogicalPlan,
) -> tuple[pl.DataFrame, dict[str, tuple[str, str, str]], dict[str, str]]:
    types = dict(plan.types)
    columns = {p: (f"v{i}", f"p{i}", f"n{i}") for i, p in enumerate(plan.fields)}
    series = []
    for name, values in plan.columns:
        dtype = DTYPES[types[plan.fields[int(name[1:])]]] if name[0] == "v" else pl.Boolean
        series.append(pl.Series(name, values, dtype=dtype))
    series.append(pl.Series("_row", range(plan.input_rows), dtype=pl.Int64))
    frame = pl.DataFrame(series)
    return frame, columns, types


def matching_cost(plan: LogicalPlan, limits: Limits) -> dict[str, Any]:
    query = AnalyticsQuery.model_validate_json(plan.query_json)
    frame, columns, types = frame_for(plan)
    if query.time_range:
        frame = frame.filter(
            pl.col(columns[query.time_range.field][0]).is_between(
                plan.start, plan.end, closed="left"
            )
        )
    _, matcher, rules = prepare(query, frame, columns, types, limits, predicate_expr, score=False)
    return matcher.cost(rules)
