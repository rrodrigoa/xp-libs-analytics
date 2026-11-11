# Local verification: xp-libs-analytics 0.4.0

Recorded November 6, 2026 (America/Los_Angeles) from local validation of the 0.4.0 release candidate before its initial commit. Earlier evidence is in `verification-v0.1.md` through `verification-v0.3.md`.

## Implemented changes

- `src/xp_libs_analytics/matching/`: strict matching models, Unicode normalization, bounded LIKE/Rust regex validation, shared Polars expression compiler with exhaustive RapidFuzz scoring, and independently ranked diagnostics. Native dependencies load after worker resource enforcement; no user row UDF or persistent derived-value cache.
- `models/__init__.py`, `engine/planner.py`, `engine/backend.py`, `policy/__init__.py`, `sdk/__init__.py`: integrated source matching everywhere a source predicate is legal, preserved typed comparisons and HAVING alias rules, planned all matching budgets, and kept regex/fuzzy/diagnostics isolated by default. Named datasets retain the 0.3 SDK contract and immutable snapshot leases.
- `errors/catalog.json` and `errors/codes.py`: 11 new distinctions, 73 canonical codes; existing field/type/authorization codes reused. Invalid Rust syntax is rejected before reading snapshot records. Entity inference is explicitly unsupported.
- `mcp/server.py`: nine existing tools remain; capabilities and the new read-only matching reference advertise the extension. There are 32 resources, including all 28 examples. The core remains independent of FastMCP and Inspect AI.
- `examples/queries/18_*.yaml` through `28_*.yaml`, matching JSON/JSONL fixtures, README/skill/references, `docs/string-matching.md` and the deferred-entity ADR: runnable examples and explicit boundary, normalization, budget, diagnostic scope, privacy and recovery contracts.
- `evals/agent_skill/`: 11 additional deterministic recipes; 116 total. Native mocked agents exercise actual MCP matching/repair. The CLI requires a runtime model ID and endpoint; no default model/service address is embedded.
- `tests/matching/`, schema/example inventory tests and worker bootstrap regression; coverage gate, matching benchmark and distribution smoke scripts; CI benchmark evidence; 0.4.0 packaging, lock, notices and SBOM.

The spec was adapted to the existing repository: the named selector already exists, so no legacy handle shim or new search API was added. The existing Polars epoch-aligned window membership implementation was retained rather than replaced with `group_by_dynamic`; regression tests verify half-open bounds, leading partial windows, overlap and sparse-data behavior. Diagnostic frequencies explicitly describe positive leaf hits after all outer filters and before aggregation/window expansion. This narrower scope avoids presenting false conditional provenance.

## Observed verification

| Check | Result |
|---|---|
| Windows Python 3.12.14 | 877 passed, 5 live cases deselected; 144.96 s |
| Linux Docker Python 3.12 | 877 passed, 5 live cases deselected; 155.65 s; 2 CPUs, 2 GiB, 128 PID limit |
| Matching test inventory | 169 cases, including deterministic Hypothesis oracles and real FastMCP integration |
| Ruff lint / format | Passed; 118 Python files formatted |
| Strict mypy | Passed; 22 core modules |
| YAML examples | All 28 validated and executed; the full suite also runs them through actual MCP |
| Agent recipe validation | All 116 definitions and SDK oracles passed; 13 actual seeded MCP recovery errors verified |
| Catalog | All 73 entries checked for enum parity, canonical envelopes and repair examples |
| Resource probes | All seven existing subprocess probes passed; new candidate, comparison, pattern, disclosure and timeout boundaries exercised by tests |
| Dependency consistency/audit | `pip check` passed; zero known dependency vulnerabilities; unpublished local project skipped by audit |
| Wheel / source archive | Built and twine checked; fresh core-only installs executed actual YAML/fuzzy queries and packaged resources; optional MCP wheel smoke passed |
| Reproducibility | Both artifact hashes match byte-for-byte repeated builds |
| Hardened container | Fuzzy query ran as UID 10001 with no network, read-only root, dropped capabilities, no-new-privileges, 1 GiB memory, two CPUs and 128 PIDs |

