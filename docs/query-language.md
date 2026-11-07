# Analytics YAML Query Language v1 — Normative Contract

- **Version literal:** `analytics.query/v1`
- **Input:** one UTF-8 YAML query document referring to a previously admitted, immutable, authorized logical dataset name
- **Output:** `analytics.result/v1` JSON envelope
**Policy:** strict, typed, bounded, deterministic. Implement and test every operation listed here; do not silently ignore keys, unsupported options, or type conflicts.

## 1. End-to-end example

Assume incoming arbitrary JSON data:

```json
[
  {"ts":"2026-11-06T10:00:05Z","tenant":"alpha","region":"west","metrics":{"delay":12.2},"status":"warning"},
  {"ts":"2026-11-06T10:01:06Z","tenant":"alpha","region":"west","metrics":{"delay":16.9},"status":"error"},
  {"ts":"2026-11-06T10:02:07Z","tenant":"alpha","region":"east","metrics":{"delay":null},"status":"ok"},
  {"ts":"2026-11-06T10:03:08Z","tenant":"alpha","region":"west","status":"ok"}
]
```

Dataset schema is discovered; it is **not predefined**. An authorized app registers records under a logical name in an execution context. The **YAML query document** is:

```yaml
version: analytics.query/v1
dataset:
  name: example_data
casts:
- field: /ts
  to: datetime
  format: rfc3339
  on_error: reject
time_range:
  field: /ts
  start: '2026-11-06T10:00:00Z'
  end: '2026-11-06T11:00:00Z'
filters:
- field: /tenant
  op: eq
  value: alpha
window:
  type: tumbling
  size: 5m
group_by:
- field: /region
  as: region
aggregations:
- op: count
  as: records
- op: count_non_null
  field: /metrics/delay
  as: observed_delay
- op: missing_count
  field: /metrics/delay
  as: missing_delay
- op: avg
  field: /metrics/delay
  as: avg_delay
- op: p95
  field: /metrics/delay
  as: p95_delay
- op: count_if
  where:
    field: /status
    op: eq
    value: error
  as: errors
having:
- field: records
  op: gte
  value: 1
order_by:
- field: window_start
  direction: asc
- field: region
  direction: asc
limit: 100
```

> The logical name `example_data` must be registered by the application in the current context, or selected from analytics_list_datasets. It is independent of Python variables and internal snapshot IDs. Absolute time examples are fixed for repeatable tests. Timestamp parsing is explicitly declared because JSON strings are not intrinsically datetimes.

## 1.1 YAML document format and trust boundary

The query **authoring format** is YAML. Input record formats remain JSON/NDJSON/Python mappings; results and error envelopes remain strict JSON. MCP itself uses JSON-RPC transport; the tool parameter named `query_yaml` is a **string containing YAML text**, not a JSON query object. Python `engine.query_yaml(query_yaml)` uses the same parser; a trusted local-only `engine.query_file(path)` is convenience, never a remote MCP file path.

A strict parser MUST be implemented and is specified in `docs/yaml-security.md`. Contract highlights:

- Exactly one mapping document, UTF-8, bounded bytes (default 64 KiB), depth, nodes, and string lengths; comments and ordinary block/flow mapping syntax allowed.
- Disallow anchors (`&x`), aliases (`*x`), merge keys (`<<`), explicit tags (`!`, `!!`), `%TAG` directives, multiple documents, custom constructors, recursive/cyclic structures and arbitrary object construction. Reject duplicate mapping keys at **every depth**.
- Implement a restricted YAML 1.2-like **JSON-compatible implicit scalar subset**: lowercase `true`/`false`, `null`, decimal integers/floats; anything else remains a string. In particular `yes`, `no`, `on`, `off`, ISO timestamps and values containing colons must not silently turn into booleans/datetimes. Require quotes for strings when ambiguity exists, for example `value: "true"`.
- Reject non-finite numbers (`.nan`, `.inf`), octal/hex integer notation, unsupported numbers, non-string map keys, and invalid Unicode/control scalars. JSON Pointer field paths and dynamic values are treated as **data**, never expressions.
- YAML parsing MUST NOT bypass any Pydantic strict model, authorization, provenance, or execution budget. Never use `yaml.load(..., Loader=yaml.Loader)`, `unsafe_load`, pickle or `eval`.
- The server returns code-keyed errors from the single `errors/catalog.json`, optionally with safe 1-based `line`/`column` and a Pydantic query field path. It must not echo secret text fragments from malicious queries.

