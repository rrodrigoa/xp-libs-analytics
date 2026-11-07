import re
from pathlib import Path

import yaml


def test_workflow_permissions_pins_and_fork_safety():
    for path in Path(".github/workflows").glob("*.yml"):
        text = path.read_text()
        assert "pull_request_target" not in text
        for action in re.findall(r"uses: ([^\s#]+)", text):
            assert re.search(r"@[0-9a-f]{40}$", action), action
        workflow = yaml.safe_load(text)
        assert workflow["permissions"] == {"contents": "read"}
        for name, job in workflow["jobs"].items():
            if job.get("permissions", {}).get("id-token") == "write":
                assert path.name == "release.yml"
                assert job["environment"] in ("pypi", "testpypi")
                assert name in ("pypi", "testpypi")
    release = yaml.safe_load(Path(".github/workflows/release.yml").read_text())
    assert release["jobs"]["pypi"]["needs"] == "verify-testpypi"
    assert release["jobs"]["testpypi"]["needs"] == "build"
