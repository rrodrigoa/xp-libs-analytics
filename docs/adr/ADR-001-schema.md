# ADR-001: Full-snapshot discovery

Accepted. Profile every admitted record; preserve RFC 6901 paths, observed type unions, presence and explicit null flags. Reject mixed typed operations without explicit casts. This avoids first-sample schema errors and silent coercion. Snapshot admission and per-query work are bounded by host-owned limits.