A normalized typed AST is the sole input to policy/planning/Polars; the compiler must have no dependency on YAML syntax and must not accept raw YAML nodes.

## 2. Root contract

| Key | Type / default | Requirement |
|---|---|---|
| `version` | literal `analytics.query/v1` | required |
| `dataset` | object `{ "name": string }` | required; ownership checked server-side |
| `casts` | array of 0..8 cast specifications | optional, default [] |
| `time_range` | absolute or relative time object | optional unless window requested |
| `filters` | array of 0..20 predicate nodes; implicit AND | optional, default [] |
| `window` | null or tumbling/sliding | optional, default null; requires valid time range |
| `group_by` | 0..4 `{field: JSON pointer, as: alias}` | optional, default [] |
| `aggregations` | array of 1..20 typed aggregates | required |
| `having` | 0..10 post-aggregate predicates, implicit AND | optional, default [] |
| `order_by` | 0..4 sort elements | optional; implicit stable ordering when omitted |
| `limit` | int 1..500, default 100 | optional; result cap, not work cap |
| `options` | `{include_empty_windows?: false}` | optional; true only under restricted conditions |

The YAML root mapping is validated using `ConfigDict(extra="forbid", strict=True)` after restricted parsing. Unknown keys are errors. The DSL accepts neither textual expressions nor source-specific function names. Query files must use `.yaml` or `.yml` and contain exactly one YAML mapping document. YAML is never executed as code. `dataset.name` must resolve to a live authorized binding in the server-selected context. Names match [A-Za-z][A-Za-z0-9_-]{0,63}; no paths, context IDs or internal snapshot IDs are accepted. Unknown and foreign-context names both yield DATASET_NAME_UNKNOWN. Existing expired bindings yield DATASET_SNAPSHOT_STALE. All numeric limits above are **V1 default policy maxima**, further restricted by the server owner if configured.

### 2.1 JSON Pointer fields

Use canonical RFC 6901 paths: `/name`, `/nested/value`, `/~0escaped`, `/foo~1bar` for key `foo/bar`. A key `""` uses `/` (empty token), subject to field policy. Root `/` must not ambiguously refer to entire record. Reject paths deeper than `max_depth`, invalid escape sequences, or non-scalar fields for unsupported operators. No dotted-path shorthand; no wildcards, JSONPath or array expansion. A path identifies the same logical field in every record, although that field may be missing or type-conflicted.

### 2.2 Type contract

Supported queryable scalar types: boolean, integer (signed 64-bit if representable), float64 (finite), string (bounded), datetime (UTC), and null. JSON `object` and `array` may be discovered but are not groupable, comparable, castable to numeric, or aggregatable in V1. `mixed` discovered type requires an explicit and permitted cast or query fails with `DATA_FIELD_TYPE_CONFLICT`. Source field names/aliases must be authorized and visible. A cast is not the same as granting access to a field.

### 2.3 Casts

```yaml
field: /measure
to: float64
on_error: 'null'
```

Allowed `to`: `float64`, `int64`, `string`, `datetime`; format mandatory for datetime: `rfc3339` or `epoch_s`, `epoch_ms`, `epoch_us` (only numeric when epoch chosen). `on_error`: `reject` (fail if any non-null/non-missing value cannot convert) or `null` (mark invalid conversion null, count `cast_errors`, warning). Do not silently convert booleans to numbers; verify overflow and non-finite values. `to:string` is for scalar values only and is not an arbitrary JSON serializer. Reject decimal precision-loss if a policy marks a field exact.

## 3. Filter predicate AST — all V1 operators

A leaf has keys `field: /path`, `op: eq`, and `value: 123`; `filters` is implicit AND. Negation and composition are explicit disjoint typed variants. Enforce max AST depth 4, 32 total nodes, max 20 literals in an IN list, max scalar text length 1024. No executable expression syntax. The [matching extension](string-matching.md) adds bounded Rust regex, never Python callbacks.

