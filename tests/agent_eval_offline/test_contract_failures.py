import json
import sys
from unittest.mock import MagicMock

import pytest
import yaml

from evals.agent_skill import scenarios, server, skill_loader
from evals.agent_skill.fixtures import make_engine


@pytest.mark.parametrize("fault", ["duplicate", "tool", "fixture"])
def test_bad_scenario_contracts(fault, tmp_path, monkeypatch):
    scenario = scenarios.load_scenarios(scenario_id="aggregate-count")[0].model_dump()
    (tmp_path / "datasets").mkdir()
    (tmp_path / "datasets" / scenario["fixture"]).write_text("{}\n")
    (tmp_path / "scenarios").mkdir()
    if fault == "tool":
        scenario["allowed_tools"] = ["shell"]
    if fault == "fixture":
        scenario["fixture"] = "missing.jsonl"
    document = {
        "scenarios": [scenario, json.loads(json.dumps(scenario))]
        if fault == "duplicate"
        else [scenario]
    }
    (tmp_path / "scenarios/test.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
    monkeypatch.setattr(scenarios, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        scenarios.load_scenarios()


def test_unsupported_fixture_policy_and_empty_skill(tmp_path, monkeypatch):
    s = scenarios.load_scenarios(scenario_id="aggregate-count")[0]
    s.policy = {"arbitrary": 1}
    with pytest.raises(ValueError):
        make_engine(s)
    path = tmp_path / "skills/generic-analytics"
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("")
    monkeypatch.setattr(skill_loader, "REPO", tmp_path)
    with pytest.raises(ValueError):
        skill_loader.load_skill()


def test_scenario_host_uses_production_server_and_private_namespace(monkeypatch):
    created = []

    def factory(engine, uploads):
        created.append(engine)
        assert uploads is False
        return MagicMock()

    monkeypatch.setattr(server, "create_server", factory)
    monkeypatch.setattr(
        sys, "argv", ["server", "--scenario", "aggregate-count", "--seed", "17", "--trial", "1"]
    )
    server.main()
    capabilities = created[0].capabilities()
    assert "evaluation_dataset" in capabilities
    assert "expected" not in capabilities
    assert created[0].isolated
