from evals.agent_skill.fixtures import oracle
from evals.agent_skill.scenarios import load_scenarios, vary


def test_field_variations_preserve_oracle_and_are_paired():
    for s in load_scenarios("positive") + load_scenarios("temporal"):
        variant = vary(s, 17, 1)
        assert variant == vary(s, 17, 1)
        assert oracle(variant)["rows"] == oracle(s)["rows"]
        assert variant.field_renames
        assert variant.variation_seed == 17 and variant.variation_trial == 1


def test_recovery_variations_do_not_change_error_contract():
    s = load_scenarios("recovery")[0]
    assert vary(s, 17, 1).recovery == s.recovery
