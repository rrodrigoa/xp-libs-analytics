# ADR-003: Snapshot execution

Accepted. Every query resolves one immutable owned dataset. Separate sources, sinks, ports, definitions and execution IDs preserve extension seams. Joins, unions, multiple outputs and continuous state are rejected in V1. This keeps snapshot evidence and consistency meaningful.
