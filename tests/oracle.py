"""Independent plain Python semantics; never imports the implementation or Polars."""

import math
import operator
import statistics

MISSING = object()


def lookup(row, pointer):
    value = row
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            return MISSING
        value = value[token]
    return value


def predicate(row, node):
    op = node["op"]
    if op in ("and", "or"):
        values = [predicate(row, c) for c in node["conditions"]]
        if op == "and":
            return False if False in values else None if None in values else True
        return True if True in values else None if None in values else False
    if op == "not":
        v = predicate(row, node["condition"])
        return None if v is None else not v
    value = lookup(row, node["field"])
    absent = value is MISSING
    null = absent or value is None
    if op == "is_missing":
        return absent
    if op == "is_present":
        return not absent
    if op == "is_null":
        return null
    if op == "is_not_null":
        return not null
    if null:
        return None
    if op in ("in", "not_in"):
        found = value in [v for v in node["values"] if v is not None]
        result = True if found else None if None in node["values"] else False
        return (None if result is None else not result) if op == "not_in" else result
    if op == "between":
        return node["lower"] <= value <= node["upper"]
    other = node["value"]
    if other is None:
        return None
    if op in ("eq", "ne", "gt", "gte", "lt", "lte"):
        return {
            "eq": operator.eq,
            "ne": operator.ne,
            "gt": operator.gt,
            "gte": operator.ge,
            "lt": operator.lt,
            "lte": operator.le,
        }[op](value, other)
    if op == "contains":
        return other in value
    if op == "starts_with":
        return value.startswith(other)
    return value.endswith(other)


def aggregate(rows, agg):
    op = agg["op"]
    if op == "count":
        return len(rows)
    if op == "count_if":
        return sum(predicate(r, agg["where"]) is True for r in rows)
    raw = [lookup(r, agg["field"]) for r in rows]
    values = [v for v in raw if v is not MISSING and v is not None]
    if op == "count_non_null":
        return len(values)
    if op == "null_count":
        return sum(v is None for v in raw)
    if op == "missing_count":
        return sum(v is MISSING for v in raw)
    if op == "count_distinct":
        return len(set(values))
    if op == "ratio_if":
        numerator = sum(
            v is not MISSING and v is not None and predicate(r, agg["where"]) is True
            for r, v in zip(rows, raw, strict=True)
        )
        return numerator / len(values) if values else None
    if op.endswith("_if"):
        values = [
            v
            for r, v in zip(rows, raw, strict=True)
            if v is not MISSING and v is not None and predicate(r, agg["where"]) is True
        ]
    if not values:
        return None
    if op in ("sum", "sum_if"):
        return sum(values)
    if op in ("avg", "avg_if"):
        return statistics.mean(values)
    if op == "min":
        return min(values)
    if op == "max":
        return max(values)
    if op in ("stddev", "variance"):
        return (
            (statistics.stdev(values) if op == "stddev" else statistics.variance(values))
            if len(values) > 1
            else None
        )
    q = {"median": 0.5, "p50": 0.5, "p90": 0.9, "p95": 0.95, "p99": 0.99}[op]
    ordered = sorted(values)
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)
