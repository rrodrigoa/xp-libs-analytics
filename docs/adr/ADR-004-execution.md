# ADR-004: Host budgets and isolated workers

Accepted. The trusted SDK defaults to direct execution. Untrusted deployment uses isolated workers and constrained hosting/container resources. MCP defaults to isolated execution and disabled uploads. Workers have OS CPU/memory ceilings and parent-enforced wall deadlines; parent parsing/admission remain separately bounded. Fields, scopes, clocks, quotas and identity come only from trusted hosts.
