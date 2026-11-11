# Local verification: xp-libs-analytics 0.2.0

Recorded 2026-11-06 from a local build using Python 3.12.14 on Windows. Earlier evidence is in [verification-v0.1.md](verification-v0.1.md).

## Delivered behavior

The distribution and console command are `xp-libs-analytics`; the import is `xp_libs_analytics`. The obsolete import/distribution was replaced. Restricted YAML parsing, typed validation, planning and snapshot execution remain in the independent core. FastMCP is an optional adapter; Inspect AI is optional developer tooling. A subprocess regression blocks all MCP/evaluator imports and still executes a real YAML query. Fresh core-only artifact installs also execute queries without FastMCP installed.

The optional evaluator uses Inspect AI 0.3.287 (MIT), OpenAI Python 3.46.0 (Apache-2.0) and existing FastMCP 4.1.6 (Apache-2.0). Inspect supplies its native ReAct agent, MCP client, Task runner and custom scorer API. There is no custom model tool loop or LLM judge. The real product server and canonical error catalog are used unchanged by the evaluation host.

Added `evals/agent_skill/`: strict scenario definitions, synthetic fixtures, deterministic generation/variations, actual MCP host, real seeded recovery, semantic/result scorer, privacy guard, allowlisted reports, CLI and documentation. Added offline evaluator tests, opt-in live tests and core import-separation regression. Updated namespace references, metadata, skill/examples, CI/release workflows, dependency inventory and notices. Creation blueprints remain removed; product contracts and operational documentation remain.

## Executed checks

| Check | Actual result |
|---|---|
| Full Windows offline suite | 630 passed; 5 live cases deselected; 89.56 seconds |
| Full Linux Docker offline suite | 630 passed; 5 live cases deselected; 72.61 seconds; two CPUs, 2 GiB memory, 128 PID limit |
| Test inventory | 394 core/product tests and 236 evaluator tests |
| Ruff lint and formatting | Passed, 96 Python files |
| Strict mypy | Passed, 15 core source modules |
| All query examples | 17 restricted-parser/AST validations and 17 SDK executions passed; actual MCP examples also exercised by the full suite |
| Scenario validation | All 105 definitions and their SDK oracles passed |
| Dependency consistency/audit | `pip check` passed; audit found zero known dependency vulnerabilities; unpublished local project skipped by audit |
| Wheel/source distribution | Built and twine validated; each installed into a fresh environment and executed a real query/resource smoke check |
| Optional MCP wheel extra | Fresh installation and server construction passed |
| Container | Renamed production image built; nonroot isolated query passed with no network, read-only filesystem, dropped capabilities, no-new-privileges, 1 GiB memory, two CPUs and 128 PIDs |

The core suite retains all 19 predicate/logical operators, all 20 aggregates, all 60 catalog codes and the Y01–Y26 YAML boundary tests. The independent Python reference oracle and deterministic Hypothesis tests remain active. MCP integration uses real clients, not mocked analytics responses. Hosted CI and Python 3.13/3.14 matrix runs have not been executed locally for this release.

Linux emitted 11 upstream Inspect retry deprecation warnings (`initial` will become `multiplier`); no test failures occurred. The package-name probes returned HTTP 404 for both PyPI and TestPyPI at the recorded check time; this does not reserve the name or prove ownership.

## Coverage

Branch measurement is enabled. Combined statement/branch coverage is **97.59%**. Machine-readable evidence: `coverage-v0.2.json`, `coverage-v0.2.xml`, `tests-v0.2.xml`.

| Scope | Statements | Branches |
|---|---:|---:|
| Core | 1514/1541 = 98.25% | 462/476 = 97.06% |
| Optional evaluator | 780/796 = 97.99% | 206/222 = 92.79% |
| Combined | 2294/2337 = 98.16% | 668/698 = 95.70% |

Every critical core module independently passes the existing 95% gate: ingestion 98.68%, policy/models/worker/errors/parser 100%, backend 97.32%, planner 98.73%. No new coverage exclusions were added.

## Live model evidence

Runtime-only connection discovery found a tool-capable `gpt-oss:120b`. Native model tool preflight and actual analytics MCP discovery passed. No service address or credential is recorded here or in reports.

