import json

import pytest

from evals.agent_skill.fixtures import bind_query, oracle
from evals.agent_skill.reporting import metrics
from evals.agent_skill.scenarios import load_scenarios
from evals.agent_skill.scoring import Call, close, score_trace


@pytest.mark.parametrize(
    "scenario",
    [s for s in load_scenarios() if s.expected.outcome in {"success", "no_data"}],
    ids=lambda s: s.id,
)
def test_correct_trace_with_aliases_and_results(scenario):
    if scenario.recovery:
        return
    result = oracle(scenario)
    calls = [
        Call(tool=t, arguments={}, response={})
        for t in scenario.expected.required_tools
        if t != "analytics_query"
    ]
    calls += [
        Call(
            tool="analytics_query",
            arguments={"query_yaml": bind_query(scenario.expected.query, "owned")},
            response=result,
        )
    ]
    answer = json.dumps(
        {
            "outcome": scenario.expected.outcome,
            "rows": result["rows"],
            "explanation": "Measured snapshot",
        }
    )
    score = score_trace(scenario, calls, answer)
    assert score.status == "PASS", score.explanation


def test_reject_accidentally_correct_result_wrong_query():
    scenario = load_scenarios(scenario_id="aggregate-sum")[0]
    result = oracle(scenario)
    call = Call(
        tool="analytics_query",
        arguments={
            "query_yaml": bind_query({"aggregations": [{"op": "count", "as": "metric"}]}, "owned")
        },
        response=result,
    )
    score = score_trace(
        scenario, [call], json.dumps({"outcome": "success", "rows": result["rows"]})
    )
    assert score.status == "FAIL" and not score.dimensions["query_semantics"]


def test_unsupported_tool_is_hard_failure():
    scenario = load_scenarios("adversarial")[0]
    score = score_trace(
        scenario,
        [Call(tool="shell", arguments={}, response={})],
        json.dumps({"outcome": "rejection", "explanation": "Denied"}),
    )
    assert score.security_violation and score.status == "FAIL"
    assert metrics([score])["security_violations"] == 1


def test_refusal_is_wrong_for_supported_query():
    s = load_scenarios(scenario_id="aggregate-count")[0]
    assert score_trace(s, [], '{"outcome":"rejection","explanation":"No"}').status == "FAIL"
    assert not close(True, 1)
    assert close(1.0000000001, 1.0)
