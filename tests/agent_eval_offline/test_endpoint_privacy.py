import pytest

from evals.agent_skill.endpoint_security import PrivacyError, PrivacyGuard, private_execution
from evals.agent_skill.reporting import Report, save_report
from evals.agent_skill.scoring import Result


@pytest.mark.parametrize(
    "url",
    [
        "file:///private",
        "ftp://invalid",
        "http://user:password@fake.invalid/v1",
        "https://fake.invalid/v1?secret=x",
        "https://fake.invalid/v1#x",
    ],
)
def test_reject_unsafe_endpoint_forms(url):
    with pytest.raises(PrivacyError):
        PrivacyGuard(url)


def test_redacts_all_exports_and_keys(tmp_path):
    endpoint = "http://private-evaluation.invalid:9876/v1"
    guard = PrivacyGuard(endpoint, "credential-canary")
    result = Result(
        scenario_id="privacy-test",
        category="adversarial",
        mode="skill",
        trial=0,
        status="FAIL",
        explanation=endpoint + " credential-canary",
        answer={"api_key": "credential-canary"},
    )
    report = save_report(
        [result],
        model="synthetic-model",
        skill_hash="a" * 64,
        suite="privacy",
        seed=1,
        guard=guard,
        directory=tmp_path,
        traces=[{"base_url": endpoint, "content": endpoint.replace(":", "%3A")}],
    )
    for path in tmp_path.iterdir():
        text = path.read_text()
        assert "private-evaluation.invalid" not in text and "credential-canary" not in text
        assert endpoint not in text
    assert Report.model_validate_json((tmp_path / "results.json").read_text()) == report
    with pytest.raises(PrivacyError):
        guard.assert_safe({"leak": endpoint})
    with private_execution():
        print(endpoint)


def test_known_secrets_in_dictionary_keys_are_rejected():
    guard = PrivacyGuard("http://private.invalid/v1", "a-secret")
    with pytest.raises(PrivacyError):
        guard.assert_safe(guard.sanitize({"a-secret": "value"}))
