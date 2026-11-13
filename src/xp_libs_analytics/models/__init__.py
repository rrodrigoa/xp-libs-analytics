"""Strict immutable, versioned normalized AST."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, ValidationError

from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.matching.models import (
    FuzzyPredicate,
    MatchFieldsPredicate,
    MatchingDetails,
    Normalization,
    StringPredicate,
)
from xp_libs_analytics.policy import Limits

Scalar = bool | int | float | str | None
LEAF_OPS = (
    "eq ne gt gte lt lte in not_in between is_null is_not_null "
    "is_missing is_present contains starts_with ends_with"
).split()
LEGACY_FILTER_OPS = LEAF_OPS + ["and", "or", "not"]
FILTER_OPS = LEGACY_FILTER_OPS + [
    "not_contains",
    "word",
    "like",
    "ilike",
    "regex",
    "fuzzy",
    "match",
]
AGG_OPS = (
    "count count_non_null null_count missing_count count_distinct sum avg min max "
    "median p50 p90 p95 p99 stddev variance count_if sum_if avg_if ratio_if"
).split()
HAVING_OPS = "eq ne gt gte lt lte between is_null is_not_null and or not".split()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, populate_by_name=False)


class PredicateBase(StrictModel):
    pass


class Eq(PredicateBase):
    op: Literal["eq"]
    field: str
    value: Scalar
    normalization: Normalization | None = None


class Ne(PredicateBase):
    op: Literal["ne"]
    field: str
    value: Scalar
    normalization: Normalization | None = None


class Gt(PredicateBase):
    op: Literal["gt"]
    field: str
    value: Scalar


class Gte(PredicateBase):
    op: Literal["gte"]
    field: str
    value: Scalar


class Lt(PredicateBase):
    op: Literal["lt"]
    field: str
    value: Scalar


class Lte(PredicateBase):
    op: Literal["lte"]
    field: str
    value: Scalar


class In(PredicateBase):
    op: Literal["in"]
    field: str
    values: list[Scalar] = Field(min_length=1, max_length=20)


class NotIn(PredicateBase):
    op: Literal["not_in"]
    field: str
    values: list[Scalar] = Field(min_length=1, max_length=20)


class Between(PredicateBase):
    op: Literal["between"]
    field: str
    lower: Scalar
    upper: Scalar


class IsNull(PredicateBase):
    op: Literal["is_null"]
    field: str


class IsNotNull(PredicateBase):
    op: Literal["is_not_null"]
    field: str


class IsMissing(PredicateBase):
    op: Literal["is_missing"]
    field: str


class IsPresent(PredicateBase):
    op: Literal["is_present"]
    field: str


class Contains(PredicateBase):
    op: Literal["contains"]
    field: str
    value: Scalar
    normalization: Normalization | None = None


class StartsWith(PredicateBase):
    op: Literal["starts_with"]
    field: str
    value: Scalar
    normalization: Normalization | None = None


class EndsWith(PredicateBase):
    op: Literal["ends_with"]
    field: str
    value: Scalar
    normalization: Normalization | None = None


class And(PredicateBase):
    op: Literal["and"]
    conditions: list[Predicate] = Field(min_length=2, max_length=32)


class Or(PredicateBase):
    op: Literal["or"]
    conditions: list[Predicate] = Field(min_length=2, max_length=32)


class Not(PredicateBase):
    op: Literal["not"]
    condition: Predicate


SinglePredicate: TypeAlias = Annotated[
    Eq
    | Ne
    | Gt
    | Gte
    | Lt
    | Lte
    | In
    | NotIn
    | Between
    | IsNull
    | IsNotNull
    | IsMissing
    | IsPresent
    | Contains
    | StartsWith
    | EndsWith
    | StringPredicate
    | FuzzyPredicate
    | And
    | Or
    | Not,
    Field(discriminator="op"),
]


def predicate_tag(value: object) -> str:
    return (
        "match"
        if isinstance(value, MatchFieldsPredicate) or isinstance(value, dict) and "match" in value
        else "single"
    )


Predicate: TypeAlias = Annotated[
    Annotated[SinglePredicate, Tag("single")] | Annotated[MatchFieldsPredicate, Tag("match")],
    Discriminator(predicate_tag),
]


Eq.model_rebuild()
Ne.model_rebuild()
Gt.model_rebuild()
Gte.model_rebuild()
Lt.model_rebuild()
Lte.model_rebuild()
In.model_rebuild()
NotIn.model_rebuild()
Between.model_rebuild()
IsNull.model_rebuild()
IsNotNull.model_rebuild()
IsMissing.model_rebuild()
IsPresent.model_rebuild()
Contains.model_rebuild()
StartsWith.model_rebuild()
EndsWith.model_rebuild()
And.model_rebuild()
Or.model_rebuild()
Not.model_rebuild()


class HavingPredicateBase(StrictModel):
    pass


class HavingEq(HavingPredicateBase):
    op: Literal["eq"]
    field: str
    value: Scalar


class HavingNe(HavingPredicateBase):
    op: Literal["ne"]
    field: str
    value: Scalar


class HavingGt(HavingPredicateBase):
    op: Literal["gt"]
    field: str
    value: Scalar


class HavingGte(HavingPredicateBase):
    op: Literal["gte"]
    field: str
    value: Scalar


class HavingLt(HavingPredicateBase):
    op: Literal["lt"]
    field: str
    value: Scalar


class HavingLte(HavingPredicateBase):
    op: Literal["lte"]
    field: str
    value: Scalar


class HavingBetween(HavingPredicateBase):
    op: Literal["between"]
    field: str
    lower: Scalar
    upper: Scalar


class HavingIsNull(HavingPredicateBase):
    op: Literal["is_null"]
    field: str


class HavingIsNotNull(HavingPredicateBase):
    op: Literal["is_not_null"]
    field: str


class HavingAnd(HavingPredicateBase):
    op: Literal["and"]
    conditions: list[HavingPredicate] = Field(min_length=2, max_length=32)


class HavingOr(HavingPredicateBase):
    op: Literal["or"]
    conditions: list[HavingPredicate] = Field(min_length=2, max_length=32)


class HavingNot(HavingPredicateBase):
    op: Literal["not"]
    condition: HavingPredicate


HavingPredicate: TypeAlias = Annotated[
    HavingEq
    | HavingNe
    | HavingGt
    | HavingGte
    | HavingLt
    | HavingLte
    | HavingBetween
    | HavingIsNull
    | HavingIsNotNull
    | HavingAnd
    | HavingOr
    | HavingNot,
    Field(discriminator="op"),
]

HavingEq.model_rebuild()
HavingNe.model_rebuild()
HavingGt.model_rebuild()
HavingGte.model_rebuild()
HavingLt.model_rebuild()
HavingLte.model_rebuild()
HavingBetween.model_rebuild()
HavingIsNull.model_rebuild()
HavingIsNotNull.model_rebuild()
HavingAnd.model_rebuild()
HavingOr.model_rebuild()
HavingNot.model_rebuild()


class CountAggregate(StrictModel):
    op: Literal["count"]
    alias: str = Field(alias="as")


class CountNonNullAggregate(StrictModel):
    op: Literal["count_non_null"]
    alias: str = Field(alias="as")
    field: str


class NullCountAggregate(StrictModel):
    op: Literal["null_count"]
    alias: str = Field(alias="as")
    field: str


class MissingCountAggregate(StrictModel):
    op: Literal["missing_count"]
    alias: str = Field(alias="as")
    field: str


class CountDistinctAggregate(StrictModel):
    op: Literal["count_distinct"]
    alias: str = Field(alias="as")
    field: str


class SumAggregate(StrictModel):
    op: Literal["sum"]
    alias: str = Field(alias="as")
    field: str


class AvgAggregate(StrictModel):
    op: Literal["avg"]
    alias: str = Field(alias="as")
    field: str


class MinAggregate(StrictModel):
    op: Literal["min"]
    alias: str = Field(alias="as")
    field: str


class MaxAggregate(StrictModel):
    op: Literal["max"]
    alias: str = Field(alias="as")
    field: str


class MedianAggregate(StrictModel):
    op: Literal["median"]
    alias: str = Field(alias="as")
    field: str


class P50Aggregate(StrictModel):
    op: Literal["p50"]
    alias: str = Field(alias="as")
    field: str


class P90Aggregate(StrictModel):
    op: Literal["p90"]
    alias: str = Field(alias="as")
    field: str


class P95Aggregate(StrictModel):
    op: Literal["p95"]
    alias: str = Field(alias="as")
    field: str


class P99Aggregate(StrictModel):
    op: Literal["p99"]
    alias: str = Field(alias="as")
    field: str


class StddevAggregate(StrictModel):
    op: Literal["stddev"]
    alias: str = Field(alias="as")
    field: str


class VarianceAggregate(StrictModel):
    op: Literal["variance"]
    alias: str = Field(alias="as")
    field: str


class CountIfAggregate(StrictModel):
    op: Literal["count_if"]
    alias: str = Field(alias="as")
    where: Predicate


class SumIfAggregate(StrictModel):
    op: Literal["sum_if"]
    alias: str = Field(alias="as")
    field: str
    where: Predicate


class AvgIfAggregate(StrictModel):
    op: Literal["avg_if"]
    alias: str = Field(alias="as")
    field: str
    where: Predicate


class RatioIfAggregate(StrictModel):
    op: Literal["ratio_if"]
    alias: str = Field(alias="as")
    field: str
    where: Predicate


Aggregate: TypeAlias = Annotated[
    CountAggregate
    | CountNonNullAggregate
    | NullCountAggregate
    | MissingCountAggregate
    | CountDistinctAggregate
    | SumAggregate
    | AvgAggregate
    | MinAggregate
    | MaxAggregate
    | MedianAggregate
    | P50Aggregate
    | P90Aggregate
    | P95Aggregate
    | P99Aggregate
    | StddevAggregate
    | VarianceAggregate
    | CountIfAggregate
    | SumIfAggregate
    | AvgIfAggregate
    | RatioIfAggregate,
    Field(discriminator="op"),
]


class Dataset(StrictModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")


class Cast(StrictModel):
    field: str
    to: Literal["float64", "int64", "string", "datetime"]
    on_error: Literal["reject", "null"]
    format: Literal["rfc3339", "epoch_s", "epoch_ms", "epoch_us"] | None = None


class AbsoluteTime(StrictModel):
    field: str
    start: str
    end: str


class RelativeTime(StrictModel):
    field: str
    last_minutes: int = Field(ge=1, le=1440)


class Tumbling(StrictModel):
    type: Literal["tumbling"]
    size: str


class Sliding(StrictModel):
    type: Literal["sliding"]
    size: str
    step: str


class Group(StrictModel):
    field: str
    alias: str = Field(alias="as")


class Order(StrictModel):
    field: str
    direction: Literal["asc", "desc"] = "asc"
    nulls: Literal["first", "last"] = "last"


class Options(StrictModel):
    include_empty_windows: bool = False
    matching_details: MatchingDetails = Field(default_factory=MatchingDetails)


class AnalyticsQuery(StrictModel):
    version: Literal["analytics.query/v1"]
    dataset: Dataset
    casts: list[Cast] = Field(default_factory=list, max_length=8)
    time_range: AbsoluteTime | RelativeTime | None = None
    filters: list[Predicate] = Field(default_factory=list, max_length=20)
    window: Annotated[Tumbling | Sliding, Field(discriminator="type")] | None = None
    group_by: list[Group] = Field(default_factory=list, max_length=4)
    aggregations: list[Aggregate] = Field(min_length=1, max_length=20)
    having: list[HavingPredicate] = Field(default_factory=list, max_length=10)
    order_by: list[Order] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=100, ge=1, le=500)
    options: Options = Field(default_factory=Options)


def parse_query(text: str, limits: Limits) -> AnalyticsQuery:
    from xp_libs_analytics.parser import parse_yaml

    marks: dict[str, tuple[int, int]] = {}
    data = parse_yaml(text, limits, source_marks=marks)
    if data.get("version") != "analytics.query/v1":
        raise AnalyticsError("QUERY_VERSION_UNSUPPORTED", "$.version")
    if set(data) & {
        "entity_inference",
        "entity_resolution",
        "resolve_entities",
        "identities",
        "aliases",
    }:
        raise AnalyticsError("MATCH_ENTITY_INFERENCE_UNSUPPORTED")
    if set(data) & {"sources", "joins", "unions", "outputs", "continuous", "sinks"}:
        raise AnalyticsError("QUERY_UNSUPPORTED_FEATURE")
    try:
        return AnalyticsQuery.model_validate(data)
    except ValidationError as exc:
        issue = exc.errors(include_input=False)[0]
        loc = issue["loc"]
        code = "QUERY_MALFORMED"
        if loc and loc[0] == "having":
            code = "QUERY_HAVING_INVALID"
        elif "algorithm" in loc:
            code = "MATCH_FUZZY_ALGORITHM_INVALID"
        elif "min_score" in loc:
            code = "MATCH_FUZZY_THRESHOLD_INVALID"
        elif "normalization" in loc:
            code = "MATCH_NORMALIZATION_INVALID"
        elif issue["type"] == "string_too_short" and "value" in loc:
            code = "MATCH_FUZZY_QUERY_TOO_SHORT" if "fuzzy" in loc else "MATCH_PATTERN_INVALID"
        elif issue["type"] == "union_tag_invalid":
            code = "QUERY_UNKNOWN_OPERATOR"
        elif loc and loc[0] in {"time_range", "window", "order_by", "group_by", "having", "limit"}:
            code = {
                "time_range": "QUERY_TIME_RANGE_INVALID",
                "window": "QUERY_WINDOW_INVALID",
                "order_by": "QUERY_ORDER_INVALID",
                "group_by": "QUERY_GROUP_INVALID",
                "having": "QUERY_HAVING_INVALID",
                "limit": "QUERY_LIMIT_INVALID",
            }[loc[0]]
        model_keys = {
            "version",
            "dataset",
            "name",
            "casts",
            "field",
            "to",
            "format",
            "on_error",
            "time_range",
            "start",
            "end",
            "last_minutes",
            "filters",
            "op",
            "value",
            "values",
            "lower",
            "upper",
            "conditions",
            "condition",
            "window",
            "type",
            "size",
            "step",
            "group_by",
            "as",
            "aggregations",
            "where",
            "having",
            "order_by",
            "direction",
            "nulls",
            "limit",
            "options",
            "match",
            "fields",
            "patterns",
            "mode",
            "normalization",
            "case_sensitive",
            "unicode",
            "trim",
            "algorithm",
            "min_score",
            "matching_details",
            "include",
            "top_values",
            "include_raw_values",
            "include_empty_windows",
        }
        segments = [
            v
            for v in loc
            if v
            not in set(
                FILTER_OPS
                + AGG_OPS
                + [
                    "single",
                    "LiteralRule",
                    "FuzzyRule",
                    "AbsoluteTime",
                    "RelativeTime",
                    "tumbling",
                    "sliding",
                ]
            )
        ]
        actual = "$" + "".join(f"[{v}]" if isinstance(v, int) else "." + str(v) for v in segments)
        path = "$" + "".join(
            f"[{v}]" if isinstance(v, int) else "." + (v if v in model_keys else "?")
            for v in segments
        )
        line, column = marks.get(actual, marks.get("$", (1, 1)))
        raise AnalyticsError(code, path, line=line, column=column) from None
