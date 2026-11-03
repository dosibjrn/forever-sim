# Common gate acceptance — PROCESS v2.20

This document contains the shared production/executor, source and migration constraints split from the approved [PROCESS](../../PROCESS.md). The active gate predicates are [P3](P3.md), [P4–P6](P4-P6.md) and [P7](P7.md). P1 (abilities) and P2 (talents) are retired as formal acceptance gates; their underlying mechanics remain part of the selected native engine and actual optimizer candidate space. Prior P1/P2 gate criteria are historical Git history, not active requirements.

## Heavy acceptance execution and retention

P3–P6 and P7.1–P7.5 are **on-demand acceptance tests**, often more expensive than unit/integration regression tests. A gate earns PASS after **one successful execution of its real production path** with the approved criteria. That PASS can be retained across subsequent unrelated changes; no all-gates rerun, hourly acceptance CI, permanent large test fixture set or gate-only simulator is required. For a completed gate, a minimal persistent checkpoint+gate `PASS` timestamp is sufficient documentation. Existing executable source, configuration and ordinary run history may support later investigation; no separate JSON report, committed trace, hash ledger or `docs/evidence/` artifact is a prerequisite for recording a genuine PASS.

Revalidate **only the materially affected gates** if behavior, source rules, target/scenario, chosen backend or scoring changes undermine the original acceptance. Do not invalidate merely because a different commit landed. Preserve honest compatibility between the independent 100-mob objective (P4–P6) and the separately pinned DPS objective (P7); historical PASS never upgrades incompatible or unexecuted gates. Normal focused regression tests can run frequently but do not themselves constitute heavy acceptance.

## One truthful scoreboard; 148 checkpoints

The exact acceptance register has **148** checkpoints: 36 unrestricted = nine classes × levels 20, 30, 40, 60; 112 spec-constrained = Druid four profiles × four levels (16) and the other eight classes three profiles × four levels (96). A checkpoint counts only if **P3–P6 and P7.1–P7.5 all PASS** on the same pinned ruleset and compatible production engine semantics. P3 is the gear smoke; P4–P6 use the continuous 100-mob leveling objective; P7.1–P7.5 use the same production integration in a separate pinned MythicSim DPS-reference scenario. Never disguise the different objectives or splice incompatible proofs. Stale, partial, synthetic, proxy-only or blocked evidence never counts as PASS.

There are **nine active gates per checkpoint** and **1,332 checkpoint×gate PASS targets**. No additional hidden gate may be introduced. P1/P2 are not gates, prerequisites, ledger rows or checkpoint blockers. A chosen source ingestion technique, full external catalogue scrape, raw-byte attestation, perfection of every item effect, or elaborate verification methodology is not an additional P3 prerequisite. Better source completeness is desirable backlog work, not automatically an acceptance veto.

### Backend names and checkpoint acceptance

