# Local verification: agent-analytics-mcp 0.1.0

Recorded 2026-11-06T17:53:04.382140+00:00. No Git commit SHA exists: this folder is not a Git checkout. StreamSQL was not modified or needed.

## Outcome and scope

Working local V1 package, Python SDK, strict YAML/Pydantic boundary, authorization/cost planner, fixed Polars backend, isolated workers, optional standalone FastMCP tools/resources, complete agent skill, synthetic examples and distribution artifacts. The implementation contains all 19 predicate/logical operators and all 20 aggregates. Interfaces for sources, sinks, ports and query definition/execution remain snapshot-only extension seams.

Creation blueprints were removed: AGENTS.md, CODEX_PROMPT.md, ARCHITECTURE_AND_EXECUTION_PLAN.md, TEST_AND_RELEASE_GATES.md and PYPI_PUBLISHING.md. Language, YAML security and error contracts were retained as product reference docs under docs/. Operational release instructions were rewritten as docs/releasing.md. No instruction-only scaffolding test remains.

## Executed checks

| Check | Actual local outcome |
|---|---|
| Windows Python 3.12.14 | 393 passed, 0 failed/errors/skipped; 13.834 seconds |
| Linux Docker Python 3.12.16 | 393 passed, 0 failed/errors/skipped; 13.731 seconds |
| Ruff lint + format | Passed; 61 files formatted/checked |
| Strict mypy | Passed; 15 source modules |
| Restricted YAML + AST examples | 17 passed |
| Complete SDK + actual FastMCP example executions | All 17 passed through each interface |
| MCP | 8 tools, 20 resources, real client, stdio, launcher ownership, trusted host resolver/revocation |
| Canonical catalog | All 60 codes: enum parity, exact envelopes and real MCP error lookup |
| YAML gates | Y01-Y26 behaviors exercised across parser, SDK, ownership, MCP and example tests |
| Dependency audit | 0 known findings after updating project-environment pip to 26.3 |
| Wheel + sdist | Built, twine validated, independently installed in fresh environments, actual YAML query passed |
| Core-only import | Passed without importing FastMCP |
| Optional MCP | Fresh wheel extra installed and server construction passed |
| Packaged resources/notices | Catalog, skill, all 17 examples, full language reference and third-party notices verified |
| Reproducibility | Wheel and sdist hashes match a repeated build from the same final sources/environment |
| Container | Built; nonroot, read-only root, no network, dropped capabilities, no-new-privileges, bounded CPU/memory/PIDs: isolated numeric query passed |

Commands executed from the repository root (using the project Python 3.12 environment):

```sh
python -m ruff check .
python -m ruff format --check .
python -m mypy src/agent_analytics
python -m pytest -q --cov=agent_analytics --cov-branch --cov-report=json --cov-report=xml --junitxml=docs/evidence/tests.xml
python scripts/check_critical_coverage.py coverage.json
python examples/run_examples.py --lint-only
python examples/run_examples.py --all
python scripts/resource_probe.py
python scripts/benchmark.py
python -m pip_audit --format json --output docs/evidence/pip-audit.json
python -m build --no-isolation
python -m twine check dist/*
python scripts/verify_dist.py
python -m build --no-isolation --outdir build/repro2
docker build -t agent-analytics-local-test .
```

Linux tests ran inside Docker with 1 GiB container memory, two CPUs and 128 PIDs, with current source/tests/scripts mounted and an editable constrained install. JUnit and coverage are stored alongside this report. The hardened runtime query separately passed with `--network none --memory=1g --cpus=2 --pids-limit=128 --read-only --tmpfs /tmp:rw,size=32m --cap-drop ALL --security-opt no-new-privileges` as the image's nonroot user.

## Test inventory

| Test module | Passing cases per OS |
|---|---:|
| test_agent_workflows | 22 |
| test_contracts | 11 |
| test_edge_cases | 7 |
| test_ingest_policy | 28 |
| test_mcp | 6 |
| test_operations | 127 |
| test_packaging_contract | 1 |
| test_security | 15 |
| test_telemetry | 1 |
| test_time | 14 |
| test_validation | 116 |
| test_worker_limits | 5 |
| test_workflows | 1 |
| test_yaml_security | 39 |

Property tests include deterministic Hypothesis examples for reconciliation, shuffle invariance, quantile monotonicity, and YAML fuzzing. Operator outputs are compared with an independent Python oracle. The agent suite comprises deterministic tool workflows and repair fixtures; it is not a live language-model accuracy evaluation.

## Coverage

| Scope | Line coverage | Branch coverage |
|---|---:|---:|
| Windows | 98.25% (1514/1541) | 97.06% (462/476) |
| Linux | 98.25% (1514/1541) | 97.06% (462/476) |

Each critical executable module independently passes >=95% branch coverage (branchless modules: >=95% statements). No custom coverage exclusions were added. Windows critical coverage:

