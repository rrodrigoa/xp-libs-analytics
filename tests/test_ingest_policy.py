import json
from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import query_text

from xp_libs_analytics import AnalyticsEngine, AnalyticsError, Limits, Principal
from xp_libs_analytics.errors import CATALOG
from xp_libs_analytics.ingest import pointer_tokens


@pytest.mark.parametrize(
    "data,code",
    [
        ('{"a":', "INPUT_INVALID_JSON"),
        ('{"a":1,"a":2}', "INPUT_DUPLICATE_KEY"),
        ('{"a": {"x":1,"x":2}}', "INPUT_DUPLICATE_KEY"),
        ("[1,2]", "INPUT_UNSUPPORTED_ROOT"),
        ('{"x":NaN}', "INPUT_INVALID_NUMBER"),
        ('{"x":1e999}', "INPUT_INVALID_NUMBER"),
        (b"\xff", "INPUT_INVALID_UTF8"),
        ([{"x": 2**63}], "INPUT_INVALID_NUMBER"),
        ([{"x": object()}], "INPUT_UNSUPPORTED_ROOT"),
        ([{1: 2}], "INPUT_UNSUPPORTED_ROOT"),
        ([{"x": "\ud800"}], "INPUT_INVALID_UTF8"),
        (123, "INPUT_UNSUPPORTED_ROOT"),
    ],
)
def test_input_rejections(engine, data, code):
    with pytest.raises(AnalyticsError) as caught:
        engine.register_records("dataset_7", data)
    assert caught.value.code == code and str(caught.value) == CATALOG[code]


@pytest.mark.parametrize(
    "limit,rows,code",
    [
        ({"max_bytes": 2}, "[] ", "INPUT_BYTES_LIMIT"),
        ({"max_bytes": 2}, b"[] ", "INPUT_BYTES_LIMIT"),
        ({"max_bytes": 3}, [{"x": 2}], "INPUT_BYTES_LIMIT"),
        ({"max_rows": 1}, [{}, {}], "INPUT_ROWS_LIMIT"),
        ({"max_depth": 1}, [{"x": {"y": 1}}], "INPUT_TOO_DEEP"),
        ({"max_columns": 1}, [{"a": 1, "b": 2}], "INPUT_TOO_WIDE"),
        ({"max_record_bytes": 5}, [{"x": "long"}], "INPUT_RECORD_TOO_LARGE"),
    ],
)
def test_admission_limits(limit, rows, code):
    with pytest.raises(AnalyticsError) as caught:
        AnalyticsEngine(limits=Limits(**limit)).register_records("dataset_8", rows)
    assert caught.value.code == code


def test_full_profile_immutability_ndjson(engine):
    rows = [{"x": i} for i in range(120)] + [{"late": {"a/b": False}, "x": None}, {}]
    handle = engine.register_records("dataset_1", rows)
    rows[0]["x"] = "changed"
    schema = engine.describe(handle.name)["fields"]
    assert schema["/late/a~1b"]["type"] == "boolean"
    assert schema["/x"]["null"] == schema["/x"]["missing"] == 1
    assert "changed" not in str(schema)
    text = "\n".join(json.dumps(r) for r in [{"x": 1}, {"x": None}])
    h = engine.register_records("dataset_2", text)
    assert engine.describe(h.name)["records"] == 2
    with pytest.raises(AnalyticsError) as caught:
        engine.register_records("dataset_9", '{"x":1}\nBAD', ndjson=True)
    assert caught.value.code == "INPUT_INVALID_NDJSON"
    with pytest.raises(AnalyticsError):
        engine.register_records("dataset_10", '{"x":1}\n3', ndjson=True)


def test_iterable_cyclic_and_numeric_precision(engine):
    h = engine.register_records("dataset_3", ({"x": i} for i in range(4)))
    assert engine.describe(h.name)["records"] == 4
    recursive = {}
    recursive["self"] = recursive
    with pytest.raises(AnalyticsError):
        engine.register_records("dataset_11", recursive)
    with pytest.raises(AnalyticsError) as caught:
        engine.register_records("dataset_12", [{"x": 2**53 + 1}, {"x": 0.5}])
    assert caught.value.code == "INPUT_INVALID_NUMBER"


def test_access_fields_handles_and_revocation(engine):
    handle = engine.register_records("dataset_4", [{"hidden": "secret", "public": 1}])
    limited = engine._authorized_view(Principal("local", fields=frozenset({"/public"})))
    assert set(limited.describe(handle.name)["fields"]) == {"/public"}
    for field in ["/hidden", "/nonexistent"]:
        result = limited.query_yaml(query_text(handle, [{"op": "sum", "field": field, "as": "n"}]))
        assert result["error"]["code"] == "ACCESS_FIELD_DENIED"
    foreign = AnalyticsEngine(
        store=engine.store, principal=Principal("foreign"), clock=engine.clock
    )
    for method in [foreign.describe, foreign.unregister_dataset]:
        with pytest.raises(AnalyticsError) as caught:
            method(handle.name)
        assert caught.value.code == "DATASET_NAME_UNKNOWN"
    assert foreign.explain_query(query_text(handle))["error"]["code"] == "DATASET_NAME_UNKNOWN"
    assert foreign.query_yaml(query_text(handle))["error"]["code"] == "DATASET_NAME_UNKNOWN"
    engine.unregister_dataset(handle.name)
    with pytest.raises(AnalyticsError):
        engine.describe(handle.name)


def test_ttl_handle_limit_and_scopes(engine):
    engine.limits = replace(engine.limits, max_datasets=1)
    engine.store.limits = engine.limits
    handle = engine.register_records("dataset_5", [])
    with pytest.raises(AnalyticsError) as caught:
        engine.register_records("dataset_13", [])
    assert caught.value.code == "RESOURCE_DATASETS_LIMIT"
    now = engine.clock()
    engine.clock = lambda: now + timedelta(seconds=901)
    with pytest.raises(AnalyticsError) as caught:
        engine.describe(handle.name)
    assert caught.value.code == "DATASET_SNAPSHOT_STALE"
    engine.unregister_dataset(handle.name)
    other = engine.register_records("dataset_6", [])
    assert other.name != handle.name
    engine.principal = Principal(scopes=frozenset())
    for method in [engine.describe, engine.unregister_dataset]:
        with pytest.raises(AnalyticsError) as caught:
            method(other.name)
        assert caught.value.code == "ACCESS_DENIED"
    assert engine.query_yaml(query_text(other))["error"]["code"] == "ACCESS_DENIED"


@pytest.mark.parametrize("pointer", ["a.b", "", "/x~2", "/x~", "/a/b/c"])
def test_invalid_pointer(pointer):
    with pytest.raises(AnalyticsError) as caught:
        pointer_tokens(pointer, 2)
    assert caught.value.code == "QUERY_INVALID_POINTER"
