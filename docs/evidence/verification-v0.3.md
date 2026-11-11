# Local verification: xp-libs-analytics 0.3.0

Recorded 2026-11-06 from local validation of 0.3.0, which requires logical dataset names. Earlier evidence is in [verification-v0.1.md](verification-v0.1.md) and [verification-v0.2.md](verification-v0.2.md).

## Implemented contract

- DatasetRegistry binds validated logical names to trusted snapshot-source descriptors. Python variable names and opaque internal snapshot IDs are independent. No registry stores Polars DataFrames or executes source plugins.
- register_records(name, records) rejects collisions; replace_records atomically publishes a fully admitted snapshot; list_datasets discovers authorized metadata; unregister_dataset removes a binding. Failed admission preserves the current snapshot.
- query_yaml(text), validate_query(text), explain_query(text) and query_file(path) accept no separate dataset argument. YAML requires dataset.name. Legacy dataset.handle, old SDK call shapes and the old MCP release tool are rejected/removed.
- Each engine/create_context owns an independent namespace. Contexts can reuse names while sharing host memory and principal request budgets. Server-selected MCP contexts never come from agent arguments. Authenticated principal views preserve namespace identity while applying current field/scope policy.
- Queries pin their resolved snapshot through planning and execution. Replacement, expiry, unregister and context close cannot alter an admitted query. Retired snapshot bytes remain charged until their final reader exits, including exceptions. Context closure cleans all bindings.
- Revisions increase across publications within a context, including unregister/re-register, preventing stale-reference ABA reuse. expected_revision on replace/unregister supports atomic compare-and-swap and rejects mismatched or incorrectly typed revisions.
- Names use 1–64 ASCII letters/digits/underscores/hyphens, starting with a letter. Unknown and foreign-context names return the same DATASET_NAME_UNKNOWN error. Duplicate, invalid and stale bindings have dedicated catalog errors; scope/closed-context failures use ACCESS_DENIED.
- register_stream is an explicit unsupported-feature seam. No streaming, joins or multi-input execution is implied.

Updated SDK, ingestion lifetime accounting, strict YAML models/schema fixture, MCP tools, catalog/enum, 17 YAML examples, runner, skill/references, optional evaluator/scenarios, smoke/benchmark scripts, docs, release metadata and coverage gate. Version is 0.3.0; the catalog has 62 entries. Creation blueprints were not retained in the product.

## Actual validation

| Check | Outcome |
|---|---|
| Windows Python 3.12.14 | 662 passed, 5 live tests deselected, 174.14 seconds |
| Linux Docker Python 3.12 | 662 passed, 5 live tests deselected, 96.50 seconds; two CPUs, 2 GiB, 128 PIDs |
| Ruff lint/format | Passed; final formatting check covered 100 Python files |
| Strict mypy | Passed, 16 core modules |
| Examples | All 17 parsed, typed and executed; real MCP examples exercised by the full suite |
| Evaluation definitions | All 105 validated with name-based SDK oracles |
| Canonical errors | All 62 enum/catalog entries and exact real-MCP error messages verified |
| Core separation | A subprocess blocks all MCP/evaluation imports and executes named YAML; fresh core-only wheel/source installations also passed |
| Build/install | Wheel and sdist built, twine passed, both freshly installed and ran resource/query smoke checks; optional MCP wheel installation constructed a server |
| Reproducibility | Wheel and source hashes match repeated builds |
| Production container | Rebuilt at 0.3.0; a named-dataset isolated query passed as nonroot with no network, read-only filesystem, dropped capabilities, no-new-privileges, 1 GiB, two CPUs and 128 PIDs |
| Dependencies | pip check passed; pip-audit found zero known dependency vulnerabilities, with the unpublished local project skipped |

