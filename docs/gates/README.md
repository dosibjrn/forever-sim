# Gate contracts — PROCESS v2.20

[PROCESS](../../PROCESS.md) is the short governance and development contract; this directory holds its **normative acceptance rules**. The original v2.10 split changed locations only. The v2.11 P1 and v2.17 P2 rules are retained below as historical context, but owner-approved v2.20 retires both gates from formal acceptance. The former consolidated PROCESS and approval history remain in Git.

**Owner-approved v2.20 (2026-11-03):** the active acceptance set is P3–P6 and P7.1–P7.5 (nine gates per checkpoint, 1,332 pairs across 148 checkpoints). P1/P2 are retired; their historical TSV rows are ignored by M1. No new P1/P2 PASS/PARTIAL may be recorded. The v2.12 on-demand cadence still applies to active gates.

| Contract | Owns |
| --- | --- |
| [COMMON](COMMON.md) | 148-checkpoint accounting; selected engines, provenance, migration and source discipline |
| Retired [P1–P2](P1-P2.md) | Historical contract only; not active acceptance and not counted in M1 |
| [P3](P3.md) | Top-five-by-ilvl legal gear smoke and meaningful stat weights |
| [P4–P6](P4-P6.md) | Independent 30s/300s whole-build searches, continuous 100-mob evaluation and saturation |
| [P7](P7.md) | Exact saved MythicSim encounter, live 2D↔native execution, individual and joint independent DPS searches |
| [RUNTIME_AUTHORITY](RUNTIME_AUTHORITY.md) | Current CLI live-provider contract (implementation guide, not a new acceptance gate) |

When changing an acceptance rule, obtain explicit owner approval and update the relevant *canonical* gate document with a reviewed commit. Git records history; do not append approval transcripts to these living contracts.
