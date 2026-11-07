import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from rapidfuzz import fuzz

from xp_libs_analytics.errors import CATALOG
from xp_libs_analytics.models import AGG_OPS

from .support import execute, fuzzy, leaf, make
from .test_composition import multi

STRINGS = st.text(alphabet="aAbBPeter_-%.*[]'éß\n ", max_size=14)
CONFIG = st.fixed_dictionaries(
    {
        "case_sensitive": st.booleans(),
        "unicode": st.sampled_from(["none", "nfc", "nfkc"]),
        "trim": st.booleans(),
    }
)


def normalized(value, config):
    if config["unicode"] != "none":
        value = unicodedata.normalize(config["unicode"].upper(), value)
    if config["trim"]:
        value = value.strip()
    return value if config["case_sensitive"] else value.casefold()


@settings(max_examples=70, deadline=None, derandomize=True)
@given(
    st.lists(st.one_of(STRINGS, st.none()), min_size=1, max_size=15),
    STRINGS.filter(lambda s: bool(s.strip())),
    CONFIG,
)
def test_independent_literal_oracle(values, term, config):
    needle = normalized(term, config)
    if not needle:
        return
    rows = [{"actor": {"name": v}} for v in values] + [{}]
    engine = make(rows)
    for op in ["eq", "ne", "contains", "not_contains", "starts_with", "ends_with"]:

        def reference(value, op=op):
            value = normalized(value, config)
            return {
                "eq": value == needle,
                "ne": value != needle,
                "contains": needle in value,
                "not_contains": needle not in value,
                "starts_with": value.startswith(needle),
                "ends_with": value.endswith(needle),
            }[op]

        expected = sum(reference(v) for v in values if v is not None)
        assert execute(engine, [leaf(op, term, normalization=config)])["rows"] == [{"n": expected}]


def like_reference(candidate, pattern):
    # Independent dynamic-programming oracle; no use of the production regex translator.
    tokens, index = [], 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 1
            tokens.append(("literal", pattern[index]))
        else:
            tokens.append(("many" if char == "%" else "one" if char == "_" else "literal", char))
        index += 1
    states = {0}
    for kind, char in tokens:
        if kind == "many":
            states = {j for i in states for j in range(i, len(candidate) + 1)}
        else:
            states = {
                i + 1
                for i in states
                if i < len(candidate) and (kind == "one" or candidate[i] == char)
            }
    return len(candidate) in states


@settings(max_examples=55, deadline=None, derandomize=True)
@given(
    STRINGS,
    st.lists(
        st.sampled_from(["P", "a", "%", "_", r"\%", r"\_", r"\\", "\n"]), min_size=1, max_size=8
    ),
)
def test_like_matches_independent_dynamic_programming(value, tokens):
    pattern = "".join(tokens)
    actual = execute(
        make([{"actor": {"name": value}}], allow_match_catch_all=True), [leaf("like", pattern)]
    )
    assert actual["rows"] == [{"n": int(like_reference(value, pattern))}]


@settings(max_examples=40, deadline=None, derandomize=True)
@given(
    st.lists(STRINGS, min_size=1, max_size=20),
    st.floats(min_value=70, max_value=100),
    st.floats(min_value=70, max_value=100),
)
def test_fuzzy_threshold_monotonic_and_exact_reference(values, first, second):
    lower, higher = sorted([first, second])
    engine = make([{"actor": {"name": v}} for v in values])
    counts = []
    for threshold in [lower, higher]:
        result = execute(engine, [{**fuzzy(), "min_score": threshold}])
        expected = sum(fuzz.ratio("Peter", v, processor=None) >= threshold for v in values)
        assert result["rows"] == [{"n": expected}]
        counts.append(expected)
    assert counts[1] <= counts[0]


@settings(max_examples=40, deadline=None, derandomize=True)
@given(
    st.lists(st.tuples(st.one_of(STRINGS, st.none()), st.one_of(STRINGS, st.none())), max_size=15)
)
def test_any_equals_separate_three_valued_or_without_duplicate_records(values):
    rows = [{"a": "Peter", "b": "Other"}] + [{"a": a, "b": b} for a, b in values] + [{}]
    rule = multi(["/a", "/b"], [{"op": "contains", "value": "P"}, {"op": "contains", "value": "P"}])
    separate = {
        "op": "or",
        "conditions": [
            {"field": "/a", "op": "contains", "value": "P"},
            {"field": "/b", "op": "contains", "value": "P"},
        ],
    }
    engine = make(rows)
    for outer in [lambda x: x, lambda x: {"op": "not", "condition": x}]:
        assert execute(engine, [outer(rule)])["rows"] == execute(engine, [outer(separate)])["rows"]


@settings(max_examples=40, deadline=None, derandomize=True)
@given(st.text(alphabet="ab()[]{}*+?\\^$0129", min_size=1, max_size=25))
def test_malformed_regex_is_always_a_canonical_error_or_bounded_result(pattern):
    result = execute(make([{"actor": {"name": "aaa"}}]), [leaf("regex", pattern)])
    assert result["status"] in {"OK", "NO_DATA", "ERROR"}
    if result["status"] == "ERROR":
        assert result["error"]["code"] in CATALOG
        assert result["error"]["message"] == CATALOG[result["error"]["code"]]


@pytest.mark.parametrize("op", AGG_OPS)
def test_every_existing_aggregate_runs_after_fuzzy_selection(op):
    rows = [
        {"actor": {"name": name}, "x": value}
        for name, value in [("Peter", 2), ("Pter", 4), ("William", 100), ("Peter", None)]
    ] + [{"actor": {"name": "Peter"}}]
    filtered = [r for r in rows if fuzz.ratio("Peter", r["actor"]["name"], processor=None) >= 80]
    agg = {"op": op, "as": "v"}
    if op not in {"count", "count_if"}:
        agg["field"] = "/x"
    if op.endswith("_if"):
        agg["where"] = {"field": "/x", "op": "gt", "value": 2}
    assert (
        execute(make(rows), [fuzzy()], [agg])["rows"]
        == execute(make(filtered), aggregations=[agg])["rows"]
    )
