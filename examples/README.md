# Runnable YAML examples

Install the local package with `python -m pip install -e '.[dev,mcp]'`, then:

```sh
python examples/run_examples.py --list
python examples/run_examples.py --lint-only
python examples/run_examples.py --query 03_group_stats_and_topk
python examples/run_examples.py --all
```

`--lint-only` applies the restricted parser and strict Pydantic AST. `--all` additionally registers synthetic records, registers them under example_data, semantically validates and executes every query, and unregisters each binding. Runtime errors fail the runner.

Each query is a complete document. `dataset.name: example_data` selects the logical name registered by the runner. You can run the same YAML unchanged after registering your own records as example_data. No internal ID is injected into YAML. Inputs are `data/events.json`, equivalent `events.ndjson`, `mixed_types.json`, and `matching_events.json`. Fields are illustrative discovered paths, never built-in business rules.

| Example | Behavior |
|---|---|
| 01_count_all | Count the snapshot |
| 02_filter_and_count | Equality and valid sample count |
| 03_group_stats_and_topk | Grouping, mean/P95, ranking |
| 04_nested_or_predicates | Logical OR |
| 05_is_missing | Original absence |
| 06_missing_vs_null | Missing/null reconciliation |
| 07_conditional_aggregation | Conditional count/mean |
| 08_ratio_if | Fraction over eligible samples |
| 09_tumbling_window | Epoch-aligned five-minute UTC windows |
| 10_sliding_window | Overlapping windows |
| 11_explicit_cast | Numeric conversion |
| 12_text_range_distinct | Literal text/range/distinct |
| 13_summary_statistics | Sum, sample variance, median |
| 14_nested_and_not | Nested logic and membership |
| 15_conditional_sum | Conditional sum |
| 16_mixed_types_cast | Heterogeneous numeric/string values |
| 17_relative_last_hour | Injected server-clock relative interval |

The fixed events fixture has 12 records, 10 numeric `/value` observations, one explicit null and one missing value. Region `west` has six records and five valid values. There are four error-status records, three with valid values; their average is 140. The fraction of valid `/value` observations greater than 100 is 0.3. The fixed tumbling-window counts are 5, 3, 1, 1, 1, 1. Mixed-types cast mean is 7.25.

Tests verify these facts and run every example through the SDK and a real FastMCP Client. Absolute-time examples are deterministic. Relative time uses the actual server clock and can correctly yield `NO_DATA`; tests inject a fixed UTC clock. Empty results do not imply healthy/zero measurements. Overlapping windows reuse source observations.

MCP clients read `analytics://skill/generic-analytics`, list context-local dataset names, describe a selected name, author YAML, validate, optionally explain, execute, interpret evidence and unregister only when permitted. Resources `analytics://examples/index` and `analytics://examples/<filename.yaml>` contain the same allowlisted queries. No resource accepts a user filesystem path.


## Matching examples (0.4.0)

The matching fixture has 28 synthetic records, two services, explicit null/missing name paths, distinct fictional actors sharing Peter, Unicode forms, metacharacters and a record at the excluded 10:10 UTC boundary. It is the same dataset as tests/fixtures/matching_events.jsonl. Identity is never inferred.

| Example | Expected aggregate over the bundled fixture |
|---|---|
| 18_string_exact | events=2 |
| 19_string_normalization | events=12 |
| 20_prefix_suffix | events=9 |
| 21_whole_word | events=10 |
| 22_ilike | events=12 |
| 23_rust_regex | events=4 |
| 24_fuzzy | events=4 |
| 25_multi_field_matching | events=11; duplicate field/rule hits count once |
| 26_conditional_fuzzy | all_events=28, matching_events=4 |
| 27_temporal_fuzzy | 10:00 UTC alpha: events=1, p95_latency=3; beta: events=1, p95_latency=2 |
| 28_safe_matching_diagnostics | events=4; two redacted diagnostic entries, diagnostics truncated, predicate complete |

```sh
python examples/run_examples.py --query 24_fuzzy
python examples/run_examples.py --query 27_temporal_fuzzy
python examples/run_examples.py --query 28_safe_matching_diagnostics
python examples/run_examples.py --lint-only
python examples/run_examples.py --all
```

RapidFuzz is installed with the core. Regex/fuzzy/diagnostic queries use the bounded worker by default. The runner has a main guard for Windows. Raw diagnostics remain disabled; top_values never limits aggregate input. Read docs/string-matching.md or the MCP resource analytics://string-matching/v1 for normalization, boundaries, scoring, error repairs and disclosure policy.