| Scenario | Mode | Outcome | Episode seconds |
|---|---|---|---:|
| aggregate-count | skill | PASS | 71.0 |
| aggregate-count | baseline | PASS | 49.9 |
| sales-aggregate-001 | skill | PASS | 53.3 |
| recovery-unknown-field | skill | PASS | 33.9 |
| adversarial-command | skill | PASS | 11.2 |
| recovery-unknown-field, final runner confirmation | skill | PASS | 71.9 |

All six successful episodes report zero infrastructure errors and zero security violations. The sales query returned east=250 and west=400. Seeded recovery executed an actual unknown-field failure, then the model discovered the schema and computed mean=27.5. Baseline/skill comparison works, but one paired recipe does not establish an improvement from the skill.

Two earlier smoke runs failed overly strict rubric checks: one required schema discovery for a field-free count; another rejected supporting quality aggregates and nonbinding ordering despite correct semantics/results. The recovery recipe now requires a field-dependent mean, and general semantic equivalence permits harmless quality columns and ordering. Regression tests cover these cases; successful real reruns are above. Original failed reports were retained locally rather than relabeled.

Reports/traces are ignored, excluded from distributions and passed through endpoint/credential redaction and a final privacy assertion. Inspect raw logs use a deleted in-memory recorder, with realtime disk buffering, raw API logging, checkpoint and control services disabled. Tests assert that no SQLite sample spool is created. This is a smoke sample, **not measured accuracy across all 105 recipes**.

## Scenario inventory and limits

46 positive, 21 negative, 8 temporal, 11 seeded recovery, 16 adversarial and 3 skill-comparison recipes. Repetitions vary wording and, for supported analytical recipes, field names in records/prompts/oracles together. Paired modes receive the same variant. Recovery uses actual engine errors; framework errors remain distinguishable from canonical codes. Unauthorized retries and unknown tools are hard safety failures. Agents have bounded turns, actual tool invocations and wall time.

Free-form prose claims are outside the deterministic scorer; quantitative final answers use an explicit JSON contract. Automatic model paraphrasing, cross-version benchmarking and broader adversarial frameworks are future work. Runtime provider compatibility is verified only for the pinned integration and sampled model. Standard CI excludes live tests and needs no endpoint/GPU.

## Performance and resource evidence

Actual host: Windows 11, Intel64 Family 6 Model 198, 24 logical CPUs, 63.5 GiB RAM. Nine samples/query; trusted in-process execution includes parsing/type/cost planning, excludes admission. The first count includes cold Polars import. These are host measurements, not an SLA.

| Rows | Query | Ingest ms | p50 ms | p95 ms | Peak RSS MiB |
|---|---|---:|---:|---:|---:|
| 1,000 | count | 5.77 | 1.59 | 252.16 | 60.89 |
| 1,000 | grouped | 5.77 | 4.81 | 22.77 | 65.27 |
| 10,000 | count | 66.65 | 12.72 | 26.36 | 78.43 |
| 10,000 | grouped | 66.65 | 22.29 | 43.28 | 81.34 |
| 100,000 | count | 798.39 | 196.42 | 212.90 | 198.22 |
| 100,000 | grouped | 798.39 | 281.80 | 312.23 | 226.13 |

`benchmarks.json` contains precise results. All seven resource probes passed expected rejection/termination checks: YAML depth, input width, group limit, overlap, distinct cost, memory ceiling and CPU termination. Artifact hashes and fresh-install outcomes are in `distributions.json`.

## Reproduce

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
python scripts/benchmark.py
python -m pip_audit
python -m build --no-isolation
python -m twine check dist/*
python scripts/verify_dist.py
python -m evals.agent_skill.cli preflight --model gpt-oss:120b
python -m evals.agent_skill.cli run --model gpt-oss:120b --suite recovery
python -m evals.agent_skill.cli compare --model gpt-oss:120b --scenario aggregate-count
```

Live commands prompt privately for connection settings; see the evaluator README for runtime variables and opt-in pytest. No TestPyPI/PyPI upload has been made, no name is reserved, and publishing environments/OIDC remain maintainer configuration.
