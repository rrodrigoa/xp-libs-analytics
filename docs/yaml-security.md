# Restricted YAML Query Parser — Normative Security Contract (V1)

**Scope:** YAML is the only public query authoring format in V1. JSON/NDJSON records remain the analytics input, and query results/error envelopes remain JSON. This file governs YAML decoding before typed Pydantic validation. It does not permit arbitrary general-purpose YAML.

## Decision and rationale

- MCP tools receive `query_yaml: str`, transported inside MCP's ordinary JSON-RPC tool arguments. `query_yaml` contains **exactly one document**. The agent writes text, not a Python expression or SQL command. No `query_json`, SQL query, Jinja, template interpolation, arbitrary `include`, external `$ref`, URL, or local file path is accepted through MCP.
- The Python SDK offers `AnalyticsEngine.query_yaml(name: DatasetHandle, query_yaml: str)`, and a **trusted local SDK only** method `query_file(handle, pathlib.Path)`. The latter opens a path supplied by the trusted application; it MUST NOT be reachable through a remote MCP argument or resource URL.
- All public methods use a **single** restricted YAML parser implementation. The resulting plain Python mapping is immediately passed to strict Pydantic v2 discriminated models and then through semantic validation, authorization and budgets. The compiled logical plan is YAML-agnostic.
- The error registry remains **JSON** at `src/xp_libs_analytics/errors/catalog.json`, as a single code → string mapping. YAML is not an alternative error catalog; codes and their messages have only that canonical source.

## 1. Accepted document subset

| Construct | Policy | Reason |
|---|---|---|
| UTF-8 single YAML mapping document | REQUIRED | One deterministic typed query |
| Plain/quoted strings, block scalars, comments | Allowed, bounded | Readable for agents |
| YAML block or flow maps/sequences | Allowed, bounded | Nested predicates and aggregations |
| Scalars: `true`, `false`, `null`, decimal int/float | Allowed with **JSON-compatible** resolution | Match strict Pydantic scalar types |
| Unquoted `yes`, `no`, `on`, `off`, ISO 8601 timestamps | Parse as **strings**, never auto-coerce | Prevent YAML 1.1 surprises |
| Quoted `"true"`, `"null"`, `"2026-..."` | Strings | Preserve explicitly quoted user intent |
| Unknown properties under root/predicate | Reject via Pydantic | Strict AST schema |
| Duplicate mapping key (including nested) | Reject `QUERY_YAML_DUPLICATE_KEY` | Prevent conflicting query interpretations |
| Anchors `&label`, aliases `*label`, merge keys `<<` | Reject, including unused anchors | No object graphs/alias amplification |
| Explicit tags `!foo`, `!!python/object`, `!!int` | Reject even safe-standard explicit tags | No object constructors or type bypass |
| Directives `%TAG`, `%YAML` | Reject | Stable subset |
| Multiple `---` documents | Reject `QUERY_YAML_MULTI_DOCUMENT` | No concatenated query ambiguity |
| Top-level scalar, sequence, empty document | Reject `QUERY_YAML_ROOT_INVALID` | Root must be mapping |
| NaN, infinity, hex/octal numbers, exotic numeric notation | Reject or preserve as string and reject by typed model; NEVER coerce to finite number | Stable numeric semantics |
| Non-string mapping keys | Reject `QUERY_YAML_ROOT_INVALID` or `QUERY_MALFORMED` | All AST keys are names |
| YAML comments starting with `#` | Allowed; content after unquoted `#` is comment | Explain escaping in skill |
| Arbitrary interpolation, `!include`, environment variables | Not supported | Prevent secret and host access |

Parser fidelity:

