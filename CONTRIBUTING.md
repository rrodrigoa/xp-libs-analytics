# Contributing

Use Python 3.12+ and install `-c requirements-lock.txt -e '.[dev,mcp]'`. Run the verification commands in README before submitting a PR. Tests use synthetic fixtures and an independent Python oracle. Every YAML example must execute through the restricted parser, strict AST, semantic planner and backend.

Preserve the [language](docs/query-language.md), [parser boundary](docs/yaml-security.md), and [error contract](docs/errors.md). Messages live exclusively in `src/xp_libs_analytics/errors/catalog.json`; code additions require enum, tests, and changelog changes. Semantic changes require schema/fixture review and a version decision.

PR CI enforces lint, format, strict mypy, >=90% aggregate coverage and >=95% branch coverage for each critical module. Branchless critical modules require >=95% statement coverage. Run security and actual FastMCP-client integration tests.

Original contributions are MIT licensed. Preserve third-party notices. Never put credentials, real private records, or sensitive schemas in code, issues, fixtures, logs or CI artifacts. See SECURITY.md for disclosure and docs/releasing.md for protected OIDC publishing.
