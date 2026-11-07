import subprocess
import sys


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
