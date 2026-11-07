# Security Policy

This project executes analytical queries over potentially sensitive JSON records. Never open an issue containing real records, secrets, access tokens, personal information, proprietary schema, or cross-tenant dataset metadata.

## Reporting vulnerabilities

After repository creation, configure a private GitHub security advisory reporting channel (Security → Advisories → Report a vulnerability) and specify an owner-maintained contact method here. **Do not invent or publish an unmonitored email address.** Until contact is configured, do not publish a public release claiming a formal security-response channel.

## Supported versions

Document supported release branches once V1 ships. Security fixes require a new version; never overwrite PyPI artifacts.

## Threat model priorities

Cross-context name resolution and snapshot identity, agent/tool input injection, denial of service via large or recursive JSON, query amplification, type confusion and cast correctness, error/meta-data disclosure, malicious dependencies, wheel supply chain, and unauthorized output channels. Reference `docs/architecture.md` and `README.md`. Security claims require executed tests and review evidence.
