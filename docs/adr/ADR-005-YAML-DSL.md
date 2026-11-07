# ADR-005: Author analytics queries in restricted YAML; compile to a typed AST

- **Status:** Implemented and verified for V1
- **Date:** 2026-11-06
- **Owners:** Engine/Agent API maintainers
- **Affects:** Python SDK, FastMCP tools, agent skill, error mapping, examples, security and release gates

## Context

AI agents need to dynamically author analytical operations on JSON records whose fields are unknown until runtime. Users want a clear declarative DSL without SQL or arbitrary Python. The previous plan used a JSON-authored query object. JSON is structurally unambiguous, but deeply nested filters/window/aggregation queries become hard to read and modify in a skill or code review. YAML provides comments and concise block structure, but creates parser ambiguity and attack surface.

## Decision

- **YAML is the only public query authoring text format for V1.** MCP tools accept `query_yaml: str`, and the Python SDK accepts a YAML string via `engine.query_yaml`. Do not expose `query_json` or raw SQL tool parameters. The public query version literal remains `analytics.query/v1` because operator semantics are unchanged; the `authoring_format: yaml` capability is explicit. If a preexisting deployed JSON-DSL client is ever discovered, it requires an explicit migration/compatibility decision rather than a silent format break.
- **JSON remains the data format and error/result format:** in-memory JSON/NDJSON ingress, result JSON envelope, canonical JSON error mapping file. The content encoding change must not impact those contracts.
- **Only a restricted YAML subset is accepted**, described in `docs/yaml-security.md`. No aliases, anchors, explicit tags, merge keys, multi-document, custom objects or YAML 1.1 implicit bool/date conversion. Strict byte/event/depth/scalar budgets and duplicate-key rejection precede Pydantic.
- **Pydantic remains the typed AST owner.** YAML parse → plain mapping → `AnalyticsQuery.model_validate` with strict discriminated models → auth/cost planner → Polars expression factories. The execution plan is independent of YAML syntax.
- **Agent skill + capability discovery** advertise the authoring format and examples. `analytics_validate_query`/`analytics_explain_query`/`analytics_query` share one parser and error mapper; no weaker alternate path.
- **Version and compatibility:** a normalization-equivalent YAML query must have the same meaning as the original JSON AST, but no user-authored JSON query is required as a public API. Syntax grammar and scalar resolution are versioned compatibility surfaces. Schema snapshots describe the *typed AST*, not YAML parsing itself.

## Consequences

### Benefits

- Less syntactic noise and easier human/agent review for nested query plans.
- Complete runnable `.yaml` examples, comments and a focused `SKILL.md`.
- No SQL parser/privileges and no arbitrary execution escape hatch.
- Existing Polars compiler/operation coverage can remain unchanged.

### Costs / risks

- A hardened parser is required. PyYAML `safe_load` alone is inadequate for this threat model; duplicate keys and YAML 1.1 scalar inference must be explicitly addressed.
- MCP's tool schema can only declare `query_yaml: str`; JSON Schema for the AST is informative, not pre-validated by FastMCP. Agents rely on examples/capabilities plus server error recovery.
- Error mapping and line/column positions need precise, non-leaking diagnostics.
- YAML syntax safety/property/fuzz tests and dependency monitoring add maintenance.

## Rejected alternatives

| Alternative | Reason rejected for public agent DSL |
|---|---|
| Raw SQL (DuckDB, Polars SQLContext) | broader grammar and larger access/execution attack surface |
| JSON-authored DSL | secure but less readable/editable for long nested agent queries |
| Python/UDF expression strings | arbitrary code and unpredictable resource/security boundary |
| General YAML with aliases/tags/merges | complex semantics, implicit typing, parser DoS and object construction risks |
| Templateable YAML (`${}`, Jinja, `!include`) | host file/secret inclusion and syntax/authorization confusion |

## Acceptance

Implementation is accepted only after all YAML-specific Y01–Y26 gates, existing P/N/S/H/I/A gates, packaged examples, MCP tool tests, wheel smoke and error-catalog parity succeed. No exception can be silently swallowed.
