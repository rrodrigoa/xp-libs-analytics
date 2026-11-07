"""Smoke wheel, sdist and optional MCP in fresh non-editable environments."""

import hashlib
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def checked(args, **kwargs):
    subprocess.run(args, check=True, **kwargs)  # noqa: S603 -- fixed local interpreter/CLI args


def main():
    root = Path(__file__).resolve().parents[1]
    wheel = next((root / "dist").glob("*.whl"))
    sdist = next((root / "dist").glob("*.tar.gz"))
    report = []
    for artifact in (wheel, sdist):
        with tempfile.TemporaryDirectory(prefix="xp-libs-analytics-smoke-") as temp:
            folder = Path(temp)
            venv.create(folder, with_pip=True)
            bindir = folder / ("Scripts" if os.name == "nt" else "bin")
            python = str(bindir / ("python.exe" if os.name == "nt" else "python"))
            checked([python, "-m", "pip", "install", str(artifact)], cwd=folder)
            checked([python, str(root / "scripts/smoke.py")], cwd=folder)
            cli = str(
                bindir / ("xp-libs-analytics.exe" if os.name == "nt" else "xp-libs-analytics")
            )
            checked([cli, "--help"], cwd=folder)
            if artifact == wheel:
                checked([python, "-m", "pip", "install", str(artifact) + "[mcp]"], cwd=folder)
                checked(
                    [
                        python,
                        "-c",
                        "from xp_libs_analytics.mcp.server import create_server; "
                        "assert create_server()",
                    ],
                    cwd=folder,
                )
            report.append(
                {
                    "artifact": artifact.name,
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "fresh_install": "passed",
                }
            )
    target = root / "docs/evidence/distributions.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
