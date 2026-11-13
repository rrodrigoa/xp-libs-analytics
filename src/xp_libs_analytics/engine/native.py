"""Execution of host-owned Polars transformations over authorized projections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from inspect import isfunction
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel

from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.ingest import Snapshot, flatten, pointer_tokens
from xp_libs_analytics.policy import Limits, Principal
from xp_libs_analytics.registered import parameter_schema, validate_parameters
from xp_libs_analytics.registry import validate_name

if TYPE_CHECKING:
    from polars import DataFrame

type PolarsTransform = Callable[[DataFrame, BaseModel], DataFrame]
type ColumnType = Literal["integer", "float", "boolean", "string", "datetime", "null"]
_OUTPUT_TYPES = {"integer", "float", "boolean", "string", "datetime", "null"}
_INPUT_TYPES = _OUTPUT_TYPES - {"datetime"}


@dataclass(frozen=True)
class PolarsQuery:
    dataset: str
    fields: tuple[str, ...]
    transform: PolarsTransform
    parameters: type[BaseModel]
    output_schema: Mapping[str, ColumnType]
    max_output_rows: int = 100

    def __post_init__(self) -> None:
        validate_name(self.dataset)
        fields = tuple(self.fields)
        if len(fields) != len(set(fields)):
            raise ValueError("Duplicate projected field")
        for path in fields:
            pointer_tokens(path, max_depth=256)
        schema = dict(self.output_schema)
        if not schema or any(
            type(name) is not str or not name or kind not in _OUTPUT_TYPES
            for name, kind in schema.items()
        ):
            raise ValueError("Invalid Polars output schema")
        if not callable(self.transform) or type(self.max_output_rows) is not int:
            raise ValueError("Invalid Polars query configuration")
        if self.max_output_rows < 1:
            raise ValueError("Output row limit must be positive")
        parameter_schema(self.parameters)
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "output_schema", MappingProxyType(schema))


@dataclass(frozen=True)
class NativePlan:
    projection: tuple[tuple[str, str, tuple[Any, ...], tuple[bool, ...]], ...]
    input_rows: int
    output_schema: tuple[tuple[str, ColumnType], ...]
    max_output_rows: int


def prepare_native(
    query: PolarsQuery, snapshot: Snapshot, principal: Principal, limits: Limits
) -> NativePlan:
    if (
        len(query.fields) > limits.max_columns
        or len(query.output_schema) > limits.max_columns
        or snapshot.row_count > limits.max_rows
        or snapshot.byte_count > limits.max_bytes
        or snapshot.row_count * max(1, len(query.fields)) > limits.max_expanded_rows
    ):
        raise AnalyticsError("QUERY_TOO_EXPENSIVE")
    schema = snapshot.schema()
    for field in query.fields:
        pointer_tokens(field, limits.max_depth)
        if not principal.permits(field) or principal.fields is not None and field not in schema:
            raise AnalyticsError("ACCESS_FIELD_DENIED")
        if field not in schema:
            raise AnalyticsError("DATA_FIELD_UNKNOWN")
        # A container can include descendants that the caller cannot read.
        if schema[field]["type"] not in _INPUT_TYPES:
            raise AnalyticsError("QUERY_NATIVE_INPUT_INVALID")
    projected: dict[str, tuple[list[Any], list[bool]]] = {field: ([], []) for field in query.fields}
    for record in snapshot.records():
        flat = flatten(record)
        for field, (values, presence) in projected.items():
            values.append(flat.get(field))
            presence.append(field in flat)
    return NativePlan(
        tuple(
            (field, schema[field]["type"], tuple(values), tuple(presence))
            for field, (values, presence) in projected.items()
        ),
        snapshot.row_count,
        tuple(query.output_schema.items()),
        query.max_output_rows,
    )


def native_fingerprint(query: PolarsQuery) -> str:
    definition = (
        query.dataset,
        query.fields,
        tuple(query.output_schema.items()),
        query.max_output_rows,
        getattr(query.transform, "__module__", ""),
        getattr(query.transform, "__qualname__", type(query.transform).__qualname__),
    )
    return hashlib.sha256(json.dumps(definition).encode()).hexdigest()


def execute_native(
    plan: NativePlan, transform: PolarsTransform, parameters: BaseModel, limits: Limits
) -> dict[str, Any]:
    import polars as pl

    from xp_libs_analytics.engine.backend import json_safe

    dtypes = {
        "integer": pl.Int64,
        "float": pl.Float64,
        "boolean": pl.Boolean,
        "string": pl.String,
        "null": pl.Null,
    }
    # The row index preserves cardinality even for a zero-column projection.
    columns = [pl.Series("row_index", range(plan.input_rows), dtype=pl.Int64)]
    for path, kind, values, presence in plan.projection:
        columns.append(pl.Series(path, values, dtype=dtypes[kind]))
        columns.append(pl.Series("present:" + path, presence, dtype=pl.Boolean))
    result = transform(pl.DataFrame(columns), parameters)
    if not isinstance(result, pl.DataFrame) or result.columns != [
        name for name, _ in plan.output_schema
    ]:
        raise AnalyticsError("QUERY_NATIVE_RESULT_INVALID")
    for dtype, (_, kind) in zip(result.dtypes, plan.output_schema, strict=True):
        if kind == "datetime":
            valid = isinstance(dtype, pl.Datetime) and dtype.time_zone is not None
        else:
            valid = dtype == dtypes[kind]
        if not valid:
            raise AnalyticsError("QUERY_NATIVE_RESULT_INVALID")
    if result.height > plan.max_output_rows:
        raise AnalyticsError("RESOURCE_RESULT_LIMIT")

    rows = []
    size = 0
    for row in result.iter_rows(named=True):
        try:
            encoded = json_safe(row)
            size += len(json.dumps(encoded, allow_nan=False).encode("utf-8"))
        except (AnalyticsError, TypeError, ValueError):
            raise AnalyticsError("QUERY_NATIVE_RESULT_INVALID") from None
        if size > limits.max_result_bytes:
            raise AnalyticsError("RESOURCE_RESULT_LIMIT")
        rows.append(encoded)
    return {
        "status": "NO_DATA" if not rows else "OK",
        "columns": [{"name": name, "type": kind} for name, kind in plan.output_schema],
        "rows": rows,
        "truncated": False,
        "evidence": {"input_rows": plan.input_rows, "coverage": "UNKNOWN"},
        "warnings": [],
        "error": None,
    }


def import_reference(value: Any) -> tuple[str, str]:
    module, name = getattr(value, "__module__", ""), getattr(value, "__qualname__", "")
    if module in {"", "__main__", "__mp_main__"} or not name.isidentifier():
        raise ValueError("Isolated definitions must be declared in an importable module")
    if getattr(import_module(module), name, None) is not value:
        raise ValueError("Isolated definition does not match its module binding")
    return module, name


@dataclass(frozen=True)
class NativeWorkerRequest:
    plan: NativePlan
    transform: tuple[str, str]
    model: tuple[str, str]
    parameters_json: bytes

    def execute(self, limits: Limits) -> dict[str, Any]:
        transform = getattr(import_module(self.transform[0]), self.transform[1])
        model = getattr(import_module(self.model[0]), self.model[1])
        if (
            not isfunction(transform)
            or not isinstance(model, type)
            or not issubclass(model, BaseModel)
        ):
            raise AnalyticsError("QUERY_NATIVE_ISOLATION_INVALID")
        parameters, _ = validate_parameters(model, json.loads(self.parameters_json), limits)
        return execute_native(self.plan, cast(PolarsTransform, transform), parameters, limits)
