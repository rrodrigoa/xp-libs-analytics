# String matching in analytics.query/v1

Version 0.4.0 adds bounded string predicates to the existing named-snapshot query engine. Query source remains restricted YAML; record input and results remain JSON. Dataset registration, numeric comparisons, null/missing semantics, casts, all 20 aggregates, HAVING and temporal windows keep their existing contracts. No search call is required, and no separate search API is implemented.

## Choosing an operator

| Operator | Meaning |
|---|---|
| eq / ne | Typed equality/inequality; string normalization is optional. Datetime/numeric/Boolean comparisons retain their original typed behavior. |
| contains / not_contains | Literal substring/complement for non-null strings. Percent, dot and star are ordinary characters. |
| starts_with / ends_with | Literal prefix/suffix. |
| word | Literal surrounded by the Rust engine's Unicode word boundaries. |
| like / ilike | Whole normalized value matched with percent/underscore wildcards; ILIKE is case-insensitive. |
| regex | Rust regex search, unanchored unless explicitly anchored. |
| fuzzy | Entire normalized values compared using RapidFuzz ratio, wratio or token_sort. |

Null/missing values yield unknown, including under NOT. WHERE selects only true; conditional counts treat unknown as false. Null is never converted to an empty search string. Arrays and objects are not flattened/stringified for matching. Non-string scalar fields require an explicit approved string cast; mixed values retain the existing cast/type policy. Unknown and hidden paths retain DATA_FIELD_UNKNOWN / ACCESS_FIELD_DENIED behavior.

```yaml
version: analytics.query/v1
dataset: {name: observations}
filters:
  - field: /actor/name
    op: fuzzy
    value: Peter
    algorithm: ratio
    min_score: 85
    normalization: {case_sensitive: false, unicode: nfkc, trim: true}
aggregations:
  - {op: count, as: matching_records}
```

Fuzzy similarity is not probability, confidence or real-world identity. ratio uses normalized Indel similarity; token_sort compares token-sorted strings; wratio includes RapidFuzz's weighting/partial-match heuristics. Processing is explicit: the engine owns normalization and passes processor=None. The inclusive cutoff uses the actual floating-point score without rounding. Only displayed scores are rounded to six decimal places. No nickname expansion, entity merging, identity assignment or inference is available.

## Normalization

Optional normalization has strict keys case_sensitive (default true), unicode (none/nfc/nfkc; default none), trim (default false). Processing order is Unicode normalization, whitespace trim, then Python casefold when case-insensitive. Apply the same processing to search text and candidate values. Records, schema, groups and display values retain their original content.

Casefold can expand characters: Straße equals STRASSE with case-insensitive literal equality, and sharp-s occupies two normalized code points. LIKE underscore counts normalized Unicode code points, including newline, rather than grapheme clusters. Query and candidate length budgets also apply after normalization. Empty contains/not_contains/prefix/suffix/word/fuzzy terms are rejected; typed equality accepts an empty string.

Regex is the deliberate exception: patterns are never Unicode-normalized, trimmed or casefolded. Regex rejects unicode other than none and trim=true. normalization.case_sensitive=false enables Rust's (?i) behavior over original input strings. Regex Unicode case handling follows Rust regex, not full-string Python casefold expansion. Inline i flags, global or scoped, are allowed; other flags, flag disabling, lookaround and backreferences are rejected. Explicit case-sensitive normalization conflicts with an inline i flag. Regex validity is checked with installed Polars, never Python re. Pattern errors use canonical messages without echoing patterns.

Whole-word matching means Unicode regex-engine words: Peter Johnson, Peter-Johnson, Peter's and Peter@example.invalid contain the word Peter; Peterson and Peter_Johnson do not. Combining marks participate in word membership. Han letters are word characters; this is not language-specific tokenization. Normalize explicitly when composed/decomposed spellings should match.

## LIKE escaping and regex

