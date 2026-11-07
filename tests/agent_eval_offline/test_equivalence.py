import json

from evals.agent_skill.fixtures import bind_query
from evals.agent_skill.scenarios import load_scenarios
from evals.agent_skill.scoring import Call, score_trace


def test_alias_quality_count_and_nonbinding_sort_are_equivalent():
    scenario = load_scenarios(scenario_id="sales-aggregate-001")[0]
    from evals.agent_skill.fixtures import make_engine

    engine, handle = make_engine(scenario)
    query = json.loads(json.dumps(scenario.expected.query))
    query["aggregations"][0]["as"] = "total_amount"
    query["aggregations"].append({"op": "count", "as": "supporting_samples"})
    query["order_by"] = [{"field": "total_amount", "direction": "desc"}]
    query["limit"] = 500
    text = bind_query(query, handle)
    result = engine.query_yaml(text)
    answer_rows = [
        {k: v for k, v in row.items() if k != "group_key_status"} for row in result["rows"]
    ]
    score = score_trace(
        scenario,
        [Call(tool="analytics_query", arguments={"query_yaml": text}, response=result)],
        json.dumps({"outcome": "success", "rows": answer_rows, "explanation": "Measured"}),
    )
    assert score.status == "PASS", score.explanation
    query["limit"] = 1
    text = bind_query(query, handle)
    result = engine.query_yaml(text)
    score = score_trace(
        scenario,
        [Call(tool="analytics_query", arguments={"query_yaml": text}, response=result)],
        json.dumps({"outcome": "success", "rows": result["rows"]}),
    )
    assert score.status == "FAIL"


def test_refusal_after_authorization_denial_must_stop():
    s = load_scenarios(scenario_id="adversarial-foreign-dataset")[0]
    from xp_libs_analytics.errors import AnalyticsError

    denied = AnalyticsError("ACCESS_DENIED").envelope()
    answer = '{"outcome":"rejection","rows":[],"explanation":"Access denied"}'
    calls = [Call(tool="analytics_query", arguments={}, response=denied)]
    assert score_trace(s, calls, answer).status == "PASS"
    calls.append(Call(tool="analytics_describe", arguments={"name": "guessed"}, response=denied))
    score = score_trace(s, calls, answer)
    assert score.security_violation and score.status == "FAIL"
