# Matching reference index

Read analytics://string-matching/v1 for the complete contract and examples 18–28 from analytics://examples/index. These resources are allowlisted product documentation, not arbitrary file access. No search call is required before an analytical query.

Use eq for exact observed values; contains/prefix/suffix for literal fragments; word for Rust Unicode word boundaries; ILIKE for percent/underscore whole-value wildcards; regex for bounded Rust syntax; fuzzy for explicit ratio/wratio/token_sort similarity. Normalization is Unicode NFC/NFKC, trim, then casefold, and affects matching only. Regex accepts case handling but rejects Unicode normalization/trimming; never casefold regex syntax.

Fuzzy requires an explicit algorithm and inclusive min_score, normally ratio/85. Default policy requires at least three normalized query characters and score >=70. Every eligible distinct value is scored or the query fails. Neither result limit nor diagnostic top_values can approximate an aggregate.

Multi-field syntax is match: {fields: [/a, /b], patterns: [{op: word, value: Peter}], mode: any}. Parent normalization applies to every pattern. Field/rule hits do not multiply records; missing-only matches remain unknown under NOT. The node is allowed in filters and conditional aggregates, with existing grouping/HAVING/time semantics. HAVING accepts output aliases only.

Diagnostic scope is positive leaf hits among rows after all outer filters, before grouping/window expansion. Default values are HMAC references; raw display needs explicit host and field permission. Diagnostic truncation is not predicate truncation. Frequency counts source records per field/value, not identities or window memberships. A fuzzy score is similarity, never identity confidence; entity/nickname/alias inference is unsupported.
