# Hosting configuration

The workflows in this repository run on GitHub Actions. These account-level controls require a maintainer:

1. Create/connect the repository; enable Actions, dependency alerts and private vulnerability reporting.
2. Set real maintainer identities in `.github/CODEOWNERS.template`, then rename it to CODEOWNERS.
3. Protect main: reviewed PRs, resolved conversations, no force/direct pushes, required `lint-and-type`, OS/Python `tests` matrix, `build-smoke`, audit, CodeQL and dependency review checks. Include `merge_group` when using a merge queue.
4. Configure `testpypi` and `pypi` protected environments, reviewer approval, trusted tag restrictions, and matching index OIDC Trusted Publishers.
5. Test a fork PR and protected release in staging. Confirm fork jobs cannot obtain publishing authority and release promotion preserves artifact hashes.
6. Configure monitored security disclosure, real project metadata and index ownership before a public release.

Workflows use verified immutable action SHAs and least-privilege tokens. Dependabot updates dependency/action pins. CodeQL and dependency review availability depend on repository/account entitlements. Local verification evidence cannot establish hosted check status.
