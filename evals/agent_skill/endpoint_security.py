"""Runtime-only connection settings and fail-closed report redaction."""

from __future__ import annotations

import contextlib
import io
import json
import logging
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import unquote, urlsplit


class PrivacyError(ValueError):
    pass


def validate_endpoint(endpoint: str) -> str:
    url = urlsplit(endpoint)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise PrivacyError("Provide an HTTP(S) API base URL without credentials, query or fragment")
    return endpoint.rstrip("/")


class PrivacyGuard:
    def __init__(self, endpoint: str, credential: str = "") -> None:
        self.endpoint = validate_endpoint(endpoint)
        url = urlsplit(self.endpoint)
        self.secrets = tuple(
            sorted(
                {s for s in (self.endpoint, url.netloc, url.hostname, credential) if s},
                key=len,
                reverse=True,
            )
        )

    def sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(k): "[REDACTED]"
                if re.search(
                    r"endpoint|base.?url|api.?key|authorization|password|headers|credential",
                    str(k),
                    re.I,
                )
                else self.sanitize(v)
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.sanitize(v) for v in value]
        if isinstance(value, str):
            value = unquote(value)
            for secret in self.secrets:
                value = value.replace(secret, "[REDACTED]")
            return re.sub(r"https?://[^\s\"'<>]+", "[REDACTED_URL]", value)
        return value

    def assert_safe(self, value: Any) -> None:
        text = unquote(json.dumps(value, ensure_ascii=False))
        if any(s in text for s in self.secrets) or re.search(r"https?://", text):
            raise PrivacyError("Refusing to persist sensitive runtime connection details")


@contextlib.contextmanager
def private_execution() -> Iterator[None]:
    """Inspect uses a memory-only JSON recorder, with realtime disk spool disabled.

    Suppress library console errors as well: provider exceptions may contain URLs.
    Native messages/traces remain in memory until allowlisted, sanitized export.
    """
    previous = logging.root.manager.disable
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        logging.disable(logging.CRITICAL)
        try:
            yield
        finally:
            logging.disable(previous)
