"""Bounded snapshot analytics over arbitrary JSON records and restricted YAML."""

from xp_libs_analytics.engine.native import PolarsQuery
from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.models import AnalyticsQuery
from xp_libs_analytics.policy import Limits, Principal
from xp_libs_analytics.registered import ParameterizedYamlQuery
from xp_libs_analytics.registry import DatasetInfo, DatasetRegistry
from xp_libs_analytics.sdk import AnalyticsEngine

__all__ = [
    "AnalyticsEngine",
    "AnalyticsError",
    "AnalyticsQuery",
    "DatasetInfo",
    "DatasetRegistry",
    "Limits",
    "ParameterizedYamlQuery",
    "PolarsQuery",
    "Principal",
]
__version__ = "0.5.0"
