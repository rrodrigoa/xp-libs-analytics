"""Context-local logical sources, atomic publication and pinned immutable snapshots."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.ingest import DatasetHandle, DatasetStore, Snapshot
from xp_libs_analytics.policy import Principal


class SnapshotSource(Protocol):
    """Trusted source binding; execution consumes snapshots, never DataFrames or user code."""

    @property
    def handle(self) -> DatasetHandle: ...

    @property
    def expires(self) -> datetime: ...

    @property
    def mode(self) -> Literal["snapshot"]: ...


@dataclass(frozen=True)
class RecordsSnapshotSource:
    handle: DatasetHandle
    expires: datetime
    mode: Literal["snapshot"] = "snapshot"


@dataclass(frozen=True)
class DatasetInfo:
    """Public binding metadata; opaque IDs remain internal."""

    name: str
    revision: int


def validate_name(name: str) -> None:
    if type(name) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name):
        raise AnalyticsError("DATASET_NAME_INVALID")


class _Namespace:
    def __init__(self, owner: str) -> None:
        self.bindings: dict[str, SnapshotSource] = {}
        self.lock = threading.RLock()
        self.closed = False
        self.owner = owner
        self.generation = 0


class DatasetRegistry:
    """A bounded namespace owned by one execution context, never a global name table."""

    def __init__(
        self,
        store: DatasetStore,
        principal: Callable[[], Principal],
        clock: Callable[[], datetime],
        *,
        namespace: _Namespace | None = None,
    ) -> None:
        self._store, self._principal, self._clock = store, principal, clock
        self._namespace = namespace or _Namespace(principal().id)
        self._bindings = self._namespace.bindings
        self._lock = self._namespace.lock

    def _check(self, scope: str) -> Principal:
        principal = self._principal()
        if (
            self._namespace.closed
            or scope not in principal.scopes
            or principal.id != self._namespace.owner
        ):
            raise AnalyticsError("ACCESS_DENIED")
        return principal

    def _source(self, name: str, revision: int | None = None) -> SnapshotSource:
        validate_name(name)
        source = self._bindings.get(name)
        if source is None:
            # A foreign context's name is indistinguishable from an unknown name.
            raise AnalyticsError("DATASET_NAME_UNKNOWN")
        if revision is not None and (
            type(revision) is not int or revision != source.handle.revision
        ):
            raise AnalyticsError("DATASET_SNAPSHOT_STALE")
        return source

    def _publish(
        self,
        name: str,
        records: Any,
        *,
        replace: bool,
        ndjson: bool,
        expected_revision: int | None = None,
    ) -> DatasetInfo:
        validate_name(name)
        with self._lock:
            principal = self._check("upload")
            old = self._source(name, expected_revision) if replace else None
            if not replace and name in self._bindings:
                raise AnalyticsError("DATASET_NAME_DUPLICATE")
            if not replace and len(self._bindings) >= self._store.limits.max_datasets:
                raise AnalyticsError("RESOURCE_DATASETS_LIMIT")
            now = self._clock()
            revision = self._namespace.generation + 1
            handle = self._store.register(
                records,
                principal,
                now,
                ndjson=ndjson,
                replaces=old.handle if old else None,
                revision=revision,
            )
            snapshot = self._store.get_snapshot(handle, principal, now)
            self._namespace.generation = revision
            self._bindings[name] = RecordsSnapshotSource(handle, snapshot.expires)
            return DatasetInfo(name, revision)

    def register_records(self, name: str, records: Any, *, ndjson: bool = False) -> DatasetInfo:
        return self._publish(name, records, replace=False, ndjson=ndjson)

    def replace_records(
        self,
        name: str,
        records: Any,
        *,
        ndjson: bool = False,
        expected_revision: int | None = None,
    ) -> DatasetInfo:
        return self._publish(
            name, records, replace=True, ndjson=ndjson, expected_revision=expected_revision
        )

    @contextmanager
    def snapshot(self, name: str, *, revision: int | None = None) -> Iterator[Snapshot]:
        with self._lock:
            principal = self._check("read")
            source = self._source(name, revision)
            now = self._clock()
            if source.expires <= now:
                raise AnalyticsError("DATASET_SNAPSHOT_STALE")
            snapshot = self._store.acquire(source.handle, principal, now)
        try:
            yield snapshot
        finally:
            self._store.unpin(source.handle)

    def names(self) -> list[str]:
        with self._lock:
            self._check("read")
            return sorted(self._bindings)

    def describe(self, name: str) -> dict[str, Any]:
        with self.snapshot(name) as snapshot:
            principal = self._check("read")
            return {
                "name": name,
                "revision": snapshot.handle.revision,
                "records": snapshot.row_count,
                "source_kind": snapshot.source_kind,
                "mode": "snapshot",
                "expires": snapshot.expires.isoformat(),
                "fields": {
                    p: info for p, info in snapshot.schema().items() if principal.permits(p)
                },
            }

    def list_datasets(self) -> list[dict[str, Any]]:
        datasets = []
        for name in self.names():
            try:
                datasets.append(self.describe(name))
            except AnalyticsError as exc:
                if exc.code not in {"DATASET_NAME_UNKNOWN", "DATASET_SNAPSHOT_STALE"}:
                    raise
        return datasets

    def unregister_dataset(self, name: str, *, expected_revision: int | None = None) -> None:
        with self._lock:
            self._check("release")
            source = self._source(name, expected_revision)
            # Expired bindings can still be removed. No query can resolve them again.
            with self._store._lock:
                self._store._retire(source.handle.id)
            del self._bindings[name]

    def close(self) -> None:
        with self._lock:
            for source in self._bindings.values():
                with self._store._lock:
                    self._store._retire(source.handle.id)
            self._bindings.clear()
            self._namespace.closed = True
