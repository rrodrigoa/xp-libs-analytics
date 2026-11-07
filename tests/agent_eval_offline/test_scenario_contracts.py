from collections import Counter

import pytest

from evals.agent_skill.cli import validate
from evals.agent_skill.fixtures import oracle
from evals.agent_skill.scenarios import load_scenarios, vary

SCENARIOS = load_scenarios()


def test_minimum_categories_and_definitions():
    counts = Counter(s.category for s in SCENARIOS)
    assert counts["positive"] >= 30 and counts["negative"] >= 20
    assert counts["adversarial"] >= 15 and counts["recovery"] >= 11
    assert validate()["status"] == "PASS"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_every_oracle(scenario):
    result = oracle(scenario)
    if scenario.expected.outcome in {"success", "no_data"}:
        assert result["status"] == ("NO_DATA" if scenario.expected.outcome == "no_data" else "OK")
    else:
        assert result is None


def test_deterministic_variations():
    s = SCENARIOS[0]
    assert vary(s, 17, 0) == vary(s, 17, 0)
    assert vary(s, 17, 0).expected == s.expected
    with pytest.raises(ValueError):
        load_scenarios("missing")
