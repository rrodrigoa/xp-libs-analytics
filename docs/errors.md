# Canonical Error Contract — Analytics Engine V1

## Decision: one error-message registry

Every public error code maps to exactly **one canonical message string** in:

`src/xp_libs_analytics/errors/catalog.json`

The file is a JSON object, where **key = stable UPPER_SNAKE_CASE error code** and **value = user-visible message string**. The single string includes what failed, the recommended correction, and a safe example. The catalog remains JSON even though the **query DSL is YAML**; input data remains JSON/NDJSON. No alternative YAML message registry is permitted. The catalog remains JSON even though the **query DSL is YAML**; input data remains JSON/NDJSON. No alternative YAML message registry is permitted. **Do not create duplicate message sources**, YAML translations, nested error objects in the catalog, class-specific message templates, or hardcoded alternates in the MCP adapter. Treat the catalog as release-versioned API data.

Example extract (illustrative; file remains authoritative):

```json
{
  "QUERY_YAML_MULTI_DOCUMENT": "Only one YAML query document may be submitted at a time. Fix: remove additional document separators and send one root mapping. Example: version: analytics.query/v1 followed by dataset and aggregations in the same document."
}
```

The runtime returns the catalog **value verbatim**, with dynamic safe context outside the message. Machine agents can read it via `analytics_error_info(code)` and use the `Fix:` and `Example:` text to repair their own inputs. A static message is safer for privacy: field names/values from sensitive data never leak into interpolation.

## YAML parser error boundary

The YAML query parser is a separate boundary from JSON record ingestion. Its dedicated stable errors are `QUERY_YAML_INVALID`, `QUERY_YAML_DUPLICATE_KEY`, `QUERY_YAML_ANCHOR_FORBIDDEN`, `QUERY_YAML_ALIAS_FORBIDDEN`, `QUERY_YAML_TAG_FORBIDDEN`, `QUERY_YAML_MULTI_DOCUMENT`, `QUERY_YAML_ROOT_INVALID`, `QUERY_YAML_COMPLEXITY_LIMIT`, and `QUERY_YAML_SCALAR_INVALID`. Each appears **once** in the same `catalog.json` object. There is no Python hardcoded fallback message. Keep source-location data in `error.details` with safe 1-based `line` and `column`; `error.path` localizes the AST property (`$.filters[0].op`), never the underlying input record field. Do not echo malicious YAML snippets in error output. YAML scanner/constructor faults should not escape as raw exceptions.

For example, an agent can repair `QUERY_YAML_DUPLICATE_KEY` by removing a repeated `limit` mapping key, but must not attempt to force a parser to choose the first or last occurrence. Field/auth failures cannot be repaired by bypassing access control.

## YAML parser error boundary

The YAML query parser is a separate boundary from JSON record ingestion. Its dedicated stable errors are `QUERY_YAML_INVALID`, `QUERY_YAML_DUPLICATE_KEY`, `QUERY_YAML_ANCHOR_FORBIDDEN`, `QUERY_YAML_ALIAS_FORBIDDEN`, `QUERY_YAML_TAG_FORBIDDEN`, `QUERY_YAML_MULTI_DOCUMENT`, `QUERY_YAML_ROOT_INVALID`, `QUERY_YAML_COMPLEXITY_LIMIT`, and `QUERY_YAML_SCALAR_INVALID`. Each appears **once** in the same `catalog.json` object. There is no Python hardcoded fallback message. Keep source-location data in `error.details` with safe 1-based `line` and `column`; `error.path` localizes the AST property (`$.filters[0].op`), never the underlying input record field. Do not echo malicious YAML snippets in error output. YAML scanner/constructor faults should not escape as raw exceptions.

For example, an agent can repair `QUERY_YAML_DUPLICATE_KEY` by removing a repeated `limit` mapping key, but must not attempt to force a parser to choose the first or last occurrence. Field/auth failures cannot be repaired by bypassing access control.

## Runtime architecture

1. `ErrorCode`: closed enum (generated or checked against catalog.json); names stay stable during v1.
2. `ErrorCatalog`: uses `importlib.resources.files('xp_libs_analytics.errors').joinpath('catalog.json')` to load, sanity checks string values, caches read-only in memory.
3. `AnalyticsError`: typed internal exception carrying `code`, `path`, safe `details`, `trace_id`, `retryable`, optional `cause` stored only in secure logs.
4. `ErrorTranslator`: catches all known parsing, validation, policy, cost, backend and transport failures and maps them to one of the known codes. Unknown exceptions map to `INTERNAL_ERROR`; internal exception text never reaches caller.
5. `ErrorEnvelope`: serializes `code`, exact canonical message, JSON path, bounded optional details, and boolean retryability. No raw record echo. Exact `query_id` correlation matches server logs/traces.
6. **Only the public `message` field is catalog-owned**; metadata (`retryable`, HTTP/MCP status, path, safe remediation links) can be maintained in code as a typed classification table, but no second message string.

