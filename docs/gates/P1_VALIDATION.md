> **Retired by owner-approved PROCESS v2.20 on 2026-11-03.** P1 is not an active acceptance gate. This guide is retained for historical context only; do not run it for acceptance or record P1 progress in M1. The active gates are P3–P6 and P7.1–P7.5.

# P1 — historical native ability validation guide (retired)

**Historical status:** This guide described the former P1 validation contract under PROCESS v2.11. P1 was retired by PROCESS v2.20 on 2026-11-03; this file is no longer an acceptance guide and does not authorize P1 runs or M1 records.

## Boundary

P1 validates **what abilities the selected production simulator can do**;
it does not require a particular code architecture.

1. **Selected native inventory:** use the (class, level, spec, talents, ruleset)
   candidate space and MythicSim's own native prepare/validation to decide
   which spell/rank requests are valid or unsupported. Forever must not maintain
   trainer, learned-spellbook, source-acquisition-batch or quest-proof checks.
   Historical source-index lists may help diagnostics, but cannot override native.
2. **Applicability:** keep the explicitly approved, scenario-specific
   `DOES_NOT_AFFECT_SIM` list separate from test results. Identify autoattacks,
   pet actions, passive/auxiliary spells and uncertain grants by their real roles;
   never count a pet skill as a missing player cast action. Changing the scenario
   requires reconsidering its applicability decisions.
3. **Production execution:** for combat effects, run real pinned MythicSim Rust/Go
   with appropriate resource/form/target/trigger conditions. Observe native
   damage, healing, overhealing, resources, stats, real auras/DoTs, CC or analogous
   behavior. A deterministic controlled positive/negative experiment or
   comparable targeted real-runtime assertion is enough. A per-spell 100-mob
   fight, raid log, or vast repeated RNG test is **not** a P1 requirement.
4. **World-dependent mechanics:** use the *real* gsim 2D world coupled to the
   selected MythicSim executor only when the tested behavior depends on
   range, movement, geometry, facing or another world-owned effect. Do not
   demand a 2D wrapper for a native direct-damage/heal effect.
5. **Outcome and candidate reachability:** label each source-legal applicable
   ability as executed behavior observed, not observed, unexecutable,
   or conditional trigger unresolved. Native INVALID and UNSUPPORTED remain distinct. Confirm
   actual selected-engine candidate usability as part of final P1, but never
   equate a missing Python GameIR action with a missing MythicSim ability.

**Important:** equal spell registration, a cast counter, a mock event, a
source-index name, or a non-executed CI test is not behavioral proof.
An APL entry removal is useful as a *diagnostic* but can change timing and
other action selection; it does not alone prove a spell's isolated effect.
No backend union of incomplete implementations can be treated as P1 PASS.

## Retirement

The P1-specific runtime stack was removed on 2026-11-03 after P1 was retired
from formal acceptance by PROCESS v2.20. This includes the Forever GameIR
source/inventory provider, the separate selected-Rust P1 diagnostic client and
CLI, their P1-only tests, the P1-native workflow, and its scenario-applicability
configuration.

No P1 runner or native P1 diagnostic is maintained. Do not recreate these
entrypoints or schedule P1 runs. Historical source data, retained evidence and
P1 ledger rows remain unchanged; historical P1 rows are excluded from the
active M1 score. The active gates are P3–P6 and P7.1–P7.5.