| Operator | Shape | Semantics |
|---|---|---|
| `eq` | `{field,op,value}` | typed equality; null comparison yields unknown (not selected) |
| `ne` | same | typed inequality; **does not** include null/missing |
| `gt` | same | greater-than ordered scalar |
| `gte` | same | greater-or-equal |
| `lt` | same | less-than |
| `lte` | same | less-or-equal |
| `in` | `{field,op,values:[...]}` | membership, nonempty homogeneous bounded list |
| `not_in` | same | inverse membership on present non-null values |
| `between` | `{field,op,lower,upper}` | inclusive ordered bounds, `lower <= upper` |
| `is_null` | `{field,op}` | true if explicit JSON null **or missing** in normalized columns |
| `is_not_null` | `{field,op}` | true if present, non-null and successfully cast |
| `is_missing` | `{field,op}` | true only if the path is absent in original record |
| `is_present` | `{field,op}` | true if path exists, including explicit null |
| `contains` | `{field,op,value}` | literal case-sensitive substring only |
| `starts_with` | same | literal case-sensitive prefix only |
| `ends_with` | same | literal case-sensitive suffix only |
| `not_contains` | `{field,op,value,normalization?}` | literal substring complement; null remains unknown |
| `word` | same | Rust Unicode whole-word boundaries |
| `like`, `ilike` | same | anchored percent/underscore patterns with bounded escaping |
| `regex` | same | bounded Rust regex search; no lookaround/backreferences |
| `fuzzy` | `{field,op,value,algorithm,min_score,normalization?}` | inclusive RapidFuzz similarity over full normalized values |
| `match` | `{match:{fields,patterns,normalization?,mode:any}}` | three-valued ANY across authorized field/rule pairs, without multiplying records |
| `and` | `{op,conditions:[pred,...]}` | all conditions true; min 2 |
| `or` | same | any condition true; min 2 |
| `not` | `{op,condition:pred}` | logical complement with documented null behavior |

Notes:

- **26 predicate tags total:** 22 leaf predicates, `and`/`or`/`not`, and the disjoint multi-field `match` node. Boolean `false`, integer 0 and empty string are actual values, not missing.
- Null semantics use three-valued logic for typed comparisons; the top-level WHERE keeps only True; `count_if` treats unknown as False. `not` of unknown stays unknown, rather than turning null into a match.
- Existing literal operations retain their defaults. The matching extension supports explicit NFC/NFKC, trim and casefold, LIKE/ILIKE, Rust regex and exhaustive fuzzy similarity. Normalization changes matching only, never source/group values. Regex has its own syntax/case policy; see the [full matching contract](string-matching.md).
- `is_null` includes missing **by definition**. For distinctions, use `is_missing` and `is_present` explicitly.
- Operators must reject incompatible types, not return empty results on error. Explicit cast rules can resolve supported conflicts.
- HAVING uses a separate, smaller result-only typed predicate model; supports `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `between`, `is_null`, `is_not_null`, `and`, `or`, `not`. Its `field` is an output alias (not a source JSON Pointer). Max 10 total nodes.

## 4. Aggregations — all V1 operators

All aggregations require unique safe `as` aliases of ASCII `[A-Za-z][A-Za-z0-9_]{0,63}` not equal to reserved outputs (`window_start`, `window_end`, `query_id`, etc.) nor group aliases. `field` is required only when specified below; no unused extra keys.

| Operator | Syntax fields | Exact semantics |
|---|---|---|
| `count` | `op,as` | input rows per group/window (including null-bearing records) |
| `count_non_null` | `op,field,as` | count present, non-null, successfully typed values |
| `null_count` | `op,field,as` | explicit JSON null plus invalid-to-null conversions, **not originally missing** |
| `missing_count` | `op,field,as` | count originally absent field path |
| `count_distinct` | `op,field,as` | exact unique non-null scalar values; bounded cardinality |
| `sum` | `op,field,as` | sum of finite numeric valid values; null when no valid samples |
| `avg` | `op,field,as` | arithmetic mean over valid numeric values; null if none |
| `min` | `op,field,as` | smallest valid ordered scalar; null if none |
| `max` | `op,field,as` | largest valid ordered scalar; null if none |
| `median` | `op,field,as` | 0.50 quantile of numeric values with linear interpolation |
| `p50` | `op,field,as` | exact quantile q=0.50, linear interpolation |
| `p90` | `op,field,as` | exact quantile q=0.90, linear interpolation |
| `p95` | `op,field,as` | exact quantile q=0.95, linear interpolation |
| `p99` | `op,field,as` | exact quantile q=0.99, linear interpolation |
| `stddev` | `op,field,as` | sample stdev, ddof=1, null if fewer than 2 valid values |
| `variance` | `op,field,as` | sample variance, ddof=1, null if fewer than 2 valid values |
| `count_if` | `op,where,as` | rows where predicate True; false/unknown not counted |
| `sum_if` | `op,field,where,as` | numeric sum over matching valid samples; null if no matches |
| `avg_if` | `op,field,where,as` | numeric mean over matching valid samples; null if none |
| `ratio_if` | `op,field,where,as` | True matches **among non-null valid values of field** / non-null valid count; null if denominator=0 |

**20 operators total.** For `ratio_if`, require `where` to reference the `field` itself or other approved scalar fields; clarify that null/missing field never enters the denominator and match count only includes denominator-eligible rows. Numeric `sum` must detect overflow or fail clearly rather than wrap. `median` and `p50` produce the same result by design. `count_distinct` exactness is restricted to finite cardinality. No `first`/`last` in V1: input order/event-time tie semantics need a separate later contract.

### 4.1 Aggregation example with conditional counts

```yaml
aggregations:
- op: count
  as: events
