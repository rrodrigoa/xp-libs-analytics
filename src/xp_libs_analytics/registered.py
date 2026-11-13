"""Host-authored registered query definitions and bounded parameter validation."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.models import AnalyticsQuery
from xp_libs_analytics.policy import Limits


def parameter_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    if schema.get("type") != "object":
        raise ValueError("Registered queries require an object parameter model")
    return {**schema, "additionalProperties": False}


def validate_parameters(
    model: type[BaseModel], parameters: Mapping[str, Any] | None, limits: Limits
) -> tuple[BaseModel, bytes]:
    remaining = limits.max_yaml_nodes

    def check(value: Any, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > limits.max_yaml_depth:
            raise AnalyticsError("QUERY_PARAMETERS_LIMIT")
        if isinstance(value, dict):
            if len(value) > limits.max_collection_items:
                raise AnalyticsError("QUERY_PARAMETERS_LIMIT")
            for key, item in value.items():
                if type(key) is not str:
                    raise AnalyticsError("QUERY_PARAMETERS_INVALID")
                check(key, depth + 1)
                check(item, depth + 1)
        elif isinstance(value, list):
            if len(value) > limits.max_collection_items:
                raise AnalyticsError("QUERY_PARAMETERS_LIMIT")
            for item in value:
                check(item, depth + 1)
        elif type(value) is str:
            if len(value) > limits.max_scalar_chars:
                raise AnalyticsError("QUERY_PARAMETERS_LIMIT")
            value.encode("utf-8")
        elif type(value) is int:
            if not -(2**63) <= value < 2**63:
                raise AnalyticsError("QUERY_PARAMETERS_INVALID")
        elif type(value) is float:
            if not math.isfinite(value):
                raise AnalyticsError("QUERY_PARAMETERS_INVALID")
        elif value is not None and type(value) is not bool:
            raise AnalyticsError("QUERY_PARAMETERS_INVALID")

    def encode(value: dict[str, Any]) -> bytes:
        check(value, 0)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > limits.max_query_bytes:
            raise AnalyticsError("QUERY_PARAMETERS_LIMIT")
        return encoded

    try:
        if parameters is not None and not isinstance(parameters, Mapping):
            raise AnalyticsError("QUERY_PARAMETERS_INVALID")
        raw = encode(dict(parameters) if parameters is not None else {})
        validated = model.model_validate_json(raw, strict=True, extra="forbid")
        # Check effective defaults as well as the supplied JSON.
        remaining = limits.max_yaml_nodes
        encode(validated.model_dump(mode="json", by_alias=True, round_trip=True, warnings="error"))
        return validated, raw
    except (ValidationError, PydanticSerializationError, ValueError, TypeError, RecursionError):
        raise AnalyticsError("QUERY_PARAMETERS_INVALID") from None


@dataclass(frozen=True)
class ParameterizedYamlQuery:
    """Restricted YAML with whole-value {$param: name} placeholders."""

    yaml: str
    parameters: type[BaseModel]

    def __post_init__(self) -> None:
        parameter_schema(self.parameters)

    def bind(self, parameters: Mapping[str, Any] | None, limits: Limits) -> AnalyticsQuery:
        from xp_libs_analytics.parser import parse_yaml

        validated, _ = validate_parameters(self.parameters, parameters, limits)
        values = validated.model_dump(mode="json")
        document = parse_yaml(self.yaml, limits)

        def bind_node(node: Any, path: tuple[str, ...] = ()) -> Any:
            if isinstance(node, dict):
                if "$param" in node:
                    name = node["$param"]
                    if (
                        len(node) != 1
                        or type(name) is not str
                        or name not in values
                        or not _value_slot(path)
                    ):
                        raise AnalyticsError("QUERY_PARAMETER_BINDING_INVALID")
                    return values[name]
                return {key: bind_node(value, (*path, key)) for key, value in node.items()}
            if isinstance(node, list):
                return [bind_node(value, (*path, "[]")) for value in node]
            return node

        try:
            return AnalyticsQuery.model_validate(bind_node(document), strict=True)
        except ValidationError:
            raise AnalyticsError("QUERY_PARAMETER_BINDING_INVALID") from None


def _value_slot(path: tuple[str, ...]) -> bool:
    if path in {("time_range", "start"), ("time_range", "end"), ("time_range", "last_minutes")}:
        return True
    if len(path) < 3 or path[1] != "[]":
        return False
    root, _, *parts = path
    if root == "aggregations":
        if not parts or parts.pop(0) != "where":
            return False
    elif root not in {"filters", "having"}:
        return False
    while parts and parts[0] in {"conditions", "condition"}:
        parts = parts[2:] if parts[:2] == ["conditions", "[]"] else parts[1:]
    return tuple(parts) in {
        ("value",),
        ("values",),
        ("values", "[]"),
        ("lower",),
        ("upper",),
        ("min_score",),
        ("match", "patterns", "[]", "value"),
        ("match", "patterns", "[]", "min_score"),
    }
