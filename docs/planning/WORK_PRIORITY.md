# WORK PRIORITY — live M1 queue

Refreshed against main `0d02162d047b77323e162380116b907beb43d6f9`. Canonical ledger blob: `ab3e8ad0faa686e8782c236b45177e0042fb6eb3`; scoreboard script blob: `93b3f38c4f663e742d154f7ad90a7b05e0c4defc`.

## M1 scoreboard

- **M1 measured: 2.1490% (float=0.0214899642)**; **28.625 / 1,332** measured gate-equivalents; **23 PASS / 10 PARTIAL**; **0/148 certified**.
- Shaman L20 unrestricted P3 is the official **PARTIAL 93/204** from [Merge recorder #41808193281](https://github.com/dosibjrn/forever-sim/actions/runs/41808193281). No Paladin L20 P3 row yet.
- Merge alone runs the trusted recorder and writes `M1_PASSES.tsv`.

## Immediate integration handoff — Paladin L20 unrestricted P3 ([Work2 #845](https://github.com/dosibjrn/forever-sim/issues/845))

- Forever draft [PR #865](https://github.com/dosibjrn/forever-sim/pull/865), current branch HEAD `76d2887601c0918a550f03e3ca38cc2c5c2364cd`, has source-backed native player context and native ItemSparse options. It is **mergeable=true** but remains DRAFT. The branch includes current main through `511d432`; subsequent main changes are Prio queue-only refreshes, not Paladin production changes.
- Exact-head selected-engine/no-record [#41815499955](https://github.com/dosibjrn/forever-sim/actions/runs/41815499955) is SUCCESS and re-ran the real producer: P3 **FAIL / provisional 154/210 (73.33%)**, 40 eligible paid evaluations / 41 attempts, 2,303 native legal candidates, 17 slots, 85 top-five items and zero unverified candidates. Source-paid [#41815499786](https://github.com/dosibjrn/forever-sim/actions/runs/41815499786), maintenance [#41815499817](https://github.com/dosibjrn/forever-sim/actions/runs/41815499817), and native session/clock/world-ACK [#41815499797](https://github.com/dosibjrn/forever-sim/actions/runs/41815499797) are all SUCCESS. The obsolete proxy-diagnostic step is removed; the narrow fail-closed native-binary refusal check remains. This is real measured partial coverage, not a P3 PASS or official M1 row.
- **Next:** Work2 corrects the PR description's stale opening engine-pin text (`9ce8f02...` → actual gitlink `dc53cbda9aa7de44f2fb194ba30095dc46040f52`) and marks the PR ready. Merge then integrates and runs the single official `/m1-run paladin:20:unrestricted:P3`. No further no-record rerun is needed while P3 production code remains unchanged. Conditional partial-inclusive M1 upside is **+0.05505 percentage points**, not earned until Merge records it. No manual ledger edit.

## Work1 — Priest L20 unrestricted P4/P5 ([#817](https://github.com/dosibjrn/forever-sim/issues/817))

- Baseline [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303): both gates BLOCKED, zero complete paid screens and zero source-action casts.
- MythicSim draft [PR #10](https://github.com/dosibjrn/mythicsim-forever-engine/pull/10), HEAD `a55a0202`, adds the requested-level field and sourced Priest L20 race stats / class base HP and mana, but still refuses actor preparation because the real level-dependent conversions and class preparation are incomplete. Native smoke [#41812788713](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41812788713) SUCCESS; broad Engine checks [#41812788699](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41812788699) fail on repository-wide unrelated rustfmt diffs and `native_persistent_early_world_kill_clock_boundary` (378 passed / 1 failed).
- **Next:** implement the actual native L20 conversions/class preparation, then connect that actor to the existing paid whole-build + 2D/source-action screen. One changed-HEAD no-record light P4/P5 run must show actor level 20, complete paid screens and positive source-action casts. No proxy or GameIR/SQLite fallback.

## Work2 after Paladin — Shaman L20 unrestricted P3 Intellect witness ([#871](https://github.com/dosibjrn/forever-sim/issues/871))

- Baseline [#41808193281](https://github.com/dosibjrn/forever-sim/actions/runs/41808193281): **93/204 PARTIAL**; Intellect weight is `0.0` with `NONPOSITIVE_RELEVANT_WEIGHT:intellect`; only the positive Spell Power witness was attempted.
- The existing generic paid witness ranks Intellect next for the non-weapon policy and already uses source-authored policies, native item-sized deltas and real CombatRuntime before/after evaluation.
- **Action:** Work2 starts #871 only after #845/PR #865 is integrated because both touch `tools/wf_gate_p3_live.py`. Add only the Intellect witness after the native Spell Power path; keep the 44-evaluation cap. One changed-HEAD no-record run must show a positive Intellect derivative and more than 93/204 comparable assertions before Merge is asked for one official recorder. No numerical gain is presumed.

## Alternatives and guardrails

- Hunter L20 P3 [#827](https://github.com/dosibjrn/forever-sim/issues/827) is complete: two trusted attempts returned BLOCKED with zero source evaluations. Do not rerun unchanged or invent a Hunter policy.
- Mage L30 P3 [#818](https://github.com/dosibjrn/forever-sim/issues/818) is **129/224 PARTIAL**; remaining axes have no demonstrated single cheap repair. Druid L60 Balance P7.4 is PASS; Druid L30/L40 P6 are 200/200 partials.
- Active gates only: P3–P6 and P7.1–P7.5. P1/P2 are retired. No HPS/TPS witnesses, MythicSim self-validation, duplicate unchanged runs, invented weights or fabricated M1 rows.
