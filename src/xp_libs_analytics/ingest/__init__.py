"""Bounded JSON admission, schema discovery and owner-scoped snapshots."""

from __future__ import annotations

import json
import math
import re
import secrets
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.policy import Limits, Principal, RequestBudget


def pointer_tokens(path: str, max_depth: int = 12) -> list[str]:
    if not path.startswith("/") or re.search(r"~(?![01])", path):
        raise AnalyticsError("QUERY_INVALID_POINTER")
    tokens = path[1:].split("/")
    if len(tokens) > max_depth:
        raise AnalyticsError("QUERY_INVALID_POINTER")
    return [t.replace("~1", "/").replace("~0", "~") for t in tokens]


def kind(value: Any) -> str:
    return {
        type(None): "null",
        bool: "boolean",
        int: "integer",
        float: "float",
        str: "string",
        dict: "object",
        list: "array",
        datetime: "datetime",
    }[type(value)]


def reject_constant(_: str) -> Any:
    raise AnalyticsError("INPUT_INVALID_NUMBER")


def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AnalyticsError("INPUT_DUPLICATE_KEY")
        result[key] = value
    return result


def loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=pairs_hook, parse_constant=reject_constant)


def admit(data: Any, limits: Limits, *, ndjson: bool = False) -> tuple[list[dict[str, Any]], int]:
    if isinstance(data, bytes):
        if len(data) > limits.max_bytes:
            raise AnalyticsError("INPUT_BYTES_LIMIT")
        try:
            data = data.decode("utf-8")
        except UnicodeError:
            raise AnalyticsError("INPUT_INVALID_UTF8") from None
    if isinstance(data, str):
        try:
            if len(data.encode("utf-8")) > limits.max_bytes:
                raise AnalyticsError("INPUT_BYTES_LIMIT")
            if ndjson:
                data = [loads(line) for line in data.splitlines() if line.strip()]
            else:
                try:
                    data = loads(data)
                except json.JSONDecodeError as exc:
                    if exc.msg == "Extra data" and "\n" in data:
                        return admit(data, limits, ndjson=True)
                    raise
        except UnicodeError:
            raise AnalyticsError("INPUT_INVALID_UTF8") from None
        except (ValueError, RecursionError):
            raise AnalyticsError(
                "INPUT_INVALID_NDJSON" if ndjson else "INPUT_INVALID_JSON"
            ) from None
    if isinstance(data, Mapping):
        data = [data]
    if not isinstance(data, Iterable) or isinstance(data, (str, bytes)):
        raise AnalyticsError("INPUT_UNSUPPORTED_ROOT")
    fields: set[str] = set()
    record_units = [0]

    def check(value: Any, depth: int, path: str, ancestors: set[int]) -> Any:
        record_units[0] += len(value) if type(value) is str else 1
        if record_units[0] > limits.max_record_bytes:
            raise AnalyticsError("INPUT_RECORD_TOO_LARGE")
        if depth > limits.max_depth:
            raise AnalyticsError("INPUT_TOO_DEEP")
        if type(value) in (dict, list) or isinstance(value, Mapping):
            if id(value) in ancestors:
                raise AnalyticsError("INPUT_TOO_DEEP")
            chain = ancestors | {id(value)}
            if isinstance(value, Mapping):
                result = {}
                for k, v in value.items():
                    if type(k) is not str:
                        raise AnalyticsError("INPUT_UNSUPPORTED_ROOT")
                    p = path + "/" + k.replace("~", "~0").replace("/", "~1")
                    fields.add(p)
                    if len(fields) > limits.max_columns:
                        raise AnalyticsError("INPUT_TOO_WIDE")
                    result[k] = check(v, depth + 1, p, chain)
                return result
            return [check(v, depth + 1, path, chain) for v in value]
        if type(value) is float and not math.isfinite(value):
            raise AnalyticsError("INPUT_INVALID_NUMBER")
        if type(value) is int and not -(2**63) <= value < 2**63:
            raise AnalyticsError("INPUT_INVALID_NUMBER")
        if type(value) is str:
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise AnalyticsError("INPUT_INVALID_UTF8") from None
        elif type(value) not in (int, float, bool, type(None)):
            raise AnalyticsError("INPUT_UNSUPPORTED_ROOT")
        return value

    rows: list[dict[str, Any]] = []
    total = 0
    for row in data:
        record_units[0] = 0
        if len(rows) >= limits.max_rows:
            raise AnalyticsError("INPUT_ROWS_LIMIT")
        if not isinstance(row, Mapping):
            raise AnalyticsError("INPUT_INVALID_NDJSON" if ndjson else "INPUT_UNSUPPORTED_ROOT")
        copied = check(row, 0, "", set())
        size = len(json.dumps(copied, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if size > limits.max_record_bytes:
            raise AnalyticsError("INPUT_RECORD_TOO_LARGE")
        total += size
        if total > limits.max_bytes:
            raise AnalyticsError("INPUT_BYTES_LIMIT")
        rows.append(copied)
    return rows, total


def flatten(record: dict[str, Any], path: str = "") -> dict[str, Any]:
    result = {}
    for key, value in record.items():
        p = path + "/" + key.replace("~", "~0").replace("/", "~1")
        result[p] = value
        if isinstance(value, dict):
            result.update(flatten(value, p))
    return result


@dataclass(frozen=True)
class DatasetHandle:
    id: str
    revision: int = 1


@dataclass(frozen=True)
class Snapshot:
    handle: DatasetHandle
    owner: str
    created: datetime
    expires: datetime
    payload: str
    schema_json: str
    row_count: int
    byte_count: int
    source_kind: str

    def records(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], json.loads(self.payload))

    def schema(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.schema_json))