1. Enforce UTF-8 and raw byte size **before** parser work. Suggested default `max_query_bytes=65_536`, configurable lower by trusted policy. Also bound string length (`max_scalar_chars=1_024` except perhaps approved fixed query metadata), nesting (`max_yaml_depth=16`), total nodes/events (`max_yaml_nodes=4_096`), mapping entries and sequences (`max_yaml_collection_items=1_024`); versioned server defaults are normative once selected.
2. The restricted loader extends PyYAML's `SafeLoader` with the library's duplicate-key rules, scalar resolution, and allowed syntax. Query parsing excludes `yaml.Loader`, `FullLoader`, `unsafe_load`, `!!python/*`, and arbitrary constructors.
3. Preflight parser events **with budgets**. Reject `AliasEvent`, any `anchor` on scalar/sequence/mapping events, explicit tags, directives, multi-documents and unsupported events. Stop after the first permitted document and reject further documents. Parse deterministically, with a hard deadline/worker budget and bounded untrusted text. Avoid regex-only prechecks: anchors, aliases and tags must be detected by parsing, not substring search (quoted `"*alias"` is just a string).
4. Clone only the safe scalar resolver table before modifying it; don't mutate global `yaml.SafeLoader` implicit resolvers. Install a narrowly documented set of JSON-compatible scalar recognizers: lowercase true/false; exact null; JSON-style decimal integers and finite decimal/exponent floats; no timestamp or binary auto-resolution; no YAML 1.1 aliases for booleans. Treat leading-zero or plus-prefixed numerals as strings unless explicitly supported by a later version. Validate `int64` bounds and numeric finiteness at the typed semantic layer; never accept Python bool as numeric.
5. Override mapping constructor to reject duplicate keys **at every depth**, including flow-style maps, before converting to dict; require string keys, no merge key, and preserve source marks in a safe `{query_path → (line,column)}` index. Convert positions to 1-based line/column. Use local source-mark metadata, never return raw YAML excerpts or tokens. A duplicate-key failure may include the duplicate key's **safe path** and line/column, but must not echo field values.
6. Validate all nested lengths and AST grammar **again** via Pydantic `ConfigDict(extra='forbid', strict=True)`, discriminated unions for filter/aggregate variants. Invalid root or key shape must become cataloged error codes. No YAML parser node enters Polars or authorization checks.
7. Preserve the exact user-facing YAML line/column and Pydantic location for structured diagnostics. Never expose stack traces, raw record contents, query contents, secrets, partial internal schemas, or inaccessible field names. Public `error.message` must equal `catalog.json[error.code]`; `details` may include a bounded `line`, `column`, `expected_type`, `allowed_ops` (if authorized), and `query_id`.
8. Resolve `dataset.name` only from the parsed mapping; enforce it is a scoped, live, authorized snapshot. The trusted SDK's `handle` argument must agree with the YAML's `dataset.name` after a safe structured binding step. Any mismatch is denied without revealing the existence of foreign handles.

## 2. Parser algorithm (implementation guidance; not a complete production parser)

```text
parse_query_yaml(query_yaml: str, principal, policy):
  enforce_utf8_bytes(query_yaml, policy.max_query_bytes)
  preflight_yaml_events_with_budgets(query_yaml, policy)
    # reject aliases, anchors, explicit tags, directives, multi-doc, excess nodes/depth
  mapping, source_marks = load_with_restricted_safe_loader(query_yaml)
    # custom JSON-compatible scalar resolver; duplicate-key and string-key checks
  assert_single_mapping_document(mapping)
  validated_ast = AnalyticsQuery.model_validate(mapping, strict=True)
  resolve_version_and_dataset_permissions(validated_ast, principal)
  analyze_types_and_budget(validated_ast, principal)
  return typed_plan, source_marks
```

The `parse_query_yaml` boundary is shared by `analytics_validate_query`, `analytics_explain_query`, `analytics_query`, and the SDK. Validation and explain are not weaker paths that accept different syntax or leak unauthorized schema.

## 3. MCP contract

```python
from fastmcp import FastMCP

mcp = FastMCP("Agent Analytics")


@mcp.tool
async def analytics_query(query_yaml: str) -> dict:
    """Execute one bounded YAML analytics query over an authorized JSON snapshot."""
    # Use authenticated server context; NEVER trust principal supplied inside YAML.
    return await service.query_yaml(query_yaml, trusted_context())


@mcp.tool
async def analytics_validate_query(query_yaml: str) -> dict: ...


@mcp.tool
async def analytics_explain_query(query_yaml: str) -> dict: ...
```

