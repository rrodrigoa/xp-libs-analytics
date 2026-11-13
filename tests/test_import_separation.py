import subprocess
import sys


def test_typed_sdk_and_mcp_do_not_load_analytics_yaml_parser():
    code = """
import asyncio
import importlib.abc
import sys

class BlockYaml(importlib.abc.MetaPathFinder):
    block_dependency = True

    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'xp_libs_analytics.parser' or (
            self.block_dependency and fullname.split('.')[0] == 'yaml'
        ):
            raise ImportError('YAML imports intentionally blocked')

blocker = BlockYaml()
sys.meta_path.insert(0, blocker)
from xp_libs_analytics import AnalyticsEngine, AnalyticsQuery
from xp_libs_analytics.mcp.server import create_server

async def main():
    engine = AnalyticsEngine()
    engine.register_records('observations', [{'x': 2}])
    query = AnalyticsQuery.model_validate({
        'version': 'analytics.query/v1',
        'dataset': {'name': 'observations'},
        'aggregations': [{'op': 'count', 'as': 'n'}],
    })
    assert engine.query_typed(query)['rows'] == [{'n': 1}]
    assert 'yaml' not in sys.modules and 'xp_libs_analytics.parser' not in sys.modules
    # FastMCP imports PyYAML for its own skill provider.
    blocker.block_dependency = False
    from fastmcp import Client

    async with Client(create_server(engine, registered_queries={'count': query})) as client:
        result = await client.call_tool('analytics_query_by_key', {'key': 'count'})
        assert result.structured_content['rows'] == [{'n': 1}]
    assert 'xp_libs_analytics.parser' not in sys.modules

asyncio.run(main())
"""
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603 -- fixed test program


def test_worker_bootstrap_does_not_load_native_runtimes_before_limits():
    code = """
import sys
from xp_libs_analytics.engine.worker import run_worker
assert callable(run_worker)
assert 'polars' not in sys.modules and 'rapidfuzz' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603 -- fixed test program


def test_core_works_with_all_mcp_and_evaluation_imports_blocked():
    code = """
import importlib.abc, sys
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fastmcp','mcp','inspect_ai','evals','openai'}:
            raise ImportError('Optional package intentionally blocked')
sys.meta_path.insert(0, BlockOptional())
from xp_libs_analytics import AnalyticsEngine
engine=AnalyticsEngine()
handle=engine.register_records('observations', [{'x':2},{'x':4}])
text=(f"version: analytics.query/v1\\ndataset: {{name: {handle.name}}}\\n"
      "aggregations: [{op: avg, field: /x, as: mean}]")
assert engine.query_yaml(text)['rows']==[{'mean':3.0}]
assert not any(name.startswith(('fastmcp','inspect_ai','evals')) for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603 -- fixed test program
