# Gate contracts — PROCESS v2.12

[PROCESS](../../PROCESS.md) is the short governance and development contract; this directory holds its **normative acceptance rules**. The original v2.10 split changed locations only. Owner-approved v2.11 clarifies **P1 validation** on the selected native executor (no mandatory GameIR wrapper); it leaves eligible classes, run budgets, other gate criteria and previously approved outcomes unchanged. The former 50 KB consolidated PROCESS and its approval history remain in Git.

**Owner-approved v2.12:** these are on-demand, potentially expensive production acceptance tests, not an always-on unit-test matrix. One real successful gate execution earns a PASS; persistent documentation may be only PASS + timestamp, and only materially invalidated gates require revalidation. No new proof bundle or extra gate is required; underlying P1–P7.5 predicates and budgets remain unchanged.

| Contract | Owns |
| --- | --- |
| [COMMON](COMMON.md) | 148-checkpoint accounting; selected engines, provenance, migration and source discipline |
| [P1–P2](P1-P2.md) | Legal abilities/ranks and fully behavior-tested talents; updated P1 native validation boundary |
| [P1 validation guide](P1_VALIDATION.md) | Source inventory, native effect testing, scenario exclusions and unresolved diagnostics (implementation guide) |
| [P3](P3.md) | Top-five-by-ilvl legal gear smoke and meaningful stat weights |
| [P4–P6](P4-P6.md) | Independent 30s/300s whole-build searches, continuous 100-mob evaluation and saturation |
| [P7](P7.md) | Exact saved MythicSim encounter, live 2D↔native execution, individual and joint independent DPS searches |
| [RUNTIME_AUTHORITY](RUNTIME_AUTHORITY.md) | Current CLI live-provider contract (implementation guide, not a new acceptance gate) |

When changing an acceptance rule, obtain explicit owner approval and update the relevant *canonical* gate document with a reviewed commit. Git records history; do not append approval transcripts to these living contracts.