- op: count_if
  where:
    field: /status
    op: eq
    value: failed
  as: failures
- op: ratio_if
  field: /latency
  where:
    field: /latency
    op: gt
    value: 100
  as: high_latency_fraction
```

This is a fragment, not a full root query. Percentages are *fractions*, range `[0,1]`, not multiplied by 100. A ratio based on missing observations must return supporting coverage metadata. Never turn count of bad observations into duration without sampling-cadence evidence.

## 5. Time semantics and windows

### 5.1 Time range (optional without window, mandatory with window)

Absolute:

```yaml
field: /observed_at
start: '2026-11-06T00:00:00Z'
end: '2026-11-06T01:00:00Z'
```

Relative:

```yaml
field: /observed_at
last_minutes: 60
```

Allow exactly one of `last_minutes` (1..1440) or `start`+`end`. Normalize explicit RFC3339 timestamps with timezone offsets to UTC. Resolve a relative interval against a server-injected UTC clock **once**, not the model's clock. `[start,end)` is applied before windowing; reject invalid or overly broad time bounds. Time field must be datetime or explicitly cast to datetime, with failed timestamp parses handled according to policy and counted. No implicit unit guessing, local timezone or DST-based calendar period in V1. If `time_range` is omitted, all admitted snapshot records are in scope (subject to row limits).

### 5.2 Windows

No window: `"window": null` or key omitted; grouped aggregation over entire filtered data.

Tumbling:

```yaml
type: tumbling
size: 5m
```

Sliding (also called hopping):

```yaml
type: sliding
size: 5m
step: 1m
```

Allowed fixed intervals: `1s`, `5s`, `10s`, `30s`, `1m`, `5m`, `15m`, `30m`, `1h`. A trusted policy may reduce this allowlist. `step <= size`; overlap multiplier `size/step <= 12`, step divides size exactly. Windows aligned to UTC Unix epoch, closed left (`[start,end)`), labeled with **both** start and end. Partial boundary windows flagged in evidence. Require bounded number of generated windows, groups, and result bytes before execution. `group_by_dynamic` must sort the timestamp appropriately within groups as required by Polars version in use. Overlapping windows reuse records; do not sum them to calculate distinct source samples.

Polars does not automatically materialize empty windows. Default is sparse window output. `include_empty_windows=true` may be supported only with zero groups or a *small, explicitly constrained authorized list* of group keys and bounded grid. Otherwise fail `QUERY_EMPTY_WINDOW_UNSUPPORTED`, never silently omit promised rows. In an explicit empty window row, counts are 0 and numeric metric aggregations null, with `NO_DATA` evidence.

### 5.3 Group by, HAVING, ordering

`group_by` defines output aliases for one to four scalar dimensions. Missing group keys are represented distinctly from explicit null in result grouping (e.g. distinct tagged sentinel encoded as JSON `null` with `group_key_status` metadata, or dual marker), and must be tested—never silently merge absent/null if a query requests their distinction. Reject arbitrary cardinality above policy limit. Group ordering deterministic across runs.

`having` applies **after** aggregation using output aliases only. `order_by` allows 0..4 alias/window keys, directions asc/desc, explicit `nulls: first|last` (default last), with deterministic tie-breaks. `limit` applies last. `truncated` only true when eligible output count exceeds returned count; `limit` doesn't justify unbounded work.

## 6. Error and evidence requirements

Public query issues use `QUERY_*`, data shape issues `DATA_*`, record ingestion `INPUT_*`, authorization `ACCESS_*`, limits `RESOURCE_*`, backend `EXECUTION_*`. Every code is defined in `src/xp_libs_analytics/errors/catalog.json`; the API returns that **exact** message string, safe JSON path, retry flag and bounded `details`. Avoid echoing raw content. `analytics_error_info(code)` exposes the same catalog and cannot fabricate a new message.

`NO_DATA` means zero matching valid observations; this is not an error. `INSUFFICIENT_DATA` means data exists but a configured minimum evidence requirement was not met; metadata explains the basis. An unknown expected sampling cadence means coverage is `UNKNOWN`, not zero or 100%. Snapshot queries should identify which rows were admitted, excluded, malformed, missing, cast-invalid and aggregated, allowing totals to reconcile.

## 7. YAML authoring / Pydantic schema compatibility policy

- Pydantic model names/types and `model_json_schema()` snapshots are committed and compared on PRs.
- `analytics.query/v1` YAML cannot silently change operator meaning, error code semantics, timestamp boundaries or serialization. Additive optional properties are reviewed; breaking changes require `v2` and migration docs.
- Use discriminated unions for `op` and `type`, `ConfigDict(extra='forbid', strict=True)`, explicit types for scalar values, and limits at model + semantic levels.
- Pydantic-derived JSON Schema documents the **post-YAML-parsing AST**, not the YAML tool wire argument; the skill and YAML examples teach agents the authoring format. JSON Schema supplied to LLMs assists planning, but real security rules stay server-side. Even a valid schema can't grant access to a dataset or reveal an unauthorized field.
- Validate every `.yaml` under `examples/queries/`: bounded strict YAML parser → `AnalyticsQuery.model_validate` → semantic validation against authorized named synthetic snapshots. Do not call `model_validate_json` for YAML. Invalid examples fail CI. Canonical runtime errors preserve YAML locations (line/column) and Pydantic field paths.

## 8. Operator-to-Polars mapping guidance (not agent-facing)

- Filter leaves → `pl.col(colid)` comparisons, `.is_in`, `.is_null`, `.str.contains(..., literal=True)` if supported by pinned version or `.str.contains` with safely escaped literal, `.str.starts_with`, `.str.ends_with`.
- Missing predicates → separate source-presence bitmap/column per referenced field; do **not** map `is_missing` to `.is_null()`.
- Count → `pl.len()`; non-null → `.count()`; null vs missing → separate raw-null flags/presence; exact distinct → `.drop_nulls().n_unique()` with cardinality check.
- Quantiles → `.quantile(q, interpolation='linear')`; sample stdev/var → Polars equivalent with ddof=1, pinned version verified.
- Conditional counts → `when(predicate).then(1).otherwise(0).sum()` or equivalent Boolean `fill_null(False).cast(Int64).sum()`.
- Conditional mean/sum → null out invalid or nonmatching samples; ratio numerator/denominator must use the **same** non-null eligibility filter.
- Time grouping → lazy or eager `group_by_dynamic(index_column=..., every=..., period=..., group_by=..., closed='left', label='left', start_by='window')` with explicit UTC alignment and boundaries verified against reference oracle; APIs are version dependent; confirm exact pinned version.
- HAVING/sort → expressions using approved output alias map only. Keep internal ids opaque to avoid injection or name collisions.
- Prefer lazy execution and projection/filter pushdown before materialization where possible, but JSON records supplied in memory are already parsed; do not claim zero-copy for all formats.

The backend uses bounded native integer-range expansion for epoch-aligned window membership. Operator semantics are verified against an independent Python oracle; changes require versioned contract review.

## String matching extension (0.4.0)

The [complete matching contract](string-matching.md) defines normalization, raw-value disclosure, bounded candidate/scoring work, diagnostics scope and all new errors. Source predicates are shared between filters and every conditional aggregate; HAVING remains aggregate-output aliases only. Matching does not infer entities. Snapshot registry and temporal semantics remain unchanged. analytics://string-matching/v1 exposes the same product reference through MCP.