class DatasetStore:
    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self._snapshots: dict[str, Snapshot] = {}
        self._budgets: dict[str, RequestBudget] = {}
        self._readers: dict[str, int] = {}
        self._retired: set[str] = set()
        self._lock = threading.RLock()

    def request_budget(self, principal: Principal) -> RequestBudget:
        with self._lock:
            if principal.id not in self._budgets:
                self._budgets[principal.id] = RequestBudget(self.limits)
            return self._budgets[principal.id]

    def expire(self, now: datetime) -> None:
        with self._lock:
            for ident, snapshot in list(self._snapshots.items()):
                if snapshot.expires <= now:
                    self._retire(ident)

    def _retire(self, ident: str) -> None:
        if self._readers.get(ident, 0):
            self._retired.add(ident)
        else:
            self._snapshots.pop(ident, None)
            self._retired.discard(ident)

    def acquire(self, handle: DatasetHandle, principal: Principal, now: datetime) -> Snapshot:
        with self._lock:
            snapshot = self.get_snapshot(handle, principal, now)
            self._readers[handle.id] = self._readers.get(handle.id, 0) + 1
            return snapshot

    def unpin(self, handle: DatasetHandle) -> None:
        with self._lock:
            count = self._readers[handle.id] - 1
            if count:
                self._readers[handle.id] = count
            else:
                del self._readers[handle.id]
                if handle.id in self._retired:
                    self._retire(handle.id)

    def register(
        self,
        data: Any,
        principal: Principal,
        now: datetime,
        *,
        ndjson: bool = False,
        replaces: DatasetHandle | None = None,
        revision: int = 1,
    ) -> DatasetHandle:
        rows, size = admit(data, self.limits, ndjson=ndjson)
        flat = [flatten(row) for row in rows]
        paths = sorted({p for row in flat for p in row})
        schema = {}
        for p in paths:
            values = [row[p] for row in flat if p in row]
            types = sorted({kind(v) for v in values})
            nonnull = set(types) - {"null"}
            resolved = (
                "float"
                if nonnull == {"integer", "float"}
                else next(iter(nonnull))
                if len(nonnull) == 1
                else "null"
                if not nonnull
                else "mixed"
            )
            if resolved == "float" and any(type(v) is int and abs(v) > 2**53 for v in values):
                raise AnalyticsError("INPUT_INVALID_NUMBER")
            schema[p] = {
                "types": types,
                "type": resolved,
                "present": len(values),
                "null": sum(v is None for v in values),
                "missing": len(rows) - len(values),
            }
        with self._lock:
            self.expire(now)
            old = self._snapshots.get(replaces.id) if replaces else None
            reclaim = old.byte_count if old and not self._readers.get(old.handle.id) else 0
            if (
                size + sum(s.byte_count for s in self._snapshots.values()) - reclaim
                > self.limits.max_total_bytes
            ):
                raise AnalyticsError("RESOURCE_MEMORY_LIMIT")
            if (
                sum(
                    s.owner == principal.id and k not in self._retired
                    for k, s in self._snapshots.items()
                )
                - int(old is not None and old.handle.id not in self._retired)
                >= self.limits.max_datasets
            ):
                raise AnalyticsError("RESOURCE_DATASETS_LIMIT")
            handle = DatasetHandle("ds_" + secrets.token_urlsafe(24), revision)
            self._snapshots[handle.id] = Snapshot(
                handle,
                principal.id,
                now,
                now + timedelta(seconds=self.limits.ttl_seconds),
                json.dumps(rows, ensure_ascii=False),
                json.dumps(schema, sort_keys=True),
                len(rows),
                size,
                "inline_json" if isinstance(data, (str, bytes)) else "in_memory",
            )
            if replaces:
                self._retire(replaces.id)
            return handle

    def get_snapshot(
        self, handle: DatasetHandle | str, principal: Principal, now: datetime
    ) -> Snapshot:
        ident = handle.id if isinstance(handle, DatasetHandle) else handle
        with self._lock:
            snapshot = self._snapshots.get(ident)
            if snapshot is None or snapshot.owner != principal.id:
                raise AnalyticsError("ACCESS_DENIED")
            if snapshot.expires <= now:
                raise AnalyticsError("DATASET_SNAPSHOT_STALE")
            return snapshot


def utc_now() -> datetime:
    return datetime.now(UTC)
