# Agent Error Handling for YAML Queries

The **only** runtime error message registry is `src/xp_libs_analytics/errors/catalog.json`. It maps each stable error code directly to one canonical string with a `Fix:` and `Example:`. Never copy messages to a second runtime module or generate free-form exceptions. Use `analytics_error_info(code)` to retrieve the canonical value.

Tool error JSON includes `error.code`, `error.message` (exact catalog lookup), `error.path` (YAML AST location such as `$.aggregations[0].op`), `retryable`, and optionally safe 1-based YAML `line` and `column` in `details`. Do not include raw YAML payload text or dataset records in errors.

## Correct an unsupported aggregation

Invalid query (structurally plausible, but `average` isn't a V1 operator):

```yaml
version: analytics.query/v1
dataset:
  name: example_data
aggregations:
  - op: average
    field: /value
    as: average_value
```

`QUERY_UNKNOWN_OPERATOR` → replace with `avg`, revalidate:

```yaml
version: analytics.query/v1
dataset:
  name: example_data
aggregations:
  - op: avg
    field: /value
    as: average_value
```

## Correct YAML syntax/format errors

- `QUERY_YAML_INVALID`: make one indented mapping, quote ambiguous strings.
- `QUERY_YAML_DUPLICATE_KEY`: remove a repeated key; never assume which repeated value should win.
- `QUERY_YAML_ALIAS_FORBIDDEN`, `QUERY_YAML_ANCHOR_FORBIDDEN`, `QUERY_YAML_TAG_FORBIDDEN`: express a small explicit mapping/list instead.
- `QUERY_YAML_MULTI_DOCUMENT`: one YAML document per call.
- `QUERY_YAML_ROOT_INVALID`: root must be mapping with `version`, `dataset`, `aggregations`.
- `QUERY_YAML_COMPLEXITY_LIMIT`: split/narrow query; do not try a recursive alias workaround.
- `QUERY_YAML_SCALAR_INVALID`: finite decimal numbers only; quote text.
- `QUERY_MALFORMED`: YAML parsed, but typed AST fields/types invalid; inspect supported model/schema.

## Correct semantic errors

- `DATA_FIELD_UNKNOWN`: call `analytics_describe` and select an authorized JSON Pointer exactly.
- `DATA_FIELD_TYPE_CONFLICT`: add a permitted cast or choose compatible field. Never silently coerce.
- `QUERY_WINDOW_INVALID`: verify permitted size/step and add time range with explicit datetime conversion.
- `QUERY_HAVING_INVALID`, `QUERY_ORDER_INVALID`: refer only to declared result aliases.
- `ACCESS_*`: stop. Do not enumerate dataset names, hidden fields, tenants or scopes to work around denial.
- `RESOURCE_*`: simplify, reduce groups or time window overlap, check `retryable` before retry.

`NO_DATA` and `INSUFFICIENT_DATA` are **non-error statuses**. Report evidence honestly. See the complete recovery matrix in `../SKILL.md` and examples in `../../examples/queries/`.

Matching-specific repairs are indexed by the product skill and analytics://string-matching/v1. All MATCH_* codes still resolve through the single catalog using analytics_error_info. Candidate/comparison failures return no partial aggregate; raw-diagnostic denial is not permission to enumerate values; similarity is not verified identity.
