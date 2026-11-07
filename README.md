# XP Libs Analytics

A Python library for bounded, in-memory snapshot analytics over JSON records with unknown, heterogeneous schemas. Queries are restricted YAML, validated with strict Pydantic models and compiled to fixed Polars expressions. The optional standalone FastMCP adapter supplies tools, an agent skill, and 28 read-only query examples.

Python 3.12+ · MIT · Import: `xp_libs_analytics` · Distribution: `xp-libs-analytics`

The distribution uses hyphens for package indexes and `pip`; Python imports use underscores because hyphens are not valid identifiers. The previous `agent_analytics` import and `agent-analytics-mcp` distribution/command have been replaced.

## Install and run

From this checkout:

```sh
python -m pip install .
python -m pip install '.[mcp]'    # optional MCP adapter
```

```python
from xp_libs_analytics import AnalyticsEngine

engine = AnalyticsEngine()
my_data = [{"value": 10}, {"value": 20}, {"value": None}, {}]
engine.register_records(name="observations", records=my_data)
engine.register_records("events", [{"kind": "created"}])
print(engine.list_datasets())

query_yaml = """version: analytics.query/v1
dataset:
  name: observations
aggregations:
  - {op: count, as: records}
  - {op: avg, field: /value, as: mean}
  - {op: missing_count, field: /value, as: missing}
"""
result = engine.query_yaml(query_yaml)
print(result["rows"])  # [{"records": 4, "mean": 15.0, "missing": 1}]

# Atomic publication: future queries resolve the new snapshot.
engine.replace_records("observations", [{"value": 30}])
engine.unregister_dataset("events")
```

Logical dataset names are symbolic references, independent of Python variable names, paths and opaque internal snapshot IDs. Registering a duplicate name fails; use `replace_records` to update it. Each query resolves exactly one immutable snapshot. Running queries retain their resolved snapshot through replacement, unregister or context closure; storage remains charged until their leases are released. Result metadata reports the logical name and resolved revision. Revisions increase within a context and can have gaps; re-registering a removed name never reuses an old revision. Optional `expected_revision` on replacement/unregister rejects stale updates.

For independent namespaces in one application:

```python
with engine.create_context() as ctx:
    ctx.register_records("observations", [{"value": 7}])
    print(ctx.query_yaml(query_yaml)["rows"])
# ctx closes and removes its bindings; engine's observations remain independent.
```

Names use 1–64 ASCII letters, digits, underscores or hyphens, starting with a letter. Unknown names return `DATASET_NAME_UNKNOWN` without revealing other contexts. Expired snapshots and stale expected revisions return `DATASET_SNAPSHOT_STALE`. Expired bindings are omitted from discovery; replace or unregister them to reuse resources. `register_stream(name, source)` is reserved and always rejects with `QUERY_UNSUPPORTED_FEATURE`; streaming is not implemented.

Input accepts JSON objects, arrays of objects, NDJSON, or Python iterables of JSON mappings. Admission copies records into immutable owner-scoped snapshots. Schema discovery examines every admitted record and returns no raw samples. Fields use RFC 6901 pointers; `/a~1b` addresses key `a/b`. Arrays remain opaque.

## Query features

| Feature | Supported V1 behavior |
|---|---|
| Predicates | 22 typed leaf operators; nested `and`, `or`, `not`; multi-field `match`; three-valued null logic |
| Aggregates | 20 count, distinct, numeric, linear quantile, sample variance, and conditional operations |
| Grouping | Up to four scalar dimensions; missing and explicit null groups remain separate |
| Time | Explicit RFC3339/epoch casts, absolute or relative UTC ranges, epoch-aligned tumbling/sliding windows |
| Results | HAVING, stable sorting, limit/truncation, strict JSON and quality/provenance evidence |
| Errors | 73 catalog codes, one canonical packaged message catalog, safe diagnostic locations |

See the [query language](docs/query-language.md), [examples](examples/README.md), and [agent skill](skills/generic-analytics/SKILL.md). `NO_DATA` reports absent matching observations. `INSUFFICIENT_DATA` applies the host's minimum sample policy. Unknown sampling cadence yields `coverage: UNKNOWN`; counts do not imply duration.

Mixed scalar types require explicit casts. Boolean values are never numeric. Null/missing values are excluded from numeric samples; cast failures configured as null are counted and warned. Integer sums detect overflow. Float statistics reject integer samples beyond exact float64 integer precision. V1 does not offer exact decimal analytics. String matching defaults to case-sensitive literal semantics, with explicit Unicode/case normalization, word, LIKE/ILIKE, bounded Rust regex and RapidFuzz similarity options. See the [matching contract](docs/string-matching.md).

## Matching observed values

```yaml
version: analytics.query/v1
dataset: {name: observations}
filters:
  - match:
      fields: [/actor/name, /actor/email]
      patterns:
        - {op: word, value: Peter}
        - {op: fuzzy, value: Pter, algorithm: ratio, min_score: 85}
      normalization: {case_sensitive: false, unicode: nfkc, trim: true}
      mode: any
aggregations:
  - {op: count, as: matching_records}
options:
  matching_details: {include: true, top_values: 5, include_raw_values: false}
```

