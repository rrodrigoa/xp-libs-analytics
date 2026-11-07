from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import query_text
from hypothesis import given, settings
from hypothesis import strategies as st

from xp_libs_analytics import AnalyticsError, Limits, Principal
from xp_libs_analytics.errors import CATALOG
from xp_libs_analytics.parser import parse_yaml


@pytest.mark.parametrize(
    "case,text,code",
    [
        ("Y01-indent", "a:\n\tx: 1", "QUERY_YAML_INVALID"),
        ("Y01-quote", "a: 'unclosed", "QUERY_YAML_INVALID"),
        ("Y02", "limit: 1\nlimit: 2", "QUERY_YAML_DUPLICATE_KEY"),
        ("Y03", "a:\n  op: avg\n  op: sum", "QUERY_YAML_DUPLICATE_KEY"),
        ("Y04", "a: {op: avg, op: sum}", "QUERY_YAML_DUPLICATE_KEY"),
        ("Y05", "a: &unused 1", "QUERY_YAML_ANCHOR_FORBIDDEN"),
        ("Y06", "a: *missing", "QUERY_YAML_ALIAS_FORBIDDEN"),
        ("Y07", "a: {<<: *missing}", "QUERY_YAML_ALIAS_FORBIDDEN"),
        ("Y07-merge", "a: {<<: 1}", "QUERY_YAML_ALIAS_FORBIDDEN"),
        ("Y08-custom", "a: !foo 1", "QUERY_YAML_TAG_FORBIDDEN"),
        ("Y08-python", "a: !!python/object/apply:os.system ['evil']", "QUERY_YAML_TAG_FORBIDDEN"),
        ("Y08-time", "a: !!timestamp 2026-11-06", "QUERY_YAML_TAG_FORBIDDEN"),
        (
            "Y08-directive",
            "%TAG !e! tag:example.com,2000:app/\n---\na: 1",
            "QUERY_YAML_TAG_FORBIDDEN",
        ),
        ("Y08-version", "%YAML 1.1\n---\na: 1", "QUERY_YAML_TAG_FORBIDDEN"),
        ("Y09", "a: 1\n---\nb: !evil 2", "QUERY_YAML_MULTI_DOCUMENT"),
        ("Y10-empty", "", "QUERY_YAML_ROOT_INVALID"),
        ("Y10-list", "[1, 2]", "QUERY_YAML_ROOT_INVALID"),
        ("Y10-scalar", "true", "QUERY_YAML_ROOT_INVALID"),
        ("Y11", "1: 2", "QUERY_YAML_ROOT_INVALID"),
        ("Y15-nan", "a: .nan", "QUERY_YAML_SCALAR_INVALID"),
        ("Y15-inf", "a: .inf", "QUERY_YAML_SCALAR_INVALID"),
        ("Y15-overflow", "a: 1e999", "QUERY_YAML_SCALAR_INVALID"),
        ("Y15-int", "a: 9223372036854775808", "QUERY_YAML_SCALAR_INVALID"),
        ("Y15-hex", "a: 0xff", "QUERY_YAML_SCALAR_INVALID"),
        ("Y15-octal", "a: 01", "QUERY_YAML_SCALAR_INVALID"),
        ("Y16", "x: " + "a" * 65537, "QUERY_YAML_COMPLEXITY_LIMIT"),
        ("Y17-depth", "x: " + "[" * 20 + "0" + "]" * 20, "QUERY_YAML_COMPLEXITY_LIMIT"),
        ("Y17-width", "a: [" + "0," * 1100 + "]", "QUERY_YAML_COMPLEXITY_LIMIT"),
        ("Y17-scalar", "a: " + "s" * 1025, "QUERY_YAML_COMPLEXITY_LIMIT"),
        ("S20", 'a: "\\uD800"', "QUERY_YAML_SCALAR_INVALID"),
        ("S20-control", 'a: "\\x01"', "QUERY_YAML_SCALAR_INVALID"),
        ("S20-surrogate", "a: \ud800", "QUERY_YAML_SCALAR_INVALID"),
    ],
)
def test_yaml_rejections(case, text, code):
    with pytest.raises(AnalyticsError) as caught:
        parse_yaml(text)
    error = caught.value.envelope()["error"]
    assert error["code"] == code
    assert error["message"] == CATALOG[code]
    assert error["path"].startswith("$")
    if "line" in error["details"]:
        assert error["details"]["line"] >= 1 and error["details"]["column"] >= 1


def test_Y12_Y13_Y14_Y18_scalars():
    result = parse_yaml(
        "a: [on, off, yes, no, true, false, null, 'true', 'null', 2026-11-06, "
        "2026-11-06T00:00:00Z, '*alias', '!tag', 1.25, 1e2]"
    )
    assert result["a"] == [
        "on",
        "off",
        "yes",
        "no",
        True,
        False,
        None,
        "true",
        "null",
        "2026-11-06",
        "2026-11-06T00:00:00Z",
        "*alias",
        "!tag",
        1.25,
        100.0,
    ]
    import yaml

    assert yaml.safe_load("a: on")["a"] is True  # global resolver was not mutated


def test_Y19_layout_equivalence(engine):
    import yaml

    handle = engine.register_records("dataset_1", [{"x": 1}])
    text = query_text(handle)
    flow = yaml.safe_dump(parse_yaml(text), default_flow_style=True)
    assert engine.validate_query(text)["plan"] == engine.validate_query(flow)["plan"]
    assert engine.query_yaml(text)["rows"] == engine.query_yaml(flow)["rows"]


def test_Y20_Y22_Y24_Y25_repair_and_parity(engine):
    handle = engine.register_records("dataset_2", [{"x": 1}])
    valid = query_text(handle)
    for invalid, code in [
        ("a: [", "QUERY_YAML_INVALID"),
        (valid + "query_yaml: whatever\n", "QUERY_MALFORMED"),
        (valid + "include: /etc/passwd\n", "QUERY_MALFORMED"),
        (valid + "env: ${SECRET}\n", "QUERY_MALFORMED"),
        (valid.replace("op: count", "op: average"), "QUERY_UNKNOWN_OPERATOR"),
    ]:
        a = engine.validate_query(invalid)
        b = engine.query_yaml(invalid)
        assert a["error"] == b["error"]
        assert a["error"]["code"] == code
    assert engine.validate_query(valid)["status"] == "OK"
    assert engine.query_yaml(valid)["rows"] == [{"n": 1}]


def test_Y21_cross_principal(engine):
    from xp_libs_analytics import AnalyticsEngine

    handle = engine.register_records("dataset_3", [{"secret": "do not disclose"}])
    foreign = AnalyticsEngine(store=engine.store, principal=Principal("foreign"))
    error = foreign.query_yaml(query_text(handle))["error"]
    assert error["code"] == "DATASET_NAME_UNKNOWN"
    assert "secret" not in str(error)


def test_concurrent_parser():
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(parse_yaml, ["a: [yes, null, 3]"] * 100))
    assert all(v == {"a": ["yes", None, 3]} for v in values)


def test_event_node_budget():
    with pytest.raises(AnalyticsError, match=CATALOG["QUERY_YAML_COMPLEXITY_LIMIT"]):
        parse_yaml("a: [1,2,3,4]", Limits(max_yaml_nodes=5))


@given(st.text(max_size=500))
@settings(max_examples=150, deadline=None, derandomize=True)
def test_H10_yaml_fuzz_never_leaks(text):
    try:
        parse_yaml(text)
    except AnalyticsError as exc:
        assert exc.code in CATALOG
        assert str(exc) == CATALOG[exc.code]