LIKE translates percent to any sequence and underscore to one normalized code point. Backslash escapes only percent, underscore or backslash. Invalid/dangling escapes fail MATCH_PATTERN_INVALID. All literal characters are escaped before translation; generated patterns use absolute A/z anchors and DOTALL so wildcards include newline. Prefer single-quoted YAML for backslashes:

```yaml
filters:
  - {field: /text, op: like, value: 'Pet\%'}  # literal Pet%
```

Peter without wildcards matches the whole value only. '%Peter%' matches a substring. contains with value 'Pet%' treats percent literally. ILIKE forces case-insensitive matching and rejects explicitly case_sensitive=true; normalization may still request NFC/NFKC or trimming. LIKE may explicitly be case-insensitive, but ILIKE expresses that intent more clearly.

Regex supports explicit anchors and classes, for example value: '(?i)^peter[._-]'. Raw patterns are capped at 512 UTF-8 bytes. Generated word/LIKE regex has a separate bounded size derived from the 1024-character literal budget. By default, patterns that match the empty string (such as percent-only LIKE or dot-star regex) fail MATCH_REGEX_POLICY. Trusted hosts can explicitly allow catch-all patterns; result, candidate and execution budgets still apply. Other broad nonempty patterns remain bounded by input and runtime budgets.

## Multi-field predicates and composition

```yaml
filters:
  - match:
      fields: [/actor/name, /actor/email]
      patterns:
        - {op: word, value: Peter}
        - {op: fuzzy, value: Pter, algorithm: ratio, min_score: 85}
      normalization: {case_sensitive: false, unicode: nfkc, trim: true}
      mode: any
```

Fields are 1–10 unique, discovered JSON Pointers. Patterns are 1–10 strict rules: eq, contains, not_contains, starts_with, ends_with, word, like, ilike, regex or fuzzy. Patterns cannot contain field or normalization; normalization belongs to the parent match node. Only mode:any exists. It performs three-valued OR across every field/rule pair, and each record contributes once. Missing-only records remain unknown under outer NOT. Use existing AND/OR/NOT nodes to express other logic; a broad not_contains alternative is not identity exclusion.

The same recursive predicate is accepted in filters and count_if/sum_if/avg_if/ratio_if.where. HAVING still accepts aggregate-output aliases only; source matching and normalization options there are rejected. Grouping uses original source values; output sorting and limits follow aggregation. Time filtering uses existing explicit timestamp casts, one injected UTC clock and half-open bounds. Tumbling/sliding interval names and sparse-data semantics are unchanged.

## Complete selection and bounded execution

The planner authorizes every referenced path before matching, including OR branches. Cast/type validation still examines all admitted rows; a selective filter cannot conceal a bad cast. Time and provably independent nonfuzzy conjuncts may reduce the candidate universe. A child of fuzzy OR/NOT is never pushed down independently. Conditional predicates do not restrict their own aggregate denominator.

RapidFuzz scores every eligible distinct normalized candidate per field. Duplicate values reuse scores inside a query; membership is a typed native Polars expression. Normalization maps are bounded distinct-value mappings, not Python row UDFs. No value/scoring cache survives a query, and resolved snapshot leases survive replacement/unregister. Validation/explain checks syntax, permissions, types, candidate/comparison budgets and normalization without executing RapidFuzz scoring.

| Host limit | Default |
|---|---:|
| Authored predicate nodes / depth | 32 / 4 |
| Expanded match field-rule pairs within node budget | 32, further reduced by surrounding predicates |
| Fields / patterns per match | 10 / 10 |
| Additional global matching work cap | 40, including conditional predicates |
| Raw and normalized search characters | 1024 |
| Candidate string characters, before/after normalization | 1024 |
| Raw regex bytes | 512 |
| Distinct normalized fuzzy candidates per field/configuration | 10,000 |
| Fuzzy comparisons per query, including conditional work | 100,000 |
| Normalized mapping bytes per query | 8 MiB |
| Minimum normalized fuzzy term / similarity | 3 characters / 70 |
| Diagnostic top_values / distinct diagnostic entries | 20 / 10,000 |

