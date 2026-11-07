"""Canonical, privacy-preserving public errors."""

import json
from importlib.resources import files
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from xp_libs_analytics.errors.codes import ErrorCode

CATALOG = MappingProxyType(json.loads(files(__package__).joinpath("catalog.json").read_text()))

RETRYABLE = frozenset(
    {
        "MCP_UNAVAILABLE",
        "RESOURCE_CONCURRENCY_LIMIT",
        "RESOURCE_TIMEOUT",
        "EXECUTION_BACKEND_ERROR",
        "EXECUTION_CANCELLED",
    }
)


class AnalyticsError(Exception):
    def __init__(self, code: str, path: str = "$", **details: Any) -> None:
        self.code = ErrorCode(code)
        self.path = path
        self.details = details
        super().__init__(CATALOG[code])

    def envelope(self, query_id: str | None = None) -> dict[str, Any]:
        return {
            "version": "analytics.result/v1",
            "query_id": query_id or uuid4().hex,
            "status": "ERROR",
            "error": {
                "code": self.code.value,
                "message": CATALOG[self.code],
                "path": self.path,
                "retryable": self.code in RETRYABLE,
                "details": self.details,
            },
        }
