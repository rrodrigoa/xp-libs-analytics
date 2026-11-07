# Entity inference remains outside snapshot V1

String similarity compares observed values; it does not infer people, devices, aliases or ownership. Distinct records with the same display name remain distinct input records. The engine does not assign identities, expand nicknames or persist cross-query identity tables. Explicit grouping by trusted input identifiers remains an ordinary analytical operation.

V1 exposes bounded predicates and optional matching evidence, not a search/ranking prerequisite or an entity-resolution engine. Reserved entity_inference/entity_resolution/resolve_entities/identities/aliases query roots return MATCH_ENTITY_INFERENCE_UNSUPPORTED. Agents must explain this boundary instead of inventing identity-confidence scores.

A future entity-hypothesis interface would require trusted alias/source provenance, explicit uncertainty, authorization/disclosure policy, temporal identity semantics and its own versioned contract and tests. The source/port and shared typed matching interfaces provide extension seams only; no partial entity implementation is shipped.
