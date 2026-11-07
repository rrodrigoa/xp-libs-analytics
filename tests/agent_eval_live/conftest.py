"""Live evaluation is opt-in and cannot run through ordinary PR tests."""

import os

import pytest


@pytest.fixture(scope="session")
def live_config():
    if os.environ.get("XP_ANALYTICS_RUN_LIVE_EVALS") != "1":
        pytest.skip("Enable live agent evaluation explicitly")
    endpoint = os.environ.get("XP_ANALYTICS_EVAL_ENDPOINT")
    model = os.environ.get("XP_ANALYTICS_EVAL_MODEL")
    if not endpoint or not model:
        pytest.fail("Live endpoint and model must be supplied at runtime")
    return endpoint, model, os.environ.get("XP_ANALYTICS_EVAL_API_KEY", "")