There are 426 core/product cases (including 30 dedicated registry cases) and 236 offline evaluator cases. Tests retain independent operator/time oracles and Y01–Y26 restricted YAML security coverage. Concurrent tests cover replacement/unregister during actual query execution, nested leases, failed publication under pinned memory pressure, stale compare-and-swap races, discovery racing context close, independent contexts, host policy revocation and rejected agent context selectors. Eleven upstream Inspect retry deprecation warnings were emitted; none failed tests.

## Coverage

Combined statement/branch coverage: **97.62%**. The new registry has **100% statements and branches**. No coverage exclusions were added.

| Scope | Statements | Branches |
|---|---:|---:|
| Core | 1680/1709 = 98.30% | 494/510 = 96.86% |
| Optional evaluator | 780/796 = 97.99% | 206/222 = 92.79% |
| Combined | 2460/2505 = 98.20% | 700/732 = 95.63% |

Every critical module passes its independent 95% gate, including the newly added registry: registry/policy/models/worker/errors/parser 100%, ingestion 97.73%, backend 97.32%, planner 98.10%. See coverage-v0.3.json, coverage-v0.3.xml, tests-v0.3.xml and tests-linux-v0.3.xml.

## Real model execution

Native tool preflight and the production MCP adapter were exercised with runtime-only gpt-oss:120b:

| Episode | Outcome | Seconds |
|---|---|---:|
| aggregate-count, dataset.name contract | PASS | 70.6 |
| recovery-unknown-field, dataset.name contract | PASS | 30.5 |

Both report zero infrastructure errors and zero security violations. Recovery receives an actual canonical engine error, discovers fields by logical name and computes the corrected result. The optional Inspect AI framework and all 105 recipes use the new contract. Full-suite live accuracy has not been measured. Historical handle-based live evidence is not presented as a current-contract run.

Runtime endpoints/credentials were not saved in documentation, reports or artifacts. A persistence scan passed. Reports remain ignored and excluded from wheel/source distributions. Endpoint details appear only in execution-time arguments supplied by the host, not in this evidence. Eval traces use the existing redaction/privacy checks and memory-only Inspect recording.

## Resource and benchmark evidence

All seven actual subprocess probes reached their expected rejection/termination: YAML depth, wide records, group count, window overlap, distinct-cost budget, memory ceiling and CPU termination. See resource-probes.json.

Nine samples per query on Windows 11, 24 logical CPUs and 63.5 GiB RAM. Trusted in-process latency includes parsing/type/cost planning and snapshot resolution; admission is separate. The first count includes cold Polars initialization. Other validation and model processes were active, so these are host measurements, not isolated regression comparisons or an SLA.

| Rows | Query | p50 ms | p95 ms |
|---|---|---:|---:|
| 1,000 | count | 2.56 | 350.21 |
| 1,000 | grouped | 5.19 | 13.04 |
| 10,000 | count | 22.09 | 53.46 |
| 10,000 | grouped | 31.67 | 44.12 |
| 100,000 | count | 462.56 | 486.77 |
| 100,000 | grouped | 648.56 | 689.25 |

Precise admission/RSS values are in benchmarks.json. Hashes and fresh-install results are in distributions.json; repeated build checks are in reproducibility-v0.3.json. The production container was rebuilt for the new contract.

## Commands and limits

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
python -m evals.agent_skill.cli run --model gpt-oss:120b --scenario aggregate-count
python -m evals.agent_skill.cli run --model gpt-oss:120b --scenario recovery-unknown-field
```

Live commands prompt for runtime connection settings. Normal CI requires no model/GPU. Snapshot V1 still executes one input per query; streams, refresh schedulers, computed datasets and multi-output execution are not implemented. Expired bindings are omitted from discovery and must be replaced or unregistered; namespace metadata stays bounded. Local stdio deliberately has one launcher context per process; hosted session/request lifetimes must be managed by the trusted context_resolver. Python 3.13/3.14 matrix and hosted publishing workflows were not run locally. No TestPyPI/PyPI upload occurred.
