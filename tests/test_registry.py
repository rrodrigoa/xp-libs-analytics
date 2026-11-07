"""Named sources, lifecycle, hostile references and concurrent immutable publication."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastmcp import Client

from xp_libs_analytics import AnalyticsEngine, AnalyticsError, DatasetRegistry, Limits, Principal
from xp_libs_analytics.mcp.server import create_server


def query(name="sales"):
    return f"""version: analytics.query/v1
dataset: {{name: {name}}}
aggregations:
- {{op: sum, field: /value, as: total}}
"""


def code(error):
    return error.value.code


def test_named_inputs_and_no_legacy_api():
    engine = AnalyticsEngine()
    assert isinstance(engine.registry, DatasetRegistry)
    binding = engine.register_records(name="sales", records=[{"value": 10}, {"value": 20}])
    engine.register_records("events", [{"value": 5}])
    assert not hasattr(binding, "id")
    assert engine.query_yaml(query())["rows"] == [{"total": 30}]
    assert engine.query_yaml(query("events"))["rows"] == [{"total": 5}]
    listed = engine.list_datasets()
    assert [d["name"] for d in listed] == ["events", "sales"]
    assert listed[1]["records"] == 2
    assert "ds_" not in json.dumps(listed)
    assert (
        engine.query_yaml(query().replace("name:", "handle:"))["error"]["code"] == "QUERY_MALFORMED"
    )
    with pytest.raises(TypeError):
        engine.query_yaml(binding, query())
    with pytest.raises(TypeError):
        engine.register_records([{}])


@pytest.mark.parametrize(
    "name",
    ["", "a" * 65, "../sales", "sales.data", "sales/data", "1sales", "a:b", "\u00e9", None, 1],
)
def test_invalid_names(name):
    engine = AnalyticsEngine()
    with pytest.raises(AnalyticsError) as error:
        engine.register_records(name, [])
    assert code(error) == "DATASET_NAME_INVALID"
    assert engine.list_datasets() == []


def test_duplicate_failed_replacement_and_stale_compare_and_swap():
    engine = AnalyticsEngine()
    initial = engine.register_records("sales", [{"value": 2}])
    with pytest.raises(AnalyticsError) as error:
        engine.register_records("sales", [{"value": 3}])
    assert code(error) == "DATASET_NAME_DUPLICATE"
    with pytest.raises(AnalyticsError):
        engine.replace_records("sales", [{"value": float("nan")}])
    assert engine.query_yaml(query())["rows"] == [{"total": 2}]
    updated = engine.replace_records("sales", [{"value": 7}], expected_revision=initial.revision)
    assert updated.revision > initial.revision
    assert engine.query_yaml(query())["dataset"] == {"name": "sales", "revision": updated.revision}
    for action in [
        lambda: engine.replace_records("sales", [], expected_revision=initial.revision),
        lambda: engine.unregister_dataset("sales", expected_revision=initial.revision),
    ]:
        with pytest.raises(AnalyticsError) as error:
            action()
        assert code(error) == "DATASET_SNAPSHOT_STALE"
    engine.unregister_dataset("sales")
    recreated = engine.register_records("sales", [{"value": 8}])
    assert recreated.revision > updated.revision
    with pytest.raises(AnalyticsError) as error:
        engine.unregister_dataset("sales", expected_revision=updated.revision)
    assert code(error) == "DATASET_SNAPSHOT_STALE"


def test_unknown_and_foreign_names_indistinguishable():
    parent = AnalyticsEngine()
    parent.register_records("private", [{"value": 99}])
    with parent.create_context() as first, parent.create_context() as second:
        first.register_records("sales", [{"value": 1}])
        second.register_records("sales", [{"value": 2}])
        assert first.query_yaml(query())["rows"] == [{"total": 1}]
        assert second.query_yaml(query())["rows"] == [{"total": 2}]
        for name in ["private", "absent"]:
            assert first.query_yaml(query(name))["error"]["code"] == "DATASET_NAME_UNKNOWN"
            for action in [
                lambda name=name: first.describe(name),
                lambda name=name: first.replace_records(name, []),
                lambda name=name: first.unregister_dataset(name),
            ]:
                with pytest.raises(AnalyticsError) as error:
                    action()
                assert code(error) == "DATASET_NAME_UNKNOWN"
        assert [d["name"] for d in first.list_datasets()] == ["sales"]
    assert len(parent.store._snapshots) == 1
    assert first.query_yaml(query())["error"]["code"] == "ACCESS_DENIED"
    with pytest.raises(AnalyticsError):
        first.list_datasets()
    parent.close()
    parent.close()
    assert not parent.store._snapshots


@pytest.mark.parametrize("remove", [False, True])
def test_concurrent_query_retains_resolved_snapshot(remove, monkeypatch):
    from xp_libs_analytics.engine import backend

    engine = AnalyticsEngine(limits=Limits(max_datasets=1))
    old = engine.register_records("sales", [{"value": 1}])
    entered, resume = threading.Event(), threading.Event()
    execute = backend.execute_plan

    def pause(plan, limits):
        entered.set()
        assert resume.wait(10)
        return execute(plan, limits)

    monkeypatch.setattr(backend, "execute_plan", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(engine.query_yaml, query())
        try:
            assert entered.wait(10)
            if remove:
                engine.unregister_dataset("sales")
                assert engine.query_yaml(query())["error"]["code"] == "DATASET_NAME_UNKNOWN"
                current = engine.register_records("sales", [{"value": 8}])
            else:
                current = engine.replace_records("sales", [{"value": 8}])
            assert len(engine.store._snapshots) == 2
        finally:
            resume.set()
        result = pending.result(timeout=10)
    assert result["rows"] == [{"total": 1}]
    assert result["dataset"]["revision"] == old.revision
    assert len(engine.store._snapshots) == 1
    result = engine.query_yaml(query())
    assert result["rows"] == [{"total": 8}]
    assert result["dataset"]["revision"] == current.revision
    assert not engine.store._readers and not engine.store._retired


def test_pinned_memory_is_charged_and_failed_publication_is_atomic():
    engine = AnalyticsEngine(limits=Limits(max_datasets=1, max_total_bytes=15))
    engine.register_records("sales", [{"value": 1}])
    with engine.registry.snapshot("sales"):
        with pytest.raises(AnalyticsError) as error:
            engine.replace_records("sales", [{"value": 2}])
        assert code(error) == "RESOURCE_MEMORY_LIMIT"
        assert engine.query_yaml(query())["rows"] == [{"total": 1}]
    engine.replace_records("sales", [{"value": 2}])
    assert len(engine.store._snapshots) == 1


def test_concurrent_compare_and_swap_has_one_winner():
    engine = AnalyticsEngine()
    initial = engine.register_records("sales", [{"value": 1}])
    barrier = threading.Barrier(2)

    def replace(value):
        barrier.wait(timeout=10)
        try:
            engine.replace_records("sales", [{"value": value}], expected_revision=initial.revision)
            return "OK"
        except AnalyticsError as exc:
            return exc.code.value

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(replace, [2, 3]))
    assert sorted(outcomes) == ["DATASET_SNAPSHOT_STALE", "OK"]
    assert engine.query_yaml(query())["rows"][0]["total"] in {2, 3}
    assert len(engine.store._snapshots) == 1


def test_snapshot_pin_reference_count_expiry_and_internal_authority(engine):
    engine.register_records("sales", [{"value": 1}])
    with engine.registry.snapshot("sales") as old:
        with engine.registry.snapshot("sales"):
            assert engine.store._readers[old.handle.id] == 2
            engine.replace_records("sales", [{"value": 2}])
        assert engine.store._readers[old.handle.id] == 1
        assert old.handle.id in engine.store._retired
        with pytest.raises(AnalyticsError) as error:
            engine.store.get_snapshot(old.handle, Principal("foreign"), engine.clock())
        assert code(error) == "ACCESS_DENIED"
        with pytest.raises(AnalyticsError) as error:
            engine.store.get_snapshot(old.handle, engine.principal, old.expires)
        assert code(error) == "DATASET_SNAPSHOT_STALE"
    with pytest.raises(AnalyticsError) as error:
        engine.store.get_snapshot(old.handle, engine.principal, engine.clock())
    assert code(error) == "ACCESS_DENIED"
    assert not engine.store._readers and not engine.store._retired
    now = engine.clock()
    with engine.registry.snapshot("sales") as current:
        engine.clock = lambda: now + timedelta(seconds=901)
        engine.store.expire(engine.clock())
        assert current.handle.id in engine.store._retired
        engine.replace_records("sales", [{"value": 3}])
    assert len(engine.store._snapshots) == 1


@pytest.mark.parametrize("revision", [True, 1.0, "1", 0, -1])
def test_expected_revision_types_are_strict(revision):
    engine = AnalyticsEngine()
    engine.register_records("sales", [{"value": 1}])
    with pytest.raises(AnalyticsError) as error:
        engine.replace_records("sales", [], expected_revision=revision)
    assert code(error) == "DATASET_SNAPSHOT_STALE"


def test_close_retains_active_snapshots_and_failed_execution_releases_leases(monkeypatch):
    from xp_libs_analytics.engine import backend

    root = AnalyticsEngine()
    ctx = root.create_context()
    ctx.register_records("sales", [{"value": 1}])
    with ctx.registry.snapshot("sales"):
        ctx.close()
        assert len(root.store._snapshots) == 1
    assert not root.store._snapshots
    root.register_records("sales", [{"value": 2}])

    def fail(*_):
        raise RuntimeError("private")

    monkeypatch.setattr(backend, "execute_plan", fail)
    assert root.query_yaml(query())["error"]["code"] == "EXECUTION_BACKEND_ERROR"
    assert not root.store._readers
    root.unregister_dataset("sales")
    assert not root.store._snapshots


@pytest.mark.parametrize(
    "kind", ["context-and-engine", "context-and-principal", "engine-and-principal"]
)
def test_mcp_context_configuration_fails_closed(kind):
    engine = AnalyticsEngine()
    options = {
        "context-and-engine": {"engine": engine, "context_resolver": lambda: engine},
        "context-and-principal": {
            "context_resolver": lambda: engine,
            "principal_resolver": Principal,
        },
        "engine-and-principal": {"engine": engine, "principal_resolver": Principal},
    }
    with pytest.raises(ValueError):
        create_server(**options[kind])


def test_discovery_race_with_context_close_fails_closed(monkeypatch):
    engine = AnalyticsEngine()
    engine.register_records("sales", [{"value": 1}])
    ready, resume = threading.Event(), threading.Event()
    names = engine.registry.names

    def pause():
        result = names()
        ready.set()
        assert resume.wait(10)
        return result

    monkeypatch.setattr(engine.registry, "names", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(engine.list_datasets)
        try:
            assert ready.wait(10)
            engine.close()
        finally:
            resume.set()
        with pytest.raises(AnalyticsError) as error:
            pending.result(timeout=10)
    assert code(error) == "ACCESS_DENIED"


def test_expiry_republish_permissions_and_stream_seam(engine):
    engine.register_records("sales", [{"value": 1}])
    now = engine.clock()
    engine.clock = lambda: now + timedelta(seconds=901)
    assert engine.query_yaml(query())["error"]["code"] == "DATASET_SNAPSHOT_STALE"
    assert engine.list_datasets() == []
    engine.replace_records("sales", [{"value": 3}])
    assert engine.query_yaml(query())["rows"] == [{"total": 3}]
    view = engine._authorized_view(Principal(fields=frozenset()))
    assert view.list_datasets()[0]["fields"] == {}
    assert view.query_yaml(query())["error"]["code"] == "ACCESS_FIELD_DENIED"
    denied = engine._authorized_view(Principal(scopes=frozenset()))
    for action in [
        lambda: denied.register_records("new", []),
        lambda: denied.describe("sales"),
        lambda: denied.unregister_dataset("sales"),
        lambda: denied.list_datasets(),
    ]:
        with pytest.raises(AnalyticsError) as error:
            action()
        assert code(error) == "ACCESS_DENIED"
    with pytest.raises(AnalyticsError) as error:
        engine._authorized_view(Principal("foreign"))
    assert code(error) == "ACCESS_DENIED"
    engine.principal = Principal("foreign")
    with pytest.raises(AnalyticsError):
        engine.registry.names()
    with pytest.raises(AnalyticsError) as error:
        engine.register_stream("future", iter(()))
    assert code(error) == "QUERY_UNSUPPORTED_FEATURE"


@pytest.mark.asyncio
async def test_mcp_trusted_context_resolver_and_no_agent_context_selection():
    root = AnalyticsEngine()
    a, b = root.create_context(), root.create_context()
    a.register_records("sales", [{"value": 1}])
    b.register_records("sales", [{"value": 2}])
    active = [a]
    async with Client(create_server(context_resolver=lambda: active[0])) as client:
        listing = await client.call_tool("analytics_list_datasets", {})
        assert listing.structured_content["datasets"][0]["name"] == "sales"
        assert "ds_" not in json.dumps(listing.structured_content)
        for context, total in [(a, 1), (b, 2)]:
            active[0] = context
            result = await client.call_tool("analytics_query", {"query_yaml": query()})
            assert result.structured_content["rows"] == [{"total": total}]
        for args in [
            {"query_yaml": query(), "context_id": "foreign"},
            {"query_yaml": query(), "principal": "admin"},
        ]:
            result = await client.call_tool("analytics_query", args, raise_on_error=False)
            assert result.structured_content["error"]["code"] == "MCP_INVALID_TOOL_CALL"
        result = await client.call_tool(
            "analytics_describe", {"handle": "sales"}, raise_on_error=False
        )
        assert result.structured_content["error"]["code"] == "MCP_INVALID_TOOL_CALL"
