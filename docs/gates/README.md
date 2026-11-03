# Gate contracts — PROCESS v2.20

[PROCESS](../../PROCESS.md) is the short governance and development contract; this directory holds its **normative active acceptance rules**. Owner-approved v2.20 retires P1 (abilities) and P2 (talents) as formal gates. The active checkpoint contract is P3–P6 and P7.1–P7.5: nine gates per checkpoint, 1,332 gate targets across the unchanged 148-checkpoint scope. The underlying spell and talent functionality remains part of the native game engine and the actual optimizer search space; no separate P1/P2 acceptance or proof is required.

| Contract | Owns |
| --- | --- |
| [COMMON](COMMON.md) | 148-checkpoint accounting; selected engines, provenance, migration and source discipline |
| [P3](P3.md) | Top-five-by-ilvl legal gear smoke and meaningful stat weights |
| [P4–P6](P4-P6.md) | Independent 30s/300s whole-build searches, continuous 100-mob evaluation and saturation |
| [P7](P7.md) | Exact saved MythicSim encounter, live 2D↔native execution, individual and joint independent DPS searches |
| [RUNTIME_AUTHORITY](RUNTIME_AUTHORITY.md) | Current CLI live-provider contract (implementation guide, not a new acceptance gate) |

P1/P2 gate contracts and their acceptance-specific implementation guide are retired and removed. Their prior approval history remains in Git. When changing an active acceptance rule, obtain explicit owner approval and update the relevant canonical gate document with a reviewed commit. Git records history; do not append approval transcripts to these living contracts.
