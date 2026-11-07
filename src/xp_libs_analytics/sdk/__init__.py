"""Headless Python API; identity is supplied by the trusted application."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from xp_libs_analytics.engine.planner import LogicalPlan, plan_query
from xp_libs_analytics.errors import CATALOG, AnalyticsError
from xp_libs_analytics.ingest import DatasetStore, Snapshot, utc_now
from xp_libs_analytics.models import AGG_OPS, FILTER_OPS, AnalyticsQuery, parse_query
from xp_libs_analytics.policy import Limits, Principal
from xp_libs_analytics.registry import DatasetInfo, DatasetRegistry


class AnalyticsEngine:
    def __init__(
        self,
        *,
        limits: Limits | None = None,
        principal: Principal | None = None,
        store: DatasetStore | None = None,
        clock: Callable[[], datetime] = utc_now,
        isolated: bool = False,
        telemetry: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.limits = limits or Limits()
        self.principal = principal or Principal()
        self.store = store or DatasetStore(self.limits)
        self.registry = DatasetRegistry(self.store, lambda: self.principal, lambda: self.clock())
        self.clock = clock
        self.isolated = isolated
        self.telemetry = telemetry
        request_budget = self.store.request_budget(self.principal)
        self._slots = request_budget.slots
        self._calls = request_budget.calls
        self._quota_lock = request_budget.lock

    def register_records(self, name: str, records: Any, *, ndjson: bool = False) -> DatasetInfo:
        return self.registry.register_records(name, records, ndjson=ndjson)

    def replace_records(
        self,
        name: str,
        records: Any,
        *,
        ndjson: bool = False,
        expected_revision: int | None = None,
    ) -> DatasetInfo:
        return self.registry.replace_records(
            name, records, ndjson=ndjson, expected_revision=expected_revision
        )

    def describe(self, name: str) -> dict[str, Any]:
        return self.registry.describe(name)

    def list_datasets(self) -> list[dict[str, Any]]:
        return self.registry.list_datasets()

    def unregister_dataset(self, name: str, *, expected_revision: int | None = None) -> None:
        self.registry.unregister_dataset(name, expected_revision=expected_revision)

    def register_stream(self, name: str, source: Any) -> None:
        """Reserved seam; V1 cannot admit or execute continuous sources."""
        raise AnalyticsError("QUERY_UNSUPPORTED_FEATURE")

    def create_context(self) -> AnalyticsEngine:
        """Create an independent namespace with shared host resource/owner budgets."""
        return AnalyticsEngine(
            limits=self.limits,
            principal=self.principal,
            store=self.store,
            clock=self.clock,
            isolated=self.isolated,
            telemetry=self.telemetry,
        )

    def _authorized_view(self, principal: Principal) -> AnalyticsEngine:
        if principal.id != self.principal.id:
            raise AnalyticsError("ACCESS_DENIED")
        view = AnalyticsEngine(
            limits=self.limits,
            principal=principal,
            store=self.store,
            clock=self.clock,
            isolated=self.isolated,
            telemetry=self.telemetry,
        )
        view.registry = DatasetRegistry(
            self.store,
            lambda: view.principal,
            lambda: view.clock(),
            namespace=self.registry._namespace,
        )
        return view

    def close(self) -> None:
        self.registry.close()

    def __enter__(self) -> AnalyticsEngine:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def capabilities(self) -> dict[str, Any]:
        from dataclasses import asdict

        return {
            "version": "analytics.query/v1",
            "authoring_format": "yaml",
            "mode": "snapshot",
            "filters": FILTER_OPS,
            "matching": {
                "algorithms": ["ratio", "wratio", "token_sort"],
                "normalization": {
                    "case_sensitive": True,
                    "unicode": ["none", "nfc", "nfkc"],
                    "trim": False,
                },
                "diagnostics": "options.matching_details",
                "reference": "analytics://string-matching/v1",
                "entity_inference": False,
            },
            "aggregations": AGG_OPS,
            "limits": asdict(self.limits),
            "schema": AnalyticsQuery.model_json_schema(),
            "execution_isolated": self.isolated,
        }

    @contextmanager
    def _prepare(self, text: str) -> Iterator[tuple[LogicalPlan, Snapshot, datetime]]:
        query = parse_query(text, self.limits)
        with self.registry.snapshot(query.dataset.name) as snapshot:
            now = self.clock()
            yield plan_query(query, snapshot, self.principal, self.limits, now), snapshot, now

    def validate_query(self, query_yaml: str) -> dict[str, Any]:
        return self.explain_query(query_yaml)

    def explain_query(self, query_yaml: str) -> dict[str, Any]:
        try:
            self._take_quota()
            with self._prepare(query_yaml) as (plan, snapshot, _):
                return {
                    "status": "OK",
                    "plan": plan.explain(),
                    "dataset": {
                        "name": json.loads(plan.query_json)["dataset"]["name"],
                        "revision": snapshot.handle.revision,
                    },
                }
        except AnalyticsError as exc:
            return exc.envelope()
        except Exception:
            return AnalyticsError("INTERNAL_ERROR").envelope()

    def _take_quota(self) -> None:
        with self._quota_lock:
            now = monotonic()
            while self._calls and self._calls[0] < now - 60:
                self._calls.popleft()
            if len(self._calls) >= self.limits.max_queries_per_minute:
                raise AnalyticsError("QUERY_TOO_EXPENSIVE")
            self._calls.append(now)

    def query_yaml(self, query_yaml: str) -> dict[str, Any]:
        query_id = uuid4().hex
        started = monotonic()
        event: dict[str, Any] = {
            "query_id": query_id,
            "event": "query",
            "principal_hash": hashlib.sha256(self.principal.id.encode()).hexdigest(),
            "outcome": "ERROR",
        }
        acquired = False
        try:
            self._take_quota()
            acquired = self._slots.acquire(blocking=False)
            if not acquired:
                raise AnalyticsError("RESOURCE_CONCURRENCY_LIMIT")
            with self._prepare(query_yaml) as (plan, snapshot, now):
                event["plan_fingerprint"] = plan.fingerprint
                event["snapshot_id"] = snapshot.handle.id
                event["snapshot_revision"] = snapshot.handle.revision
                if (
                    self.isolated
                    or self.limits.force_matching_isolation
                    and json.loads(plan.matching_cost_json).get("requires_isolation")
                ):
                    from xp_libs_analytics.engine.worker import execute_isolated

                    result = execute_isolated(plan, self.limits)
                else:
                    from xp_libs_analytics.engine.backend import execute_plan

                    result = execute_plan(plan, self.limits)
                result.update(
                    version="analytics.result/v1",
                    query_id=query_id,
                    dataset={
                        "name": json.loads(plan.query_json)["dataset"]["name"],
                        "revision": snapshot.handle.revision,
                    },
                )
                if result["status"] != "ERROR":
                    result["evidence"].update(
                        schema_revision=snapshot.handle.revision,
                        source_kind=snapshot.source_kind,
                        computed_at=now.isoformat().replace("+00:00", "Z"),
                    )
                if (
                    len(json.dumps(result, allow_nan=False).encode("utf-8"))
                    > self.limits.max_result_bytes
                ):
                    raise AnalyticsError("RESOURCE_RESULT_LIMIT")
                event["outcome"] = result["status"]
                if result["status"] == "ERROR":
                    event["error_code"] = result["error"]["code"]
                return result
        except AnalyticsError as exc:
            event["error_code"] = exc.code.value
            return exc.envelope(query_id)
        except Exception:
            event["error_code"] = "EXECUTION_BACKEND_ERROR"
            return AnalyticsError("EXECUTION_BACKEND_ERROR").envelope(query_id)
        finally:
            if acquired:
                self._slots.release()
            if self.telemetry is not None:
                event["duration_seconds"] = monotonic() - started
                try:
                    self.telemetry(event)
                except Exception:  # noqa: S110 -- do not log sensitive host hook exceptions
                    # A host observability outage cannot alter analytical results.
                    pass

    def query_file(self, path: Path) -> dict[str, Any]:
        if path.suffix.lower() not in (".yaml", ".yml"):
            return AnalyticsError("QUERY_MALFORMED").envelope()
        try:
            with path.open("rb") as stream:
                text = stream.read(self.limits.max_query_bytes + 1).decode("utf-8")
            return self.query_yaml(text)
        except (OSError, UnicodeError):
            return AnalyticsError("QUERY_YAML_INVALID").envelope()

    @staticmethod
    def error_info(code: str) -> dict[str, Any]:
        if code not in CATALOG:
            return AnalyticsError("MCP_INVALID_TOOL_CALL").envelope()
        return {"code": code, "message": CATALOG[code]}