Example:

```json
{
  "version": "analytics.result/v1",
  "status": "ERROR",
  "query_id": "qid-123",
  "error": {
    "code": "QUERY_UNKNOWN_OPERATOR",
    "message": "<exact catalog value>",
    "path": "$.aggregations[1].op",
    "retryable": false,
    "details": {"allowed_operators": ["count", "avg", "p95"]}
  }
}
```

Use `details` only with authorized, allowlisted information; sanitize every scalar, max length, and array. Do not return unauthorized field names in alternatives. Do not differentiate "unknown" from "forbidden" handles where that leaks existence. Errors are **data**, not prompts, and must not contain arbitrary instructions from source records.

## Error-code rules

- Codes grouped as `INPUT_`, `DATA_`, `QUERY_`, `ACCESS_`, `RESOURCE_`, `EXECUTION_`, `MCP_`, `INTERNAL_`.
- No free-text error codes derived from third-party exception names; do not expose Polars/Pydantic exception messages to agents verbatim.
- `retryable` defaults False. Potentially transient only: MCP_UNAVAILABLE, RESOURCE_CONCURRENCY_LIMIT, RESOURCE_TIMEOUT, EXECUTION_BACKEND_ERROR (bounded retry with exponential backoff), EXECUTION_CANCELLED if explicit user intent. Explicitly do not blindly retry ACCESS or format errors.
- `status=NO_DATA` is a valid analytical result, not an error. A failed cast with `on_error='null'` is a warning+quality count, not an exception, unless policy rejects it.
- Error paths use JSONPath-like location strings purely for localization, e.g. `$.filters[0].op`, not an evaluator.
- Add a code by updating `catalog.json`, enum/check, mapping tests, examples/skill reference where relevant, and CHANGELOG. Rename or remove only in a major DSL/API version.
- Package wheel/sdist must include `catalog.json` and tests must load it through `importlib.resources` after installing the wheel.

## Catalog lint/test gates

1. JSON **record ingestion** parses with duplicate-key detection (`object_pairs_hook`) and UTF-8 validation.
2. Top-level object only, no empty keys, all keys match `^[A-Z][A-Z0-9_]+$`, all values nonempty UTF-8 strings.
3. Every value contains an explanation, `Fix:` and `Example:`; no unsupported external links or unredacted real payload data.
4. **Exact bijection** between codes reachable from public error translators and catalog keys (unused codes must be justified and explicitly marked as planned by tests/coverage policy).
5. No runtime hardcoded user-facing error strings beyond the catalog, including exception fallback.
6. Golden snapshot for error envelopes per code, plus at least one positive recovery test for every user-fixable category.
7. Fuzz inputs trigger only catalog-known codes, never third-party stack traces/structured exceptions that leak data.
8. Error lookup returns the *same bytes* as the catalog value in wheel, in-process SDK, and MCP.

## Agent recovery guide

- **Validation/type errors:** query `analytics_describe`, inspect `analytics_capabilities`, correct field/type/op and retry once with a revised query.
- **Malformed input:** correct JSON structure; never guess silently which record value should have been used.
- **Access denied:** do not attempt another principal's handle or enumerate ids; request legitimate scope through host application.
- **Resource limit:** shrink inputs, number of groups, window overlap, or output; don't repeatedly retry an identical expensive plan.
- **Timeout/backend transient:** backoff, optional one retry, then escalate with query_id.
- **No data/insufficient evidence:** communicate the limitation, distinguish missing samples from observed null values, do not fabricate aggregates.

## Named dataset lifecycle (0.3.0)

The catalog has 62 codes. DATASET_NAME_UNKNOWN covers unknown and foreign-context names identically. DATASET_NAME_DUPLICATE rejects accidental rebinding. DATASET_NAME_INVALID rejects unsafe logical names. DATASET_SNAPSHOT_STALE covers expired bindings and mismatched expected revisions. ACCESS_DENIED covers scope/closed-context failures; ACCESS_FIELD_DENIED covers hidden fields. RESOURCE_DATASETS_LIMIT bounds binding/snapshot admission. Legacy DATA_HANDLE_* and RESOURCE_HANDLES_LIMIT codes were removed; see CHANGELOG. The canonical strings remain exclusively in catalog.json.

## Matching extension (0.4.0)

The catalog now has 73 codes, adding 11 matching-specific distinctions documented in string-matching.md. Existing DATA_*/QUERY_*/ACCESS_* codes are reused for equivalent field/type/operator/permission failures. Canonical messages and repair examples remain exclusively in catalog.json. Matching resource failures do not return partially scored aggregates; new matching budget errors are nonretryable with identical inputs.
