## Description and motivation

## Affected contracts / V1 operators / public API
- [ ] Updated `QUERY_LANGUAGE_V1.md` / semantic version decision if applicable
- [ ] New/changed error codes and catalog parity (single `catalog.json`)
- [ ] Updated agent skill and machine-valid examples if behavior changed

## Safety and threat model
- [ ] No unsafe SQL/Python/UDF/network/file access introduced
- [ ] Authorization and handle ownership unchanged or explicitly reviewed
- [ ] Resource budgets and input/output leakage considered
- [ ] No real records/secrets in fixtures, logs or artifacts

## Testing evidence (actual)
- [ ] Positive and negative cases
- [ ] Penetration/security regression for affected boundary
- [ ] Property/fuzz invariants
- [ ] FastMCP client tests if MCP changed
- [ ] Line and branch coverage thresholds
- [ ] Fresh wheel install/import/skill/catalog smoke

## Performance and operational impact

## Backward compatibility / migration

## Reviewer notes / release risk
