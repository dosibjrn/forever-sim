# WORK PRIORITY — forever-sim (public main)

**Canonical repository:** [dosibjrn/forever-sim](https://github.com/dosibjrn/forever-sim). Updated 2026-11-01. The former private `dosibjrn/mage-level-sim` is a **read-only historical source**, not a work target. The old Mage Sim recurring agents have been paused; **do not automatically restart or redirect them** without a separate instruction.

**Approved project contracts:** [OVERALL PLAN v5](../../OVERALL_PLAN.md) and [PROCESS v2.10](../../PROCESS.md). This page is a mutable routing index; actual work items and acceptance criteria belong in GitHub issues. **Fully certified checkpoints: 0/148.** Historical P1–P6-only or independent native/P7 results are not full accepted P1–P7.5 checkpoints.

## 2026-11-01 source migration COMPLETE — public baseline independently verified

- **Canonical main:** [`dosibjrn/forever-sim`](https://github.com/dosibjrn/forever-sim). Old private [`mage-level-sim`](https://github.com/dosibjrn/mage-level-sim) is **read-only legacy**. The exact private source snapshot was `3bd46df7e3b95a8a3bfdc7455de659341a905826`; the [approved source publication commit](https://github.com/dosibjrn/forever-sim/commit/c04d0892060165663a937b0ece6c92cdb6591b7a) was `c04d089`. Subsequent main commits cleaned up one-shot workflow triggers.
- **Exact hydrated source bytes:** The successful [audit/publish run #41255111332](https://github.com/dosibjrn/forever-sim/actions/runs/41255111332) scanned all 1,914 tracked private paths, selected 1,877 and intentionally protected 37. It recorded **0 suspect paths, 0 unresolved LFS/SQLite assets, 0 missing files, 0 byte-copy mismatches and 0 unstaged source paths**. Previously missing **10 SQLite databases and two oversized JSON evidence artifacts** are now in public main.
- **Independent fresh public clone and tests:** [runner run #41255246045](https://github.com/dosibjrn/forever-sim/actions/runs/41255246045) **PASS**: checkout with LFS hydrated **11 SQLite + 3 large JSON payloads** (including existing LFS items); `tests/test_verify_public_snapshot.py` **13/13 PASS**, real hosted runner and shell verified.
- **Parity scope:** All 1,877 non-protected private source paths are present in public main. 14 paths have deliberately different *Git blob IDs* because public `.gitattributes` stores hydrated bytes as LFS pointers; fresh-checkout hydration confirms the published payloads are usable. 35 historical automatically triggered private workflows remain excluded on purpose to prevent massive redundant CI; public-specific README, WORK_PRIORITY and migration tooling are retained.
- **Safety/cleanup:** Publish was pinned to the exact audited private SHA and finished successfully; temporary publication and test `push` triggers were removed. Public workflows are again **manual-only**. No writes to the historical private source.
- **Separate follow-up, not missing source migration:** the draft public PRs [#20–#24](https://github.com/dosibjrn/forever-sim/pulls) need post-baseline exact-head CI / conflict checks and source-delta review, with #29 stacked on #23; evaluate the historical branch inventory only for unique relevant work. Do not blindly import historical CI or 59 private branches. These are now integration/engineering validation, not binary migration. Checkpoint certifications remain **0/148**.

## After P0 — shortest critical path toward 148/148

Optimize for **shortest overall time to 148/148**, not fastest individual PR, isolated native DPS, or one-off bespoke Druid implementation. Build one reusable production path: source-legal gear × talents × APL/policy → persistent gsim world → actual timed native effects → applied-world ACK → paid recovery → independent P1–P7.5 certification. The first complete Druid L60 Balance checkpoint is a *template* reusable for the remaining 147, not the end goal.

**Parallel lanes, each with explicit owners and nonoverlapping branches:**

1. **A — real native↔world causality:** [issue #7](https://github.com/dosibjrn/forever-sim/issues/7), [draft PR #20](https://github.com/dosibjrn/forever-sim/pull/20). Execute a source-pinned native spell event, change real gsim HP, verify world hashes + full-event ACK and the *following* native decision. Prove near/far or other causal negative control. Do not count range receipts or counters as event→world ACK.
2. **B — paid continuous 100-mob evaluator:** [issue #19](https://github.com/dosibjrn/forever-sim/issues/19), [draft PR #23](https://github.com/dosibjrn/forever-sim/pull/23). Run an actual source-backed 1→2→100 sequence with distinct targets, real source actions, persistent player clock and paid combat/recovery/travel/upkeep. Integrate A's native session, then execute genuine whole-build P4–P6 30/300-second searches.
3. **C — source legality and gate truth:** [issue #11 / P1](https://github.com/dosibjrn/forever-sim/issues/11) via [PR #21](https://github.com/dosibjrn/forever-sim/pull/21), and [issue #12 / P2](https://github.com/dosibjrn/forever-sim/issues/12) via [PR #24](https://github.com/dosibjrn/forever-sim/pull/24). Verify learned-spell/rank acquisition, full-rank talent behavior, provenance and real source fixtures; a product-specific 31-point Balance profile is not a game rule.
4. **D — generic optimizer and acceptance:** [issue #15](https://github.com/dosibjrn/forever-sim/issues/15), [issue #16](https://github.com/dosibjrn/forever-sim/issues/16), [issue #13](https://github.com/dosibjrn/forever-sim/issues/13). Connect one reusable class-neutral gear × talents × APL joint search and one provenance/certificate adapter to A+B; no alternate synthetic scorer or new Druid-only executor.
5. **Independent coverage/second class:** [PR #22](https://github.com/dosibjrn/forever-sim/pull/22) under [#19](https://github.com/dosibjrn/forever-sim/issues/19): real retained Hunter pet resources, clock, cooldowns, auras, action execution and no-pet parity. [Issue #6](https://github.com/dosibjrn/forever-sim/issues/6) and the ported Rust native L60 28-spec branch remain *diagnostic*, not P7 certification and not a blocker for the first full checkpoint.

**Parallel merge-verification enabler — [issue #39](https://github.com/dosibjrn/forever-sim/issues/39) (Merge owner; Clean may implement a delegated isolated workflow PR):** the public hosted-runner/LFS smoke is green, but no successful public exact-HEAD PR test run is recorded for #20/#23/#29/#37. Establish one bounded, read-only, **manual-only** default-branch exact-PR-SHA test lane with negative controls and no automatic/heavy triggers. This removes a shared review bottleneck; it does **not** displace 1st work's #7 or 2nd work's #19, and a test PASS is not a gate PASS. Execute one controlled positive run before selective PR checks.

**Reprioritize** after the first truly executed native→gsim→ACK trace and the first truly executed 100-mob paid trace. Require independent source-legal verification, exact current HEAD, full stochastic holdout per approved PROCESS, and evidence for every stage before changing **0/148**.

## Current public draft PR merge queue

| Rank after P0 | New PR | Source PR | Exact public head at migration check | Required next verification |
| --- | --- | --- | --- | --- |
| 1 | [#20 native ACK](https://github.com/dosibjrn/forever-sim/pull/20) | private #58 | `796fc562` | Compile pinned Go and run real event→HP/hash→ACK→subsequent decision; run focused Python/Go tests. Earlier review identified a potential empty test function: verify *current* source, don't assume it is fixed. |
| 2 | [#23 paid replay](https://github.com/dosibjrn/forever-sim/pull/23) | private #68 | `9d995093` | Real source-backed 1/2/100 mobs with captured raw trace; no synthetic/missing paid time. |
| 3 | [#21 P1 acquisition](https://github.com/dosibjrn/forever-sim/pull/21) | private #62 | `584bc7b1` | Actual acquired spell and source-snapshot provenance, legal L20/L30 ranks and fast regressions. |
| 4 | [#24 P2 profile](https://github.com/dosibjrn/forever-sim/pull/24) | private #69 | `74f9854c` | Exact-source P2 live gate, talent legality and behavior (and unrestricted-control regression). |
| 5 | [#22 companion persistence](https://github.com/dosibjrn/forever-sim/pull/22) | private #67 | `3133f5d0` | Actual Hunter 1/2/100 paid pet pulls, cooldown/focus/link continuity and Druid no-pet control. |

All five remain **DRAFT**. Merge an independently verified, bounded, regression-safe increment if it genuinely advances the overall goal; **do not** require an entire checkpoint for a useful individual PR. But never call a checkpoint PASS before all its required PROCESS gates. Never treat a green isolated unit test as end-to-end integration proof.

## Reference and ownership rules

- Approved [OVERALL PLAN](../../OVERALL_PLAN.md) / [PROCESS](../../PROCESS.md) are authoritative and untouched. This `WORK_PRIORITY.md` is the **only mutable priority index**. Use small specific GitHub issues for implementation work.
- Public issues and PRs are canonical for new work; old `dosibjrn/mage-level-sim` links in historical artifacts refer to **legacy** evidence. The same numeric identifier can refer to a different issue in the new repository.
- Agent implementation work uses separate fresh `work/*` branches, real source/negative controls, reviewable commits and exact-head tests. Integration owns queue, review and merge. Do not modify someone else's active branch.
- GitHub Actions runner failure *before any step* is infrastructure-only; it is neither source PASS nor source FAIL. CI workflows that can trigger a large run storm remain disabled during P0.