| Module | Measured gate |
|---|---:|
| src/agent_analytics/engine/backend.py | 97.32% (109/112) |
| src/agent_analytics/engine/planner.py | 98.73% (156/158) |
| src/agent_analytics/engine/worker.py | 100.00% (8/8) |
| src/agent_analytics/errors/__init__.py | 100.00% (16/16) |
| src/agent_analytics/errors/codes.py | 100.00% (62/62) |
| src/agent_analytics/ingest/__init__.py | 98.68% (75/76) |
| src/agent_analytics/models/__init__.py | 100.00% (10/10) |
| src/agent_analytics/parser/__init__.py | 100.00% (66/66) |
| src/agent_analytics/policy/__init__.py | 100.00% (41/41) |

## Performance and resource evidence

Actual host: Intel64 Family 6 Model 198 Stepping 2, GenuineIntel; 24 logical CPUs, 63.5 GiB RAM; Windows-11-10.0.26200-SP0. Nine samples per query. Latency includes restricted parsing, type/cast/cost planning and execution over an already admitted snapshot; ingestion is measured separately. The first count benchmark includes cold Polars import. This is a different host from the proposed 8-CPU/16-GiB reference; these measurements are not an SLA.

| Rows | Query | Ingest ms | p50 ms | p95 ms | Peak RSS MiB | Additional peak MiB |
|---:|---|---:|---:|---:|---:|---:|
| 1000 | count | 5.74 | 1.71 | 235.42 | 60.07 | 21.28 |
| 1000 | grouped | 5.74 | 3.92 | 6.04 | 64.72 | 25.94 |
| 10000 | count | 59.38 | 11.80 | 21.76 | 76.89 | 12.09 |
| 10000 | grouped | 59.38 | 19.05 | 29.43 | 80.09 | 15.29 |
| 100000 | count | 742.05 | 176.86 | 201.78 | 197.43 | 118.83 |
| 100000 | grouped | 742.05 | 270.03 | 286.63 | 226.27 | 147.67 |

OS probes use their own explicit 512-MiB memory and one-second CPU ceilings, with a four-second parent deadline. They rejected deep YAML, a 100k-key schema, excessive groups/distinct values and window overlap; a 1-GiB allocation was denied and a busy loop was terminated by the OS. See resource-probes.json for actual wall time, RSS, exit codes and outcomes. Default analytical workers use a 1-GiB memory ceiling because a 512-MiB Linux address-space ceiling rejected native Polars mappings even for a tiny numeric query. This virtual/commit ceiling differs from measured resident memory.

## Build artifacts

| Artifact | SHA256 |
|---|---|
| [agent_analytics_mcp-0.1.0-py3-none-any.whl](../../dist/agent_analytics_mcp-0.1.0-py3-none-any.whl) | `cebdd001f8593f759e45ae91a9ba3d7ee2fc79a635e4e96b3a2e198e4333504a` |
| [agent_analytics_mcp-0.1.0.tar.gz](../../dist/agent_analytics_mcp-0.1.0.tar.gz) | `59e20437de7425b0257b8c4f8533237dccabfe5f01beb1a2f5392ad7526e6c86` |

The final `distributions.json` hashes match the exact artifacts smoke-tested. Both repeated builds matched (`reproducibility.json`). SBOM, resolved versions/license metadata and audit results are in this directory; dependency constraints are in `requirements-lock.txt`. The unpublished local project itself is skipped by the vulnerability index; its source is covered by local tests/review. Installed dependency license metadata is recorded without claiming legal certification.

## Publication, governance and remaining limits

- Local artifacts: built and verified. TestPyPI/PyPI: no uploads or publication. Both proposed project-name JSON endpoints returned 404 at the recorded check; availability/control is not reserved or guaranteed.
- GitHub: no repository, hosted CI run, branch protection, CODEOWNERS identities, environment reviewers or OIDC Trusted Publishers were configured. Workflow definitions and permission/pin contracts pass local tests. CodeQL/dependency review were authored but were not run as hosted services.
- Python 3.12 on Windows/Linux was executed. The 3.13/3.14 CI matrix is prepared but was not locally executed.
- Remote HTTP hosting must provide actual authentication and a trusted identity resolver. Defaults fail closed. Host-supplied engines deliberately share host authority; modern local stdio uses launcher authority. No live public authentication deployment was tested.
- The SDK default is trusted in-process execution. Use isolated workers and constrained hosting for untrusted workloads. Parent parsing/admission remains in the host. Worker limits are hard OS limits; the package does not install host/container security policies automatically.
- Snapshot-only: no joins, multi-input plans, continuous processing, arbitrary sources/sinks, SQL, UDFs or exact decimal analytics. Dense windows are bounded and ungrouped. Sparse counts do not establish durations or cadence.
- The optional adapter bounds cached principal configurations at 128; it is an embedded/local adapter, not a turnkey multi-tenant service.
- Security contact and index/repository ownership require maintainer configuration before public release. This is a local implementation/security review, not an external certification.

Product implementation areas: parser, typed models/schema, ingestion/store, policy/budgets, immutable planner, Polars compiler, OS worker, SDK/telemetry, optional MCP adapter, extension interfaces, tests, examples/skill, docs/ADRs, pinned workflows, Docker and packaging scripts. Detailed operational and security behavior is documented in README, docs/architecture.md and docs/security-review.md.
