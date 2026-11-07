# Agent Quick Reference — YAML Query DSL V1

**Authored query**: one YAML mapping document (not JSON SQL). **Input records**: JSON, NDJSON, Python mappings. **Result/error**: JSON. **MCP**: send query as `query_yaml: str` in `analytics_validate_query`, `analytics_explain_query`, and `analytics_query`.

```yaml
version: analytics.query/v1
dataset:
  name: example_data
filters:
  - field: /status
    op: eq
    value: error
aggregations:
  - op: count
    as: errors
limit: 100
```

`example_data` is a logical binding; discover available names with `analytics_list_datasets` and use `dataset.name`. Names are scoped to the server-selected execution context.

- `version` exactly `analytics.query/v1`; `dataset.name` opaque authorized string.
- `casts`: list with `field`, `to: float64|int64|string|datetime`, `on_error: reject|"null"`. For datetime include `format: rfc3339|epoch_s|epoch_ms|epoch_us`.
- `time_range`: `field: /ts` plus either `last_minutes: 60` or absolute `start` and `end` RFC3339 offset-aware strings. When windowed, a time range is required.
- `filters`: 0–20 predicate AST nodes (implicit AND). Leaf `field`, `op`, `value`; `in/not_in` use `values`; `between` uses `lower`/`upper`; null/missing checks omit values; `and/or` use `conditions`, `not` uses `condition`.
- 16 leaf operators: `eq ne gt gte lt lte in not_in between is_null is_not_null is_missing is_present contains starts_with ends_with`; logical 3: `and or not`.
- `window`: omitted/null or a mapping `type: tumbling, size: 5m` or `type: sliding, size: 5m, step: 1m`. Fixed UTC intervals allowed by server. Overlapping windows reuse source records.
- `group_by`: up to four `{field: /region, as: region}` mappings (YAML flow example); alias must be unique.
- `aggregations`: 1–20 operations; all aliases `as` unique. Operators: `count count_non_null null_count missing_count count_distinct sum avg min max median p50 p90 p95 p99 stddev variance count_if sum_if avg_if ratio_if`.
- `having`: result-alias predicates, up to 10; `order_by`: alias/window field, `direction: asc|desc`, `nulls: first|last`; `limit` 1–500 by default.
- `options`: `include_empty_windows: false` default, true only when bounded and policy allows.
- Full operator semantics, null behavior, quantile interpolation, window alignment, resources and authorization live in `docs/query-language.md`.

**YAML hazards:** no anchors/aliases/tags/merges/multi-doc. Use two-space indentation. Scalar `on`, `off`, `yes`, `no` remain strings; lowercase `true`, `false`, `null` are typed. Quote string literal `"null"`; quote strings containing colon-space or `#` when needed. Do not use `.nan` or `.inf`.

Status: `OK`, `NO_DATA`, `INSUFFICIENT_DATA`, `ERROR`. Always inspect source counts, field quality, resolved time range, truncation and null denominators.

See `../../examples/README.md`, `../../examples/queries/*.yaml`, `docs/yaml-security.md` and the canonical error catalog.

String matching extends the source predicate union with not_contains, word, like/ilike, regex, fuzzy and multi-field match. See analytics://string-matching/v1 and references/string-matching.md. Normalization is explicit, fuzzy selection exhaustive, diagnostics output-only, identity inference unsupported.
