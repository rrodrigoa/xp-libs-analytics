# Changelog

## 0.5.0 — Parameterized registered queries

- Add key-only MCP execution for host-registered YAML or typed queries. Add a typed SDK entry point that bypasses YAML parsing while retaining snapshot planning and authorization.
- Bind strict runtime parameters into fixed YAML value positions and support host-owned Polars transformations over authorized projections.
- Expose parameter schema discovery and optional generated MCP tools. Support native execution in the OS-limited worker using a host-provided transformation registry.


## 0.4.0 — Bounded string and fuzzy query matching

- Extend analytics.query/v1 with explicit Unicode/trim/casefold normalization, not_contains, Unicode word boundaries, LIKE/ILIKE, Rust regex and exhaustive RapidFuzz ratio/wratio/token_sort predicates.
- Add strict disjoint multi-field match nodes shared by filters and every conditional aggregate; preserve typed datetime/numeric comparisons, all 20 aggregates, grouping/HAVING/ordering and temporal semantics.
- Prevalidate Rust syntax with Polars, enforce authorized fields and candidate/comparison/normalization/expanded-AST budgets, and use native Polars membership without Python row UDFs or persistent value caches.
- Default regex/fuzzy/diagnostics to OS-limited workers. Rank optional privacy-cleared matching evidence independently of aggregates; raw values require explicit host and field disclosure policy.
- Add 11 MATCH_* canonical error distinctions (73 total), preserve catalog-only messages, and explicitly reject entity/alias/identity inference.
- Add 11 runnable YAML examples (28 total), a full matching resource/skill, deterministic security/property/integration tests and 11 optional agent evaluation recipes (116 total). Live model ID and endpoint are runtime-only.
- Require MIT-licensed RapidFuzz >=3.14.6,<3.15; preserve optional FastMCP/Inspect separation. Keep the 0.3.0 named registry API, without reintroducing legacy dataset handles or a search prerequisite.


## 0.3.0 — Named context-local dataset sources (breaking)

- Replace dataset.handle with dataset.name and query_yaml(handle, text) with query_yaml(text). No handle-based compatibility API remains.
- Add DatasetRegistry, explicit register_records(name, records), atomic replace_records, list_datasets, unregister_dataset, independent create_context namespaces and safe closure.
- Keep opaque IDs internal; snapshot leases retain running queries through replacement/removal and keep retired storage charged until safe reclamation. Revisions do not repeat within a context; expected_revision rejects stale writes.
- MCP adds analytics_list_datasets, requires names for describe/uploads/unregister, removes analytics_release_dataset, and supports trusted context_resolver. Authenticated policy changes retain namespace identity while rechecking permissions.
- Replace DATA_HANDLE_UNKNOWN / DATA_HANDLE_EXPIRED / RESOURCE_HANDLES_LIMIT with DATASET_NAME_UNKNOWN / DATASET_SNAPSHOT_STALE / RESOURCE_DATASETS_LIMIT. Add DATASET_NAME_DUPLICATE and DATASET_NAME_INVALID: 62 canonical codes total.
- Update every YAML example, schema, product skill, evaluator and developer reference. Reserve register_stream with explicit unsupported-feature rejection; no streaming implementation.

## 0.2.0 — local build

- Rename the distribution/CLI to `xp-libs-analytics` and imports to `xp_libs_analytics`.
- Preserve the independently usable YAML analytics core and optional FastMCP adapter. Add a custom MCP adapter example and an import isolation regression test.
- Add optional Inspect AI agent evaluations, deterministic scenario/oracle contracts, real MCP recovery seeding, semantic/result scorers, memory-only Inspect logs, sanitized reporting and skill/baseline comparison.
- Add 105 synthetic scenarios and offline/live test separation. Live results are recorded separately from deterministic test evidence.

## 0.1.0 — local build

- Implement JSON/NDJSON/mapping admission, full-snapshot discovery, immutable owner-scoped handles, field visibility and shared quotas.
- Implement restricted YAML, strict discriminated Pydantic models, semantic authorization, immutable cost plans, and fixed Polars compilation.
- Support all 19 predicate/logical operators and 20 aggregates, UTC ranges, tumbling/sliding windows, HAVING, stable sorting, and quality evidence.
- Preserve the 60-code canonical catalog; include structured errors and YAML locations.
- Add optional standalone FastMCP tools, upload policy, launcher/authenticated-host identity, and packaged skill/examples.
- Add independent oracle, property/security/agent-workflow tests, real MCP/stdio integration, OS-limited workers, benchmarks, distribution smoke and release workflows.
- Public GitHub/TestPyPI/PyPI release is not configured or performed.
