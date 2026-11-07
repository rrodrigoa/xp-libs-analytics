import json
from copy import deepcopy

import pytest

from evals.agent_skill import cli
from evals.agent_skill.fixtures import bind_query, make_engine
from evals.agent_skill.scenarios import load_scenarios
from evals.agent_skill.scoring import Call, score_trace
from xp_libs_analytics import AnalyticsError
from xp_libs_analytics.engine.backend import predicate_expr
from xp_libs_analytics.models import Contains


def test_multi_field_semantics_allow_commutative_field_and_rule_order():
    scenario = load_scenarios(scenario_id="matching-misspelling")[0].model_copy(deep=True)
    node = {
        "match": {
            "fields": ["/actor/name", "/actor/email"],
            "patterns": [
                {"op": "word", "value": "Peter"},
                {"op": "fuzzy", "value": "Pter", "algorithm": "ratio", "min_score": 85},
            ],
            "mode": "any",
        }
    }
    scenario.expected.query = {"filters": [node], "aggregations": [{"op": "count", "as": "n"}]}
    engine, name = make_engine(scenario)
    actual = deepcopy(scenario.expected.query)
    actual["filters"][0]["match"]["fields"].reverse()
    actual["filters"][0]["match"]["patterns"].reverse()
    text = bind_query(actual, name)
    result = engine.query_yaml(text)
    score = score_trace(
        scenario,
        [Call(tool="analytics_query", arguments={"query_yaml": text}, response=result)],
        json.dumps(
            {
                "outcome": "success",
                "rows": result["rows"],
                "explanation": "Observed values, not identities",
            }
        ),
    )
    assert score.status == "PASS", score


def test_runtime_model_selection_is_required_and_not_defaulted(monkeypatch):
    assert cli.parser().parse_args(["run"]).model is None
    monkeypatch.setattr("sys.argv", ["eval", "run"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_string_factory_without_shared_matching_context_fails_closed():
    with pytest.raises(AnalyticsError) as error:
        predicate_expr(
            Contains(op="contains", field="/x", value="literal"),
            {"/x": ("x", "p", "n")},
            {"/x": "string"},
        )
    assert error.value.code == "QUERY_OPERATOR_TYPE"
