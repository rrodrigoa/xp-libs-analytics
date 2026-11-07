# Build and release operations

This checkout is a local build. GitHub protection, index ownership, Trusted Publishers and public publication are not configured here.

Use Python 3.12+ and reviewed dependency constraints. Run README checks, resource probes, audit and inventory. Build wheel/sdist once with `python -m build`; run `twine check`; install each in a fresh environment and execute `scripts/smoke.py` and CLI help. Verify optional MCP separately. Preserve MIT and third-party notices.

Before first public release, confirm availability and control of PyPI/TestPyPI name `xp-libs-analytics`; an index 404 does not reserve a name or establish trademark rights. Configure a real repository and monitored security contact. Protect main, require review and CI, set actual CODEOWNERS, and configure environment reviewers and tag policies.

Register separate [Trusted Publishers](https://docs.pypi.org/trusted-publishers/) matching repository owner, `release.yml`, and `testpypi`/`pypi` environments. No long-lived tokens are used. Only protected publication jobs receive `id-token: write`. PR tokens are read-only; fork PRs cannot publish.

The release workflow validates tag/version, runs quality gates, builds once, smoke-tests artifacts and records SHA256 hashes. It publishes to protected TestPyPI, downloads and compares the exact wheel, smoke-tests that fetched wheel, then publishes identical artifacts through protected PyPI. Never rebuild between stages or replace an existing version.

After publication, verify a fresh PyPI install, packaged resources, CLI and an actual YAML query; record release SHA/hashes. Workflow files cannot configure account protections or prove hosted CI execution. Follow the [GitHub setup checklist](GITHUB_SETUP.md) before enabling publication.
