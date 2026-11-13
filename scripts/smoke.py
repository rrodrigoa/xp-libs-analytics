"""Run with a freshly installed interpreter, outside editable source imports."""

import json
import sys
from dataclasses import replace
from importlib.metadata import distribution
from importlib.resources import files

from pydantic import BaseModel

from xp_libs_analytics import AnalyticsEngine, ParameterizedYamlQuery

assert "fastmcp" not in sys.modules
assert any(
    str(p).endswith("licenses/THIRD_PARTY_NOTICES.md")
    for p in distribution("xp-libs-analytics").files
)
catalog = json.loads(files("xp_libs_analytics.errors").joinpath("catalog.json").read_text())
assert len(catalog) == 79
bundle = files("xp_libs_analytics").joinpath("skills/generic-analytics")
assert bundle.joinpath("SKILL.md").is_file()
assert bundle.joinpath("references/query-language-full.md").is_file()
assert bundle.joinpath("references/string-matching-full.md").is_file()
assert bundle.joinpath("examples/queries/01_count_all.yaml").is_file()
assert len(list(bundle.joinpath("examples/queries").iterdir())) == 28
engine = AnalyticsEngine()


class Parameters(BaseModel):
    minimum: int = 1


engine.register_records("registered_smoke", [{"value": 0}, {"value": 2}])
registered = ParameterizedYamlQuery(
    """version: analytics.query/v1
dataset: {name: registered_smoke}
filters: [{field: /value, op: gte, value: {$param: minimum}}]
aggregations: [{op: count, as: rows}]
""",
    Parameters,
)
assert engine.query_parameterized(registered)["rows"] == [{"rows": 1}]
handle = engine.register_records("dataset_1", [{"x": 2}, {"x": 4}, {}])
text = f"""version: analytics.query/v1
dataset: {{name: {handle.name}}}
aggregations:
  - {{op: avg, field: /x, as: mean}}
  - {{op: missing_count, field: /x, as: absent}}
"""
result = engine.query_yaml(text)
assert result["rows"] == [{"mean": 3.0, "absent": 1}], result
print("Installed package/resources/query smoke passed")

# RapidFuzz is required by the core; this trusted smoke skips worker startup only here.

engine.limits = replace(engine.limits, force_matching_isolation=False)
engine.register_records("matching", [{"text": "Peter"}, {"text": "Pter"}])
matching = engine.query_yaml("""version: analytics.query/v1
dataset: {name: matching}
filters: [{field: /text, op: fuzzy, value: Peter, algorithm: ratio, min_score: 85}]
aggregations: [{op: count, as: n}]
""")
assert matching["rows"] == [{"n": 2}], matching
assert matching["matching"]["predicate_complete"]