- **`dsim` = legacy Decisions**: historical optimizer and optional diagnostic challenger, no longer the mandatory P7 reference.
- **`gsim` = Generic Sim**: existing source-backed GameIR/CombatRuntime, 2D world and continuous chainpull.
- **`msim` = MythicSim**: selected genuine pinned **Rust or Go** combat/spell/talent/resource engine; Rust preferred, Go fully valid. **`hybrid` = selected native MythicSim executor + actual gsim 2D world/controller**, one shared monotonic clock and strict event ownership. Do not splice engine outputs or treat untested APIs as integrated.
- The public gate entry point is `python tools/wf_gate.py --class <class> --level <level> --gate P3` (and P4–P7.5). It reports the selected production executor, provenance and blockers. An unavailable alternative is not a blocker for a passing selected executor.
- **Per-checkpoint P3–P6 and P7.1–P7.5:** all gates require a mutually compatible, actually executed production pipeline on the SAME pinned source, ruleset and combat semantics. P4–P6 share their leveling objective; the five P7 subgates share one separate pinned single-target DPS objective. Different scores or semantics cannot be spliced across backends. A gsim-only PASS remains valid until displaced by real successor evidence. Diagnostic backend differences are recorded but do not automatically fail a passing backend.
- When **earning** a new PASS, genuinely execute the selected production backend (`native-msim-rust`, `native-msim-go`, `gsim`, `hybrid-rust` or `hybrid-go`) with the required pinned source/ruleset/config and observable behavior. Source/runtime identities and detailed traces can remain in ordinary run outputs/history; the **persistent PASS record itself may contain only its timestamp**. Do not require an extra evidence-export layer. A compile, registration, mock, synthetic 2D or replay-only trace is not a PASS.
- **Ownership:** selected native MythicSim Rust/Go engine owns combat hit/damage/heal, resource, cooldown, talent, spell and gear effects it actually implements; gsim world owns geometry/facing/range, pulls, movement/CC and world-side behavior. One shared event chronology; no duplicate mechanics. Native pushback etc. can count if behavior-tested without reimplementation.
- Native Rust/Go single-fight runs may support isolated P7.1.2, but do not replace continuous 2D combat/recovery/survival in P4–P6 or live gsim-2D↔native feedback for P7.1.3/P7.2–P7.5. The owner's individually accepted historical Balance L60 P7.1 Rust result remains CLOSED, with its absence of Go/live-2D evidence disclosed; it does not waive other/new production obligations.

## Migration and removal policy

1. Implement/test **Druid L60** with the existing canonical gate CLI; report gsim plus selected `msim-rust` or `msim-go`/hybrid evidence separately. Prefer Rust when actually integrated and pinned; no inference from source code or build green.
2. Grow to all nine classes at **L60 and L40** on the real selected Rust/Go + gsim-2D production path, covering class/profile mechanics and preserving continuous resource/CC/cooldowns/recovery. Inventory or compilation alone is insufficient.
3. **Do not remove gsim or its working tests** while selected Rust/Go/hybrid is incomplete. Keep any valid gsim PASS, and retire older paths only after demonstrated cross-class L40/L60 integration with L20/L30 preserved and regression tests. The 148-checkpoint scope remains unchanged.
4. `dsim` stays available as an optional historical diagnostic challenger even if gsim is eventually retired; it is not P7 evidence. No class-specific winner presets, silent ability exclusions or new hidden gate is authorized.
5. No separate "wrapper green" counter or backend-migration checkpoint is added to the 148 scoreboard; report any migration progress as diagnostic until real P3–P6 and P7.1–P7.5 acceptance.

## Mandatory rule: no imaginary server-measurement or semantic-certification gates

1. Use the best available game data and known mechanics, including established Classic mechanics as defaults **unless concrete evidence indicates Forever differs**. Keep the chosen assumption and source visible where it materially affects a result.
2. Implement the mechanic via canonical sourced data and the selected executable gsim/msim-rust/msim-go/hybrid route, test actual observable behavior, then advance to the next acceptance gate.
3. Do **not** demand a Forever live-server measurement, internal-server access, build-to-build semantic parity proof, source-version bridge, or standalone semantic-verification round merely to accept an otherwise working implementation. No such extra gate exists.
4. Investigate uncertainty only when there is an **actionable** missing implementation, failing behavior test, contradictory data, or a demonstrated material effect on outcome/comparability. Describe the exact defect and fix it; don't block progress on speculative provenance concerns.
5. Synthetic edge-case inputs (for example 60% spell hit) are legitimate unit-test fixtures but **must be labeled synthetic**, never described as measured Forever mechanics. Distinguish test fixture, Classic-derived default, source data, and real 100-mob simulation.
6. Do not invent source values or silently override actual Forever-specific data. Where Forever-specific evidence contradicts a Classic default, use the better supported rule and rerun affected tests.
7. This does not waive the actual P3–P6 and P7.1–P7.5 criteria, real 30/300-second leveling searches, independent 100-mob measurements, or the five externally pinned P7 checks. It removes no remaining production predicate.
