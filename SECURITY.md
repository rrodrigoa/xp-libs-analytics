# Security Policy

XP Libs Analytics executes analytical queries over potentially sensitive JSON records. Vulnerability reports should use synthetic records and omit secrets, access tokens, personal information, private schema, and cross-context dataset metadata.

## Reporting vulnerabilities

Use the repository's private security advisory form (Security → Advisories → Report a vulnerability) when private reporting is available.

## Supported versions

Security fixes are distributed as new package versions. The [changelog](CHANGELOG.md) records version-specific changes.

## Threat model priorities

The library's threat model covers cross-context name resolution, snapshot identity, untrusted tool input, resource exhaustion, type and cast handling, metadata disclosure, dependency and package integrity, and unauthorized output. See the [end-to-end security review](docs/security-review.md) for controls and test evidence.
