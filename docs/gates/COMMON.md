# Common gate acceptance — approved PROCESS v2.10

This document contains the shared production/executor, source, and migration constraints split from the approved consolidated [PROCESS](../../PROCESS.md). Gate-specific predicates live in [P1–P2](P1-P2.md), [P3](P3.md), [P4–P6](P4-P6.md), and [P7](P7.md). Older version-change narratives remain in Git history.

## 2. One truthful scoreboard; 148 checkpoints

The initial exact acceptance register has **148** checkpoints: 36 unrestricted = nine classes × levels 20, 30, 40, 60; 112 spec-constrained = Druid four profiles × four levels (16) and the other eight classes three profiles × four levels (96). The order is determined by the OVERALL PLAN, not invented inside a W round. A checkpoint counts only if **P1–P6 and P7.1–P7.5 all PASS** on the same pinned ruleset and compatible production engine semantics. P1–P6 use the pinned continuous 100-mob leveling objective; P7.1–P7.5 use the *same production integration* in the separate pinned MythicSim DPS-reference scenario. The different objective is explicit, never disguised as a 100-mob result. Stale, partial, synthetic, proxy-only or blocked evidence never counts as PASS. Report both actual accepted count and remaining blocker.

P1–P6 and the five named P7 subgates are the approved gates; **no additional hidden gate** may be introduced. A chosen source ingestion technique, full external catalogue scrape, raw-byte attestation, perfection of every item effect, or elaborate verification methodology is not an additional P3 prerequisite. Better source completeness is desirable backlog work, not automatically an acceptance veto.


### Backend names and checkpoint acceptance (USER-REVISED 2026-10-26)

- **`dsim` = legacy Decisions**: historical optimizer and optional diagnostic challenger, no longer the mandatory P7 reference; not automatically a P1/P2 production executor.
- **`gsim` = Generic Sim**: existing source-backed GameIR/CombatRuntime, 2D world and continuous chainpull.
- **`msim` = MythicSim**: selected genuine pinned **Rust or Go** combat/spell/talent/resource engine; Rust preferred, Go fully valid. **`hybrid` = selected native MythicSim executor + actual gsim 2D world/controller**, one shared monotonic clock and strict event ownership. Do not splice engine outputs or treat untested APIs as integrated.
- The unchanged public gate entry point is `python tools/wf_gate.py --class <class> --level <level> --gate P1` (and P2–P7.5). Without requiring a new flag, show available `gsim`, `msim-rust`, `msim-go`, selected live `hybrid`, evidence provenance and blockers. An unavailable alternative is not a blocker for a passing selected executor.
- **Per-gate P1/P2**: genuine source-legal, behavior-tested execution on `gsim` OR selected `msim-rust`/`msim-go` (live hybrid when world-dependent) can satisfy the gate. Do not reimplement known-good effects just to support a second engine. A fabricated union of incomplete implementations cannot PASS.
- **Per-checkpoint P1–P6, P7.1–P7.5**: all gates require a mutually compatible, actually executed production pipeline on the SAME pinned source, ruleset and combat semantics; P1–P6 share their leveling objective, and the five P7 subgates share one separate pinned single-target DPS objective; different scores or semantics cannot be spliced across backends. A gsim-only PASS remains valid until displaced by real successor evidence. Diagnostic backend differences are recorded but do not automatically fail a passing backend.
- Any reported `PASS` must identify exact evidence kind (`native-msim-rust`, `native-msim-go`, `gsim`, `hybrid-rust`, `hybrid-go`, or external reference), real source/runtime/database/config hashes and executed behavior. A compile, registration, mock, synthetic 2D or replay-only trace is not a PASS.
- **Ownership**: selected native MythicSim Rust/Go engine owns combat hit/damage/heal, resource, cooldown, talent, spell and gear effects it actually implements; gsim world owns geometry/facing/range, pulls, movement/CC and world-side behavior. One shared event chronology; no duplicate mechanics. Native pushback etc can count if behavior-tested without reimplementation.
- Native Rust/Go single-fight runs can support isolated P1/P2 and P7.1.2 but do not replace continuous 2D combat/recovery/survival in P4–P6 or live gsim-2D↔native feedback for P7.1.3/P7.2–P7.5. The owner's individually accepted historical Balance L60 P7.1 Rust result remains CLOSED, with its absence of Go/live-2D evidence disclosed; it does not waive other/new production obligations.

## Migration and removal policy (USER-REVISED 2026-10-26)

1. Implement/test **Druid L60** with the existing canonical gate CLI; report gsim plus selected `msim-rust` or `msim-go`/hybrid evidence separately. Prefer Rust when actually integrated and pinned; no inference from source code or build green.
2. Grow to all nine classes at **L60 and L40** on the real selected Rust/Go + gsim-2D production path, covering class/profile mechanics and preserving continuous resource/CC/cooldowns/recovery. Inventory or compilation alone is insufficient.
3. **Do not remove gsim or its working tests** while selected Rust/Go/hybrid is incomplete. Keep any valid gsim PASS, and retire older paths only after demonstrated cross-class L40/L60 integration with L20/L30 preserved and regression tests. No new gate or reduced 148 scope.
4. `dsim` stays available as an optional historical diagnostic challenger even if gsim is eventually retired; it is not P7 evidence. No class-specific winner presets, silent ability exclusions or new hidden gate is authorized.
5. No separate "wrapper green" counter or backend-migration checkpoint is added to the 148 scoreboard; report any migration progress as diagnostic until real P1–P6 and P7.1–P7.5 acceptance.

## Mandatory rule: no imaginary server-measurement or semantic-certification gates

1. Use the best available game data and known mechanics, including established Classic mechanics as defaults **unless concrete evidence indicates Forever differs**. Keep the chosen assumption and source visible where it materially affects a result.
2. Implement the mechanic via canonical sourced data and the selected executable gsim/msim-rust/msim-go/hybrid route, test actual observable behavior, then advance to the next acceptance gate. (The new backend-neutral rule supersedes the gsim-only wording in v2.2.)
3. Do **not** demand a Forever live-server measurement, internal-server access, build-to-build semantic parity proof, source-version bridge, or standalone semantic-verification round merely to accept an otherwise working implementation. No such extra gate exists.
4. Investigate uncertainty only when there is an **actionable** missing implementation, failing behavior test, contradictory data, or a demonstrated material effect on outcome/comparability. Describe the exact defect and fix it; don't block progress on speculative provenance concerns.
5. Synthetic edge-case inputs (for example 60% spell hit) are legitimate unit-test fixtures but **must be labeled synthetic**, never described as measured Forever mechanics. Distinguish test fixture, Classic-derived default, source data, and real 100-mob simulation.
6. Do not invent source values or silently override actual Forever-specific data. Where Forever-specific evidence contradicts a Classic default, use the better supported rule and rerun affected tests.
7. P2 remains binary: suitable implementation plus meaningful passing behavioral tests = PASS; otherwise FAIL with a concrete defect. No `PARTIAL_SEMANTICS` or `SEMANTICS_UNVERIFIED` acceptance status.
8. This does not waive the actual P1–P6 and P7.1–P7.5 criteria, real 30/300 leveling searches, independent 100-mob measurements, or the five externally pinned P7 checks. It removes **only fabricated proof requirements**.
