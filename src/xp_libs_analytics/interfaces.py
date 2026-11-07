"""Versioned extension seams. V1 executes exactly one snapshot and JSON sink."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from xp_libs_analytics.engine.planner import LogicalPlan
from xp_libs_analytics.policy import Limits, Principal


@dataclass(frozen=True)
class SourceDescriptor:
    source_id: str
    origin: str
    owner: str
    schema_hash: str
    redacted: bool = False


@dataclass(frozen=True)
class InputPort:
    source_ref: str
    mode: Literal["snapshot"] = "snapshot"
    schema_revision: int = 1
    watermark_capability: bool = False


@dataclass(frozen=True)
class OutputPort:
    sink_ref: str = "json-response"
    format: Literal["json"] = "json"
    delivery_semantics: Literal["request"] = "request"


@dataclass(frozen=True)
class QueryDefinition:
    id: str
    plan: LogicalPlan


@dataclass(frozen=True)
class QueryExecution:
    id: str
    definition_id: str
    state: Literal["CREATED", "RUNNING", "STOPPING", "STOPPED", "FAILED"]


class DataSource(Protocol):
    def read(self, request: Any, principal: Principal, budget: Limits) -> Any: ...


class ResultSink(Protocol):
    def write(self, envelope: dict[str, Any], principal: Principal) -> dict[str, Any]: ...


class InlineJsonSource:
    def read(self, request: Any, principal: Principal, budget: Limits) -> Any:
        from xp_libs_analytics.ingest import admit

        return admit(request, budget)[0]


class InMemoryObjectSource(InlineJsonSource):
    pass


class JsonResultSink:
    def write(self, envelope: dict[str, Any], principal: Principal) -> dict[str, Any]:
        import json

        return cast(dict[str, Any], json.loads(json.dumps(envelope, allow_nan=False)))
