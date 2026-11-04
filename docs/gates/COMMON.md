# Common gate acceptance — approved PROCESS v2.20

This document contains the shared production/executor, source, and migration constraints split from the approved consolidated [PROCESS](../../PROCESS.md). Active gate-specific predicates live in [P3](P3.md), [P4–P6](P4-P6.md), and [P7](P7.md). [P1–P2](P1-P2.md) is a retired historical contract only. Older version-change narratives remain in Git history.

**Owner-approved v2.20 (2026-11-03):** P1/P2 retired; active acceptance is nine gates per checkpoint (P3–P6 and P7.1–P7.5). Historical P1/P2 receipts do not count toward M1.

## Heavy acceptance execution and retention (owner-approved 2026-11-02)

P3–P6 and P7.1–P7.5 are the **nine on-demand acceptance gates**, often more expensive than unit/integration regression tests. A gate earns PASS after **one successful execution of its real production path** with the approved criteria. That PASS can be retained across subsequent unrelated changes; no all-gates rerun, hourly acceptance CI, permanent large test fixture set or gate-only simulator is required. For a completed gate, a minimal persistent checkpoint+gate `PASS` timestamp is sufficient documentation. Existing executable source, configuration and ordinary run history may support later investigation; no separate JSON report, committed trace, hash ledger or `docs/evidence/` artifact is a prerequisite for recording a genuine PASS.

Revalidate **only the materially affected gates** if behavior, source rules, target/scenario, chosen backend or scoring changes undermine the original acceptance. Do not invalidate merely because a different commit landed. Preserve honest compatibility between the P3 gear-score smoke, the independent 100-mob leveling objective (P4–P6), and the separately pinned DPS objective (P7); historical PASS never upgrades incompatible or unexecuted gates. Normal focused regression tests can run frequently but do not themselves constitute heavy acceptance.

## 2. One truthful scoreboard; 148 checkpoints

The initial exact acceptance register has **148** checkpoints: 36 unrestricted = nine classes × levels 20, 30, 40, 60; 112 spec-constrained = Druid four profiles × four levels (16) and the other eight classes three profiles × four levels (96). The order is determined by the OVERALL PLAN, not invented inside a W round. A checkpoint counts only if **P3–P6 and P7.1–P7.5 all PASS** on the same pinned ruleset and compatible production engine semantics. P3 is the representative native-backed gear-score smoke; P4–P6 use genuinely coupled continuous 100-mob leveling; P7.1–P7.5 use a separate pinned, direct-native stationary DPS benchmark. The different objective is explicit, never disguised as a 100-mob result. Stale, partial, synthetic, proxy-only or blocked evidence never counts as PASS. Report both actual accepted count and remaining blocker.

P3–P6 and the five named P7 subgates are the approved gates; **no additional hidden gate** may be introduced. A chosen source ingestion technique, full external catalogue scrape, raw-byte attestation, perfection of every item effect, or elaborate verification methodology is not an additional P3 prerequisite. Better source completeness is desirable backlog work, not automatically an acceptance veto.


### Backend names and checkpoint acceptance (USER-REVISED 2026-10-26)