These are initial measured defaults, not universal safety guarantees. Hosts can tighten Limits; YAML cannot raise them. Budgets fail with a canonical error, never return a partially scored aggregate. limit and top_values are output-only. Disabling the trusted host's pushdown optimization can increase conservative cost/rejections, but completed selections keep identical semantics. Group/window/expansion/result and owner quotas remain independently enforced.

Regex/fuzzy queries and requested diagnostics automatically use the OS-limited worker by default, even on a normally in-process SDK engine. Use a __main__ guard for executable Windows applications. A trusted host may explicitly disable force_matching_isolation for controlled in-process benchmarking; untrusted deployments should retain it. Planning remains bounded host work; scoring and arbitrary regex scans run within the killable worker. Worker memory/time limits return errors, never partial aggregates.

## Matching diagnostics and privacy

```yaml
options:
  matching_details:
    include: true
    top_values: 10
    include_raw_values: false
```

The optional matching envelope reports used, predicate_complete, versions, comparison counts and cost scope. Detailed evidence is computed from positive matching-leaf hits among rows remaining after ALL outer filters, before grouping, HAVING and window expansion. diagnostic_scope explicitly names this narrower scope. It does not imply conditional-aggregate eligibility or count NOT-complements as positive matches. Each source row is counted once per field/original value, even when multiple rules match. Per-field frequencies are not summed to obtain the query's record count.

Top values report field, frequency, primary match_type, effective normalization, all matched_rules, optional actual fuzzy score/algorithm, and truncation flags. Primary precedence is exact, word, prefix/suffix, contains, LIKE/ILIKE, regex, fuzzy. Negated literal rules share their corresponding family precedence and have explicit negative types. Fuzzy-only entries sort by score descending, frequency descending, normalized value, field path, then original value. There is no fabricated score for literal matches.

By default value is null and value_ref is an HMAC using an internal snapshot-derived secret. References are stable within a snapshot, differ across snapshots/contexts and cannot be reproduced from the raw value alone. Errors/logs do not disclose candidates. Raw output requires BOTH Limits(allow_match_raw_values=True) and Principal.match_raw_fields containing every matching field, in addition to ordinary field authorization. YAML cannot grant this permission. Denied disclosure returns MATCH_DIAGNOSTICS_UNAUTHORIZED.

Diagnostic truncation sets diagnostics_truncated=true and complete=false for diagnostics only. predicate_complete remains true and every selected record still contributes to aggregates. Exceeding diagnostic cardinality or result-byte limits fails explicitly. No diagnostics can silently turn an analytical query into top-N selection.

## Errors and recovery

One catalog remains authoritative. New distinctions are MATCH_PATTERN_INVALID, MATCH_REGEX_INVALID, MATCH_REGEX_POLICY, MATCH_NORMALIZATION_INVALID, MATCH_FUZZY_ALGORITHM_INVALID, MATCH_FUZZY_THRESHOLD_INVALID, MATCH_FUZZY_QUERY_TOO_SHORT, MATCH_CANDIDATE_BUDGET_EXCEEDED, MATCH_COMPLEXITY_BUDGET_EXCEEDED, MATCH_DIAGNOSTICS_UNAUTHORIZED and MATCH_ENTITY_INFERENCE_UNSUPPORTED. Existing field/type/operator/authorization errors are reused. There are 73 catalog entries total.

Use analytics_error_info for exact repair guidance. After invalid Rust syntax, use a supported pattern or literal predicate. After a budget failure, narrow authorized time/nonfuzzy scope only with an explicit statement that the question has changed. Never claim an original-scope aggregate was complete after narrowing. After authorization denial, stop. Entity/alias/identity requests remain unsupported; observed values can resemble each other without belonging to the same person. See examples 18–28 and the agent skill.
