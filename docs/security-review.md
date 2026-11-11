# End-to-end security review for V1

XP Libs Analytics executes bounded snapshot queries over JSON records. The host controls which records enter the engine, which context handles each request, and what that context can read. YAML expresses the query. The Python SDK enforces the same query contract for direct callers and callers using the optional MCP adapter.

```text
Trusted host ── records ──► bounded admission ──► immutable snapshot
     │                                                  │
     └──────── context, permissions and limits ───┐     │
                                                   ▼     ▼
Caller ── YAML via SDK or MCP ──► parse and type ──► authorize and plan
                                                          │
                                                    approved plan
                                                          ▼
Caller ◄── bounded JSON or coded error ◄──────────── execute
```

The review covers these boundaries from admission through response, as well as tool and release permissions. Executed tests and OS probes are recorded in [verification evidence](evidence/verification.md).

- YAML is byte/event/depth/node/collection/scalar bounded before construction. Tags, directives, anchors, aliases, merges and duplicate keys are rejected. Scalar resolvers are isolated from global PyYAML behavior. Query keys cannot introduce SQL, code, plugins, host paths or network sources.
- Strict disjoint AST variants forbid unused and unknown fields. Public errors use only the packaged catalog. Invalid unknown-key locations are redacted; parser excerpts, records and backend exception strings are never returned.
- Snapshots copy admitted records, preserve missing versus null and examine all rows for typing/casts. Integer precision/overflow and nonfinite results are checked. Opaque internal column names prevent output alias collisions. Casting precedes WHERE and cannot bypass field permissions.
- Ownership is enforced for dataset discovery, description, query validation, planning, execution, and unregistering. Hidden and nonexistent paths are indistinguishable for field-restricted principals. Dataset names outside the current context are indistinguishable from unknown names. The engine applies the host's current policy without mutating shared request authority.
- Input bytes, rows, paths, record size, recursion, store bytes, handle count, result bytes, groups, distinct cardinality, windows, overlap and expanded rows have explicit budgets. Quotas/concurrency are shared by owner across SDK views of the same store. A low result limit cannot bypass planning.
- Workers have OS CPU/memory ceilings and parent-enforced deadlines; native abort/pipe loss returns a canonical error. Windows Job Object and POSIX rlimit adapters have fail-closed API tests. OS probes demonstrate memory denial and CPU termination; host/container restrictions remain necessary for host-side admission and egress.
- Default MCP local identity follows launcher authority under modern per-request connections. Default HTTP data operations fail closed. Authenticated remote hosting requires a trusted resolver and transport authentication; this package does not claim to configure an identity provider. Upload is disabled by default. Resource names are an allowlist, with no caller filesystem routing.
- Observability hooks contain only IDs/hashes/status/timing, never records, query text or field values. Hook failures cannot change query outcomes. The package performs no default payload logging.
- CI does not use `pull_request_target`. Actions are commit-pinned. Only protected release jobs have OIDC write authority; TestPyPI promotion compares wheel bytes and checks hashes before PyPI. Account-level protection still requires maintainers.

The evidence for this review comes from source inspection and local tests. The deterministic agent suite verifies tool workflows and result handling. Live model accuracy, internet-facing authentication deployments, and independent penetration testing fall outside this review. Exact decimal arithmetic, continuous queries, and multi-input execution fall outside V1.
