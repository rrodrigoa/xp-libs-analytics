"""MCP tools for YAML queries or host-registered query keys."""

import argparse
import json
import re
import threading
from collections.abc import Callable, Mapping
from functools import wraps
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any, cast
from uuid import uuid4

from xp_libs_analytics import AnalyticsEngine, AnalyticsError, AnalyticsQuery, Limits, Principal
from xp_libs_analytics.ingest import DatasetStore
from xp_libs_analytics.sdk import _validated_query_copy


def _valid_query_key(key: str) -> bool:
    return type(key) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", key) is not None


def _copy_registered_queries(
    queries: Mapping[str, str | AnalyticsQuery],
) -> dict[str, str | AnalyticsQuery]:
    registered: dict[str, str | AnalyticsQuery] = {}
    for key, query in queries.items():
        if not _valid_query_key(key):
            raise ValueError("Invalid registered query key")
        registered[key] = query if isinstance(query, str) else _validated_query_copy(query)
    return registered


def create_server(
    engine: AnalyticsEngine | None = None,
    *,
    uploads: bool = False,
    principal_resolver: Callable[[], Principal] | None = None,
    context_resolver: Callable[[], AnalyticsEngine] | None = None,
    registered_queries: Mapping[str, str | AnalyticsQuery] | None = None,
) -> Any:
    from fastmcp import FastMCP
    from fastmcp.server.dependencies import get_context
    from fastmcp.server.middleware import Middleware
    from fastmcp.tools.base import ToolResult

    if registered_queries is not None and uploads:
        raise ValueError("Uploads are unavailable in key-only mode")
    registered = (
        _copy_registered_queries(registered_queries) if registered_queries is not None else None
    )

    server = FastMCP(
        "Generic Analytics",
        instructions=(
            "Execute host-provided query keys with analytics_query_by_key."
            if registered is not None
            else "Read analytics://skill/generic-analytics. Discover analytics_list_datasets. "
            "Author restricted YAML; describe and validate before querying."
        ),
    )
    limits = engine.limits if engine else Limits()
    store = engine.store if engine else DatasetStore(limits)
    # Default server is stdio/local only. Remote hosts MUST provide an authenticated
    # principal resolver and configure FastMCP's transport authentication.
    if context_resolver is not None and (engine is not None or principal_resolver is not None):
        raise ValueError("Supply a context resolver or an engine/principal resolver")
    if engine is not None and principal_resolver is not None:
        raise ValueError("Use a context resolver to bind authenticated hosted contexts")
    sessions: dict[str, AnalyticsEngine] = {}
    session_lock = threading.Lock()
    launcher_principal = Principal(id="launcher_" + uuid4().hex)

    def service() -> AnalyticsEngine:
        context = get_context()
        if (
            principal_resolver is None
            and context_resolver is None
            and context.transport in ("sse", "streamable-http")
        ):
            raise AnalyticsError("ACCESS_DENIED")
        if context_resolver is not None:
            return context_resolver()
        if engine is not None:
            return engine
        # Modern MCP connections are per-request. Local stdio inherits the
        # launcher's authority; remote identity must come from authenticated hosting.
        principal = principal_resolver() if principal_resolver else launcher_principal
        key = principal.id
        with session_lock:
            if key not in sessions:
                if len(sessions) >= 128:
                    raise AnalyticsError("RESOURCE_CONCURRENCY_LIMIT")
                sessions[key] = AnalyticsEngine(
                    limits=limits, store=store, principal=principal, isolated=True
                )
            return sessions[key]._authorized_view(principal)

    def reply(value: dict[str, Any]) -> ToolResult:
        return ToolResult(structured_content=value, is_error=value.get("status") == "ERROR")

    def guarded(fn: Any) -> Any:
        @wraps(fn)
        def invoke(*args: Any, **kwargs: Any) -> ToolResult:
            try:
                return cast(ToolResult, fn(*args, **kwargs))
            except AnalyticsError as exc:
                return reply(exc.envelope())
            except Exception:
                return reply(AnalyticsError("INTERNAL_ERROR").envelope())

        return invoke

    tool_args = {
        "analytics_capabilities": {},
        "analytics_list_datasets": {},
        "analytics_load_json": {"name": str, "data": str},
        "analytics_describe": {"name": str},
        "analytics_validate_query": {"query_yaml": str},
        "analytics_explain_query": {"query_yaml": str},
        "analytics_query": {"query_yaml": str},
        "analytics_unregister_dataset": {"name": str},
        "analytics_error_info": {"code": str},
    }
    if registered is not None:
        tool_args = {"analytics_query_by_key": {"key": str}, "analytics_error_info": {"code": str}}

    class ErrorBoundary(Middleware):
        async def on_call_tool(self, context: Any, call_next: Any) -> Any:
            try:
                expected = tool_args.get(context.message.name)
                arguments = context.message.arguments or {}
                if (
                    expected is None
                    or set(arguments) != set(expected)
                    or any(type(arguments[k]) is not typ for k, typ in expected.items())
                ):
                    raise AnalyticsError("MCP_INVALID_TOOL_CALL")
                return await call_next(context)
            except AnalyticsError as exc:
                return reply(exc.envelope())
            except Exception:
                return reply(AnalyticsError("INTERNAL_ERROR").envelope())

    server.add_middleware(ErrorBoundary())

    @server.tool
    @guarded
    def analytics_error_info(code: str) -> ToolResult:
        """Look up the exact canonical error message and repair example."""
        return reply(AnalyticsEngine.error_info(code))

    if registered is not None:
        queries = registered

        @server.tool
        @guarded
        def analytics_query_by_key(key: str) -> ToolResult:
            """Execute a registered query in the authorized context."""
            if not _valid_query_key(key):
                raise AnalyticsError("MCP_INVALID_TOOL_CALL")
            current = service()
            query = queries.get(key)
            if query is None:
                raise AnalyticsError("ACCESS_DENIED")
            return reply(
                current.query_yaml(query) if isinstance(query, str) else current.query_typed(query)
            )

        return server

    @server.tool
    @guarded
    def analytics_capabilities() -> ToolResult:
        """Discover YAML AST schema, snapshot operations and host-owned limits."""
        return reply(service().capabilities())

    @server.tool
    @guarded
    def analytics_list_datasets() -> ToolResult:
        """Discover logical dataset names and authorized metadata in this context."""
        return reply({"datasets": service().list_datasets()})

    @server.tool
    @guarded
    def analytics_load_json(name: str, data: str) -> ToolResult:
        """Bind bounded JSON/NDJSON to a unique logical name if uploads are enabled."""
        current = service()
        if not uploads or "upload" not in current.principal.scopes:
            raise AnalyticsError("ACCESS_UPLOAD_DISABLED")
        current.register_records(name, data)
        return reply(current.describe(name))

    @server.tool
    @guarded
    def analytics_describe(name: str) -> ToolResult:
        """Discover authorized JSON Pointer fields and quality; returns no sample values."""
        return reply(service().describe(name))

    @server.tool
    @guarded
    def analytics_validate_query(query_yaml: str) -> ToolResult:
        """Validate one restricted YAML string through typing, authorization and budgets."""
        return reply(service().validate_query(query_yaml))

    @server.tool
    @guarded
    def analytics_explain_query(query_yaml: str) -> ToolResult:
        """Return an approved logical plan and conservative cost without backend execution."""
        return reply(service().explain_query(query_yaml))

    @server.tool
    @guarded
    def analytics_query(query_yaml: str) -> ToolResult:
        """Execute one authorized bounded snapshot query authored as restricted YAML text."""
        return reply(service().query_yaml(query_yaml))

    @server.tool
    @guarded
    def analytics_unregister_dataset(name: str) -> ToolResult:
        """Remove a caller-context binding; running queries retain pinned snapshots."""
        service().unregister_dataset(name)
        return reply({"status": "OK"})

    bundle = files("xp_libs_analytics").joinpath("skills/generic-analytics")
    # Editable installs have resources at the repository root; wheels bundle them.
    if not bundle.joinpath("SKILL.md").is_file():
        from pathlib import Path

        bundle = Path(__file__).resolve().parents[3] / "skills/generic-analytics"
        examples: Traversable = Path(__file__).resolve().parents[3] / "examples/queries"
    else:
        examples = bundle.joinpath("examples/queries")

    @server.resource("analytics://skill/generic-analytics")
    def skill() -> str:
        return bundle.joinpath("SKILL.md").read_text(encoding="utf-8")

    @server.resource("analytics://query-language/v1")
    def language() -> str:
        full = bundle.joinpath("references/query-language-full.md")
        if full.is_file():
            return full.read_text(encoding="utf-8")
        from pathlib import Path

        return (Path(__file__).resolve().parents[3] / "docs/query-language.md").read_text(
            encoding="utf-8"
        )

    allowlist = {p.name: p for p in examples.iterdir() if p.name.endswith(".yaml")}

    @server.resource("analytics://examples/index")
    def example_index() -> str:
        return json.dumps(sorted(allowlist))

    @server.resource("analytics://string-matching/v1")
    def matching_language() -> str:
        full = bundle.joinpath("references/string-matching-full.md")
        if full.is_file():
            return full.read_text(encoding="utf-8")
        from pathlib import Path

        return (Path(__file__).resolve().parents[3] / "docs/string-matching.md").read_text(
            encoding="utf-8"
        )

    for name, path in allowlist.items():

        def register_example(name: str, text: str) -> None:
            @server.resource("analytics://examples/" + name)
            def example() -> str:
                return text

        register_example(name, path.read_text(encoding="utf-8"))
    return server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bounded YAML analytics MCP (stdio; authority inherited from launcher)"
    )
    parser.add_argument(
        "--allow-uploads", action="store_true", help="Enable bounded local JSON uploads"
    )
    args = parser.parse_args()
    try:
        server = create_server(uploads=args.allow_uploads)
    except ImportError:
        raise SystemExit(json.dumps(AnalyticsError("MCP_UNAVAILABLE").envelope())) from None
    server.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