- **`dsim` = legacy Decisions**: historical optimizer and optional diagnostic challenger, no longer the mandatory P7 reference; not automatically an active-gate production executor.
- **`gsim` = Generic Sim**: existing source-backed GameIR/CombatRuntime, 2D world and continuous chainpull.
- **`msim` = MythicSim**: selected genuine pinned **Rust or Go** combat/spell/talent/resource engine; Rust preferred, Go fully valid. **`hybrid` = selected native MythicSim executor + actual gsim 2D world/controller**, one shared monotonic clock and strict event ownership. Do not splice engine outputs or treat untested APIs as integrated.
- The active public gate entry point is `python tools/wf_gate.py --class <class> --level <level> --gate P3` (and P4–P6 or P7.1–P7.5). Without requiring a new flag, show available `gsim`, `msim-rust`, `msim-go`, selected live `hybrid`, evidence provenance and blockers. An unavailable alternative is not a blocker for a passing selected executor.
- **Retired P1/P2:** MythicSim native prepare/execute remains authoritative for spell/talent availability, legality and effects wherever active gates consume candidates. No separate P1/P2 acceptance run, PASS or M1 row is required or allowed.
- **Per-checkpoint P3–P6, P7.1–P7.5**: all gates require a mutually compatible, actually executed production pipeline on the SAME pinned source, ruleset and combat semantics; P3 is a contextual gear-score smoke, P4–P6 share their spatial leveling objective, and P7's five subgates share one direct-native stationary single-target DPS objective; different scores or semantics cannot be spliced across backends. A gsim-only PASS remains valid until displaced by real successor evidence. Diagnostic backend differences are recorded but do not automatically fail a passing backend.
- When **earning** a new `PASS`, genuinely execute the selected production backend (`native-msim-rust`, `native-msim-go`, `gsim`, `hybrid-rust` or `hybrid-go`) with the required pinned source/ruleset/config and observable behavior. Source/runtime identities and detailed traces can remain in the ordinary run's outputs/history; the **persistent PASS record itself may contain only its timestamp**. Do not require an extra evidence-export layer. A compile, registration, mock, synthetic 2D or replay-only trace is not a PASS.
- **Ownership**: selected native MythicSim Rust/Go engine owns combat hit/damage/heal, resource, cooldown, talent, spell and gear effects it actually implements; gsim world owns geometry/facing/range, pulls, movement/CC and world-side behavior. One shared event chronology; no duplicate mechanics. Native pushback etc can count if behavior-tested without reimplementation.
- Real pinned Rust/Go runs are the acceptance executor for P7's stationary DPS reference; they do not substitute for P4–P6's genuinely coupled spatial 100-mob combat/recovery/survival. Compatible historical accepted P7 evidence remains usable; no unexecuted run earns PASS.

## Migration and removal policy (USER-REVISED 2026-10-26)

1. Implement/test **Druid L60** with the existing canonical gate CLI; report gsim plus selected `msim-rust` or `msim-go`/hybrid evidence separately. Prefer Rust when actually integrated and pinned; no inference from source code or build green.
2. Grow to all nine classes at **L60 and L40** on the real selected Rust/Go + gsim-2D production path, covering class/profile mechanics and preserving continuous resource/CC/cooldowns/recovery. Inventory or compilation alone is insufficient.
3. **Do not remove gsim or its working tests** while selected Rust/Go/hybrid is incomplete. Keep any valid gsim PASS, and retire older paths only after demonstrated cross-class L40/L60 integration with L20/L30 preserved and regression tests. No new gate or reduced 148 scope.
4. `dsim` stays available as an optional historical diagnostic challenger even if gsim is eventually retired; it is not P7 evidence. No class-specific winner presets, silent ability exclusions or new hidden gate is authorized.
5. No separate "wrapper green" counter or backend-migration checkpoint is added to the 148 scoreboard; report any migration progress as diagnostic until real P3–P6 and P7.1–P7.5 acceptance.

## Mandatory rule: no imaginary server-measurement or semantic-certification gates

1. Use the best available game data and known mechanics, including established Classic mechanics as defaults **unless concrete evidence indicates Forever differs**. Keep the chosen assumption and source visible where it materially affects a result.
2. Implement the mechanic via canonical sourced data and the selected executable gsim/msim-rust/msim-go/hybrid route, test actual observable behavior, then advance to the next acceptance gate. (The new backend-neutral rule supersedes the gsim-only wording in v2.2.)
3. Do **not** demand a Forever live-server measurement, internal-server access, build-to-build semantic parity proof, source-version bridge, or standalone semantic-verification round merely to accept an otherwise working implementation. No such extra gate exists.
4. Investigate uncertainty only when there is an **actionable** missing implementation, failing behavior test, contradictory data, or a demonstrated material effect on outcome/comparability. Describe the exact defect and fix it; don't block progress on speculative provenance concerns.
5. Synthetic edge-case inputs (for example 60% spell hit) are legitimate unit-test fixtures but **must be labeled synthetic**, never described as measured Forever mechanics. Distinguish test fixture, Classic-derived default, source data, and real 100-mob simulation.
6. Do not invent source values or silently override actual Forever-specific data. Where Forever-specific evidence contradicts a Classic default, use the better supported rule and rerun affected tests.
7. P1/P2 are retired; their former binary PASS/FAIL contracts are historical only. Native prepare/execute remains the authority for spell/talent availability, legality and effects.
8. This preserves the active P3–P7.5 gate identities and genuine source-native results. Exact current predicates are in their canonical gate files; no duplicate proof obligations are implied.