The example above sketches required signatures only: `service` and `trusted_context()` are implementation components to build, not FastMCP built-ins. The MCP input schema for these tools is a **string** plus length/description; the full AST's generated JSON Schema is available through `analytics_capabilities` or a read-only resource, for reference. No claim that FastMCP validates YAML internally. The server MUST perform all checks itself.

MCP resources: `analytics://skill/generic-analytics`, `analytics://query-language/v1`, `analytics://examples/index`, and a bounded allowlist of `analytics://examples/<bundled_name>`; examples are **read-only**, never user-chosen file paths.

## 4. Error catalog additions

The existing JSON input codes (`INPUT_*`) remain unchanged; they validate **data records**, not YAML queries.

| Code | When emitted | Safe repair |
|---|---|---|
| `QUERY_YAML_INVALID` | Scanner/parser syntax error, unterminated quote or bad indentation | Correct indentation/quoting from an example |
| `QUERY_YAML_DUPLICATE_KEY` | Two equal keys in one mapping | Retain one value |
| `QUERY_YAML_ANCHOR_FORBIDDEN` | Any `&anchor` declared | Inline bounded explicit fields |
| `QUERY_YAML_ALIAS_FORBIDDEN` | Any `*alias` reference | Inline bounded explicit fields |
| `QUERY_YAML_TAG_FORBIDDEN` | Any explicit `!tag`, `!!tag` or tag directive | Use basic scalars/maps/lists |
| `QUERY_YAML_MULTI_DOCUMENT` | More than one YAML document | Submit exactly one root mapping |
| `QUERY_YAML_ROOT_INVALID` | Empty, top-level list/scalar or non-string map key | Root must be mapping with `version`, `dataset`, `aggregations` |
| `QUERY_YAML_COMPLEXITY_LIMIT` | Text/node/depth/key/scalar budget exceeded | Narrow query or split investigations |
| `QUERY_YAML_SCALAR_INVALID` | Non-finite/unsupported scalar coercion | Use finite decimal number or quoted string |

One canonical message per code in `errors/catalog.json`, with `Fix:` and `Example:`. Map parser/Pydantic errors deterministically; no uncataloged error name may leave the boundary. Do not generate a new error message by formatting untrusted query text.

## 5. Negative and penetration acceptance tests (mandatory)

- Malformed indentation/quotes, illegal tab indentation, encoding errors, multiple-document streams, root list/null, duplicated root/nested/flow map keys.
- Tags, Python object tags, timestamp forced tags, anchors even when unused, aliases, merge keys, self-referential aliases, quoted strings containing literal `*foo` or `!bar` (must **not** be rejected when plain string).
- YAML 1.1 Boolean traps: `on`, `off`, `yes`, `no` remain strings. Lowercase `true`/`false` are booleans; quoted `"true"` is string. Timestamp text remains string. `null` becomes None and `"null"` remains string.
- Huge text, high nesting, many mapping keys, many sequences, long scalar values, wide nested predicates, alias bomb, repeated parsing under concurrency. Limits enforced before unsafe allocation; worker remains bounded.
- Numeric exotic syntax (`0x1f`, `01`, `.nan`, `.inf`), int64 overflow, float exponent overflow, surrogate/control text, escaped Unicode, non-string map keys.
- Injected SQL strings, `!!python/object/apply`, attempts at env/file read, cross-principal handles, unauthorized field paths; no execution or disclosure.
- Invariant: the same normalized AST serialized canonically yields identical logical plan/results whether YAML uses block syntax or allowed flow syntax; order of YAML mapping keys must not alter results. Duplicate keys are **never** accepted silently.
- CI tests must inspect exact catalog code, exact message lookup parity, 1-based safe mark positions and helpful repair behavior on representative failures.

**Versioning:** Changing scalar inference, alias/tag policy, syntax grammar or duplicate-key handling is a DSL compatibility change and requires explicit review, golden tests and migration notes. Security tightening can be shipped in a patch only when it does not silently change supported valid query meaning.
