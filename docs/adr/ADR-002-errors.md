# ADR-002: One canonical error catalog

Accepted. `errors/catalog.json` alone owns user-visible messages. The closed enum and parity tests cover all 60 codes. Runtime details carry safe locations and trace IDs separately. Some codes reserve transport/source classifications; tests exercise all envelopes without claiming every reserved code is emitted by default.
