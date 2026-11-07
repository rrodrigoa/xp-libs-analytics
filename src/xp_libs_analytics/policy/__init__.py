"""Host-owned policy. Request documents cannot override these limits."""

import threading
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 8 * 1024 * 1024
    max_rows: int = 100_000
    max_columns: int = 256
    max_depth: int = 12
    max_record_bytes: int = 128 * 1024
    max_datasets: int = 8
    max_total_bytes: int = 64 * 1024 * 1024
    ttl_seconds: int = 900
    max_result_bytes: int = 1024 * 1024
    max_groups: int = 10_000
    max_windows: int = 10_000
    max_expanded_rows: int = 1_200_000
    max_distinct: int = 10_000
    max_query_bytes: int = 65_536
    max_yaml_depth: int = 16
    max_yaml_nodes: int = 4096
    max_scalar_chars: int = 1024
    max_collection_items: int = 1024
    max_concurrency: int = 2
    max_queries_per_minute: int = 120
    timeout_seconds: float = 15.0
    memory_bytes: int = 1024 * 1024 * 1024
    min_samples: int = 1
    allow_null_cast: bool = True
    max_match_fields: int = 10
    max_match_patterns: int = 10
    max_match_work: int = 40
    max_match_literal_chars: int = 1024
    max_regex_bytes: int = 512
    max_match_value_chars: int = 1024
    max_fuzzy_candidates: int = 10_000
    max_match_normalized_bytes: int = 8 * 1024 * 1024
    max_fuzzy_comparisons: int = 100_000
    min_fuzzy_query_chars: int = 3
    min_fuzzy_score: float = 70.0
    max_match_diagnostic_values: int = 20
    max_match_diagnostic_candidates: int = 10_000
    allow_match_raw_values: bool = False
    allow_match_catch_all: bool = False
    match_pushdown: bool = True
    force_matching_isolation: bool = True


@dataclass(frozen=True)
class Principal:
    id: str = "local"
    fields: frozenset[str] | None = None
    scopes: frozenset[str] = frozenset({"read", "upload", "release"})

    match_raw_fields: frozenset[str] = frozenset()

    def permits(self, field: str) -> bool:
        return self.fields is None or field in self.fields


class RequestBudget:
    def __init__(self, limits: Limits) -> None:
        self.slots = threading.BoundedSemaphore(limits.max_concurrency)
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()
