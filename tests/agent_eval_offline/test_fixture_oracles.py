from evals.agent_skill.fixtures import make_engine, oracle, records
from evals.agent_skill.scenarios import load_scenarios


def test_independent_known_sales_facts():
    s = load_scenarios(scenario_id="sales-aggregate-001")[0]
    rows = oracle(s)["rows"]
    assert sorted((r["region"], r["total"]) for r in rows) == [("east", 250), ("west", 400)]


def test_namespaces_and_clock_are_independent():
    s = load_scenarios(scenario_id="relative-last-hour")[0]
    first, a = make_engine(s)
    second, b = make_engine(s)
    assert a == b == "observations"
    first.unregister_dataset(a)
    assert first.list_datasets() == []
    assert second.describe(b)["records"] == 14
    assert first.clock() == second.clock()
    assert oracle(s)["rows"] == [{"n": 14}]
    assert records(s) == records(s)