Discover paths before authoring this query. Every eligible distinct fuzzy candidate is evaluated within host budgets; limit/top_values never approximate an aggregate. A record contributes once even when multiple fields/rules match. Diagnostics are redacted by default; raw display requires host and field permissions. Similarity does not infer identities, merge people or expand nicknames. All new predicates also work in conditional aggregates and with existing grouping, HAVING and windows. Examples 18–28 are runnable against synthetic matching data. RapidFuzz is a required MIT-licensed core dependency; FastMCP and Inspect AI remain optional.

Regex/fuzzy and requested matching diagnostics automatically use the bounded worker by default. Keep the documented Windows __main__ guard. Trusted benchmarking can explicitly disable force_matching_isolation; untrusted hosts should retain it. No search API or separate matching tools are needed.

## Bounds and deployment

Defaults are declared in `Limits` and returned by `engine.capabilities()`: 8 MiB input, 100,000 rows, 256 paths, depth 12, 128 KiB per record, eight named bindings per context and eight active snapshots per principal in a shared store, 64 MiB admitted storage per store, 900-second leases, 64 KiB YAML, 10,000 groups/windows/distinct values, overlap at most 12, 500 result rows and 1 MiB results. Queries share owner quotas within a store (120/minute, two concurrent executions). Hosts may tighten limits; requests cannot change them.

The default SDK runs inside a **trusted host process**. Use `AnalyticsEngine(isolated=True)` for untrusted execution: a fresh worker has a 15-second wall deadline, CPU ceiling and 1 GiB absolute memory ceiling (POSIX address-space rlimits / Windows Job Object commit limits). Linux Polars needs native virtual mappings beyond 512 MiB even for small numeric queries; measured additional RSS is much lower. Use a `__main__` guard around executable application entry points on Windows. Parsing and bounded snapshot admission remain in the host process. Containers additionally control network/filesystem privileges; see [security](SECURITY.md) and [architecture](docs/architecture.md).

V1 evaluates one snapshot per query. It rejects joins, unions, continuous queries, external sources/sinks, SQL, UDFs, unbounded regex and executable expressions. Dense windows are supported only without grouping, with a bounded grid. In-flight executions keep their admitted snapshot; unregister blocks subsequent name resolution. Foreign-context names and unknown names receive the same unknown-name error. Scope failures receive ACCESS_DENIED.

## MCP

The YAML parser, typed query models, semantic planner and execution engine belong to the core library. They do not import FastMCP or Inspect AI. A developer can expose the SDK using any MCP implementation or another transport:

```python
from xp_libs_analytics import AnalyticsEngine

# Construct per trusted application principal; do not accept identity from agent arguments.
analytics = AnalyticsEngine()
analytics.register_records("observations", [{"value": 2}, {"value": 4}])


def query_tool(query_yaml: str) -> dict:
    return analytics.query_yaml(query_yaml)


def validation_tool(query_yaml: str) -> dict:
    return analytics.validate_query(query_yaml)
```

Register those callables with your chosen server. Select the authorized execution context and identity in the host, enforce transport authentication, and use `isolated=True` for untrusted execution. The bundled FastMCP adapter is an optional convenience layer.

```sh
xp-libs-analytics --help
xp-libs-analytics                 # stdio; uploads disabled
xp-libs-analytics --allow-uploads # bounded local uploads
```

Tools: `analytics_capabilities`, `analytics_list_datasets`, `analytics_load_json`, `analytics_describe`, `analytics_validate_query`, `analytics_explain_query`, `analytics_query`, `analytics_unregister_dataset`, `analytics_error_info`. Query tools accept `query_yaml: str`. Core imports do not load FastMCP.

The local stdio server inherits its launcher's authority; one process is one local context. The default backend uses isolated workers. HTTP access fails closed unless a host supplies an authenticated `principal_resolver` and configures FastMCP transport authentication. A host-supplied `engine` deliberately selects that engine's context for local use. Hosted sessions can supply `context_resolver`, a trusted callable returning their authorized engine/context. No tool accepts a context ID or principal. The identity resolver creates distinct namespaces per authenticated principal and reapplies current field/scopes policy per request. The adapter caps cached principal contexts at 128; restarting clears local state. It is not a turnkey public multi-tenant service.

## Development and evidence

Optional real-model evaluations use Inspect AI and the actual MCP adapter. From this checkout, install `python -m pip install -e '.[dev,mcp,agent-eval]'`, then run `python -m evals.agent_skill.cli validate`. Live evaluation accepts the model connection only at execution time; see [evaluation usage](evals/agent_skill/README.md). Normal CI runs offline evaluator tests and excludes live model tests.

```sh
python -m pip install -c requirements-lock.txt -e '.[dev,mcp,agent-eval]'
ruff check .
ruff format --check .
mypy src/xp_libs_analytics
pytest --cov=xp_libs_analytics --cov=evals.agent_skill --cov-branch --cov-report=json --cov-report=xml --cov-fail-under=90
python scripts/check_critical_coverage.py coverage.json
python examples/run_examples.py --all
python scripts/resource_probe.py
python scripts/benchmark.py
python -m build
python -m twine check dist/*
```

[Verification evidence](docs/evidence/verification.md) records actual local tests, coverage, benchmarks, audit and build hashes. GitHub checks, protected environments and TestPyPI/PyPI publication require maintainer configuration; this checkout makes no publication claim. See [releasing](docs/releasing.md).
