import json
from importlib.resources import files

from xp_libs_analytics import AnalyticsEngine
from xp_libs_analytics.errors import ErrorCode


def test_catalog_contract():
    def no_duplicates(pairs):
        result = {}
        for k, v in pairs:
            assert k not in result
            result[k] = v
        return result

    catalog = json.loads(
        files("xp_libs_analytics.errors").joinpath("catalog.json").read_text(),
        object_pairs_hook=no_duplicates,
    )
    assert len(catalog) == 73
    assert set(catalog) == {code.value for code in ErrorCode}
    for code, message in catalog.items():
        assert code == code.upper() and code.replace("_", "").isalnum()
        assert isinstance(message, str) and "Fix:" in message and "Example:" in message
    assert AnalyticsEngine is not None