Coverage was **97.87% combined**, with **2926/2974 statements (98.39%)** and **891/926 branches (96.22%)**. The matching package passed **348/348 statements and 154/154 branches**. Every critical module passes its existing independent 95% gate; matching modules are included with no lowered threshold or new exclusions. See coverage-v0.4.json/xml and tests-v0.4.xml / tests-linux-v0.4.xml.

Polars 2.1.0 and RapidFuzz 3.14.6 were tested. RapidFuzz is MIT-licensed and constrained to the compatible 3.14 series; the original MIT license and dependency attribution are retained. Optional FastMCP 4.1.6, Inspect AI 0.3.287 and OpenAI Python 3.46.0 remain independently installable. The suite emitted 19 upstream Inspect retry deprecation warnings and no test failures. No live LLM invocation was required or run for 0.4.0; five opt-in live tests are excluded from normal CI. Hosted Python 3.13/3.14 checks were not run locally.

## Actual benchmark

Windows 11, Intel Family 6 Model 198, 24 logical CPUs, 63.5 GiB RAM, Python 3.12.14. Nine warmed samples of a 10,000-row synthetic snapshot; query time includes restricted YAML, authorization/type/cost planning and execution. The benchmark explicitly uses the trusted in-process option, so it excludes automatic worker startup. This is a local workload, not an SLA.

| Workload | 0.3.0 p50 ms | 0.4.0 p50 ms | 0.4.0 p95 ms | Fuzzy comparisons |
|---|---:|---:|---:|---:|
| Count | 6.80 | 7.38 | 16.70 | 0 |
| Literal contains | 9.01 | 10.82 | 11.22 | 0 |
| Normalized contains | — | 12.50 | 13.19 | 0 |
| Rust regex | — | 13.17 | 14.59 | 0 |
| Fuzzy | — | 10.59 | 14.62 | 2 |
| Multi-field fuzzy | — | 13.45 | 14.48 | 12 |
| Fuzzy + ranked diagnostics | — | 33.65 | 52.81 | 2 |

The local count/literal regression budget was max(50 ms, three times baseline p50); both passed. The fuzzy workload scores two distinct values, not 10,000 individual rows, and still counts all 5,000 matching rows. Full measurements are in matching-benchmarks-v0.4.json and literal-pre-matching-v0.3.json. The independent pre-extension general workload is in benchmark-pre-matching-v0.3.json.

## Reproduction commands

```sh
python -m pip install -c requirements-lock.txt -e '.[dev,mcp,agent-eval]'
python -m ruff check .
python -m ruff format --check .
python -m mypy src/xp_libs_analytics
python -m pytest -q --cov=xp_libs_analytics --cov=evals.agent_skill --cov-branch --cov-report=json --cov-report=xml --cov-fail-under=90
python scripts/check_critical_coverage.py coverage.json
python -m evals.agent_skill.cli validate
python examples/run_examples.py --lint-only
python examples/run_examples.py --all
python scripts/resource_probe.py
python scripts/benchmark_matching.py --trusted-in-process --compare-baseline docs/evidence/literal-pre-matching-v0.3.json
python -m pip check
python -m pip_audit
python scripts/inventory.py
python -m build --no-isolation
python -m twine check dist/*
python scripts/verify_dist.py
python -m build --no-isolation --outdir build/repro-v0.4
```

Hashes and fresh-install outcomes are in distributions.json and reproducibility-v0.4.json; example results are in examples-v0.4.json. Prior 0.3 artifacts were archived under build/dist-v0.3. Only the current 0.4 wheel and source archive remain in dist. The artifacts exclude runtime reports and evidence. Matching remains snapshot-only: no identity inference, search prerequisite, streams, joins, SQL execution or automatic alias expansion. Host budgets can conservatively reject broad work; no incomplete matching can be reported as a complete aggregate.
