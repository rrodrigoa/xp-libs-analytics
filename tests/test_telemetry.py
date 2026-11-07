import json

from conftest import query_text

from xp_libs_analytics import AnalyticsEngine


def test_observability_is_safe_optional_and_non_disruptive():
    events = []
    engine = AnalyticsEngine(telemetry=events.append)
    handle = engine.register_records("dataset_1", [{"private_field": "SECRET_VALUE"}])
    assert engine.query_yaml(query_text(handle))["status"] == "OK"
    assert engine.query_yaml("invalid")["status"] == "ERROR"
    assert events[0]["outcome"] == "OK"
    assert events[1]["error_code"] == "QUERY_YAML_ROOT_INVALID"
    assert events[0]["duration_seconds"] >= 0
    text = json.dumps(events)
    assert "private_field" not in text and "SECRET_VALUE" not in text and handle.name not in text

    def unavailable(event):
        raise RuntimeError("monitor unavailable")

    engine.telemetry = unavailable
    assert engine.query_yaml(query_text(handle))["status"] == "OK"
