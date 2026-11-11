# Work2 — independent #2+ implementation

## Owner M0.4/M0.5 deliverable — one generic `optimize` and real paid results (2026-11-11)

Your immediate product is the **exact successful native execution** of `python -m src.v2.runner optimize --class warlock --tree unconstrained --start-level 20 --end-level 60 --level-stride 20 --n-mobs 2 --recover-at-end true --rng balanced --backend rust` on current main plus compatible pinned Rust; not a green mock, independent level winners, new Warlock-named script, or input fixtures pretending to be winners. `src/v2/native_range_optimizer.py` and `src/v2/runner.py` already exist on main; build on those. Rust API PR #50 is an incomplete starting point. Consume Work1's native M0.3 API for options, whole-build prepare, actual gsim↔Rust world execution and true 100% HP/mana restoration; avoid temp source/prepared JSON transport and false SHA checks.

Native candidate generation: seek genuine gear, talent families/hybrids, APL, pet and pull/recovery competition from native options; **exclude rating-stat item proposals at the Rust item source**, never Python veto. Cross-seed later-level good talent allocations into earlier-level ancestors, retain slower early candidates for cumulative path decisions, and preserve source-native legal sample compatibility without inventing skipped-level simulation, continuity certificates or free respec. L20, L40 and L60 are the *only requested sampled levels* for stride=20. Treat L40 prep and L20 item errors as specific candidate/engine defects; continue independent exploration and report exact refusals. Remove old source-JSON vs protobuf SHA mismatch from active adapters.

**M0.4 done criterion:** one CLI invocation exits successfully AND returns an inspectable real measured ranked compatible path at L20/L40/L60, containing exact talents, gear item IDs, pet, APL, actual two hostile mob and terminal both-resources-full elapsed scores, alternative candidates and real receipts. Never make empty-path exit 0 green. Then **M0.5 is the same optimizer at level strides 10 → 5 → 1**, start L20/end L60 is valid; reuse paid candidate/scenario cache and forward/backward promising paths. Do not demand L10–19, 100 mobs, continuous XP/travel or a separate route algorithm for M0.5. Link each real action and its output artifact in your existing owned PR; update the route result only from actual paid native observations.


Read [COMMON](COMMON.md), [WORK_COMMON](WORK_COMMON.md), this file and current [WORK_PRIORITY](../WORK_PRIORITY.md). Read only the relevant OVERALL_PLAN / PROCESS / gate sections for the assigned item.

Read Work2's current issue/branch/PR from the top of WORK_PRIORITY; assignments can change and must not be hard-coded into task prompts.

## Purpose — deliver a reusable user-facing route capability

**Purpose: deliver the owner-selected runnable route and its generic autonomous optimizer.** For the current Warlock priority, own Forever/gsim source-native level-range orchestration, paid route optimization, preserved actor/resource/talent state, optional L40 dual-spec, comparable single-spec baseline and honest guide output. Start M0.6's resumable one-request coordinator during M0.5, not after serial manually launched per-level runs. Automatically reuse compatible paid receipts; execute missing/changed native scenes rather than duplicates. Work independently of Work1's Rust/source capability lane. Continue one capability-oriented implementation PR across cycles and prioritize actual measured user-facing behavior over an M1 float, new PR count or green CI alone; only Merge records new unaccepted M1 gates.

**Good work. Work work, choo choo.**

## Owner-only role-file changes

**Do not edit this WORK2.md or any agent's description, router or shared agent contract without a separate, explicit user request for that instruction change.** Work2 cannot self-rewrite responsibilities when assignments, gate outcomes or PRs change. Take live tasks from `WORK_PRIORITY.md` and maintain only owned issues/implementation PRs during normal cycles; report stale role wording instead of changing it yourself.

## Ownership

Work2 owns the **highest independently executable #2+ product/optimizer item**. Continue its own assigned production path (currently determined by WORK_PRIORITY, not this file). If blocked solely by Work1's #1 dependency, take the next genuinely independent Prio item. Never take or edit Work1's branch.

For optimizer/source-related work, MythicSim Rust—not Forever Python—owns build/source-legality decisions **and supplies the available candidate alternatives** (items/enchants, talents, executable APL actions/conditions) for each class/level/spec/scenario. The generic Forever search owns sampling, mutations, recombination and scoring of those native-supplied choices, not a second Python/SQLite Warcraft catalogue. Do not add a new source-backed legality validator or candidate-eligibility table to the optimizer or recreate mechanics already owned by native Rust. Where an actual production caller needs an unavailable options API, implement that bounded capability in the maintained Rust fork and promote its tested exact pin before deleting the old live caller; do not build migration scaffolding for retired P1/P2 demos.

## Owner-selected Warlock handoff: one parameterized multi-level optimizer

**Retire the stale instruction to pay L45–L46; they have already been measured.** Also stop serial first-preparable L10–L19 100-mob expansion as the claimed optimizer. Use Work1's scored native candidate API inside an **existing generic Decisions/path-frontier engine** with parameters `start_level`, `end_level`, `level_stride`, `mob_count`, search budget and `recover_to_full=true`. The first runnable high-level **one-call search** must visit **L20, L30, L40, L50, L60 with 3 hostile mobs/candidate, balanced RNG and one iteration**, then pay native Life Tap/eating/drinking/passive regen to **100% HP and 100% mana at each sample end**, including its elapsed time in objective. The exact same entrypoint must handle dense `L10..60, stride=1, mob_count=100` by adjusting parameters, not branching to a special workflow.

Keep multiple legal continuing talent/path frontiers and select via cumulative estimated/observed elapsed leveling time, accounting for sourced respec/dual-spec/training/travel/acquisition and missing data explicitly. Sparse checkpoint results guide but do **not** prove a continuous path between checkpoint levels; infill and verify decisions as compute allows. Add focused tests covering **one invocation yields five sampled-level decisions**, changing stride or mob_count only changes arguments, late faster candidates win over first-prepared, and full-resource terminal time changes the result. Preserve original paid L20–L60/L47 receipts as baselines and don't repeat them. Publish decisions, alternatives, assumptions, scoped stat weights, recovery clock, provenance, budget and next useful experiment.

## Required cycle result

Deliver a committed/pushed, focused production delta on the assigned #2+ slice, with relevant Forever-owned regression/validation and an updated PR handoff. Do not finish with status, review or CI alone. Apply the complete start-of-cycle review, Actions inspection, PR response and no-report-only rules in WORK_COMMON.

At cycle end, consider and, when justified, launch an asynchronous paid-optimizer/100-mob regression or other relevant diagnostic on the owned code. Link its exact run/ref and hand off the next check in the existing issue/PR. Do not repeat an unchanged expensive run.
