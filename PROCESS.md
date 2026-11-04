# WoW Forever — PROCESS v2.22 (owner-approved 2026-11-04)

[OVERALL_PLAN.md](OVERALL_PLAN.md) defines WHAT is delivered. This file governs HOW; **the only normative gate predicates** live in [docs/gates/](docs/gates/README.md). Superseded thresholds and approvals are in Git history, not active competing instructions.

## Authority and scope

- Exactly **148 checkpoints × nine active gates P3–P6, P7.1–P7.5 = 1,332 gate pairs**. P1/P2 are retired; no new P1/P2 records or replacement GameIR validation.
- **Exactly nine genuine active gate PASSes certify a checkpoint.** Each gate evaluates its own source, runtime and scenario. No cross-gate `compatibility_id`, identity certificate or tenth acceptance condition. Unrelated SHAs do not invalidate existing PASSes; contract updates do not invent unexecuted PASSes.
- Owner approval is required to change OVERALL_PLAN, PROCESS, agent role instructions or gate predicates. `WORK_PRIORITY.md` and issues control mutable dispatch only. No extra implicit gate or auxiliary proof is permitted.
- **M1 remains the existing partial-inclusive diagnostic**: `(active PASS + Σ comparable verified/applicable PARTIAL) / 1332`. Only Merge's real production recorder writes `docs/planning/M1_PASSES.tsv`. PARTIAL never certifies a gate; unknown/incomparable denominator earns no invented fraction. Certified PASS count and 148-checkpoint count remain separate.

## Engine and optimization

- Exact-SHA-pinned **MythicSim Rust** owns Warcraft facts, legal item/enchant/talent/APL choices and mechanics; approved Go execution remains possible. Forever owns scenario, generic gear × talents × policy proposals, paid candidate evaluation and selection. Consume real native VALID/INVALID/UNSUPPORTED; do not clone Warcraft rules in Python, revalidate MythicSim or revive GameIR.
- **P3:** finite source-legal gear scores and real score sensitivity to mechanically relevant changes, using a bounded representative legal item set. Mechanically irrelevant weights may be zero. No invented positive epsilon, source catalogue audit or global gear optimality claim.
- **P4/P5:** one real fresh **300s cold whole-build search**, capturing an immutable genuine **30s** best-so-far snapshot. Continue real paid proposals/evaluations beyond 30s; each chosen distinct winner needs its own real **100 consecutive-mob** retained-actor spatial world/native run including combat, movement, recovery, resources and survival. No independent second cold restart, blanket execution of every unlocked action or `N300 >= 2×N30` throughput gate. When unlocks are legal, native-sourced generation can propose them and at least one reachable unlocked action is executed/compared where available.
- **P6:** require comparable `T30 <= 1.01 × T300` seconds/mob. Reuse compatible, identical genuine finalist 100-mob receipts; run only a missing/changed/incomparable winner. No one-mob, fake or post-hoc substitutes.
- **P7:** fixed source-legal **stationary non-attacking DPS** encounter; direct genuine pinned Rust/Go native evaluation is sufficient (no P7-only 2D world handshake). P7.1 measures one reproducible pinned **1,000-stochastic** reference with a 99% reference floor and may reuse an identical authentic native-generated receipt. P7.2/.3/.4 independently change the rotation/talent/gear axis, freeze other axes, and genuinely score at least one native-legal changed candidate when available; no separate 300s/1,000-stochastic/99% axis qualification. P7.5 alone runs an independent **300s cold joint gear × talents × policy search**, freezes its winner and holds out **1,000 stochastic native fights**, requiring mean DPS `>= 0.93 × max(reference, any accepted-compatible stochastic prior mean)`. Only actual stochastic prior means qualify as comparators; absent optional axis holdouts do not block P7.5.
- Detailed source, encounter, acceptance, identity, candidate and replay rules are solely in the linked [P3](docs/gates/P3.md), [P4–P6](docs/gates/P4-P6.md), [P7](docs/gates/P7.md) and [common](docs/gates/COMMON.md) contracts.

## Delivery and evidence

1. Prioritize the largest credible **total** M1 gain per remaining work, including reuse across genuinely active gates, not merely the next cheap one-off partial. [Prio](docs/planning/agents/PRIO.md) owns that decision; task detail/history live in existing issues/PRs, not `WORK_PRIORITY.md`.
2. Make the smallest source/production change with a causal route to a real gate improvement; validate changed behavior with focused tests and a meaningful production no-record run. Stop repeating unchanged non-improving proof probes and request reprioritization after a real no-gain result unless a new concrete cause is found.
3. One real on-demand production execution suffices for a compatible PASS. The real native receipts, config/engine identity and required timing/measurements must remain inspectable in ordinary run history; no second ledger, per-gate MD/JSON proof bundle, MythicSim audit or parallel acceptance implementation.
4. Merge integrates safe code even before a full PASS, dispatches genuine eligible affected-gate measurements only as justified, and preserves already accepted compatible PASSes. Heavy 300s/1,000-fight measurements do not run hourly or on unrelated changes.

