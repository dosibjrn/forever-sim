# WORK PRIORITY — live M1 queue

Refreshed against main `9a4900b32588223c0eb668e1b2167874ebccbb0e`. Canonical ledger blob: `ab3e8ad0faa686e8782c236b45177e0042fb6eb3`; scoreboard script blob: `93b3f38c4f663e742d154f7ad90a7b05e0c4defc`.

## M1 scoreboard

- **M1 measured: 2.1490% (float=0.0214899642)**; **28.625 / 1,332** measured gate-equivalents; **23 PASS / 10 PARTIAL**; **0/148 certified**.
- Shaman L20 unrestricted P3 is the official **PARTIAL 93/204** from [Merge recorder #41808193281](https://github.com/dosibjrn/forever-sim/actions/runs/41808193281). No Paladin L20 P3 row yet.
- Merge alone runs the trusted recorder and writes `M1_PASSES.tsv`.

## Work1 — Priest L20 unrestricted P4/P5 ([#817](https://github.com/dosibjrn/forever-sim/issues/817))

- Baseline [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303): both gates BLOCKED, zero complete paid screens and zero source-action casts.
- MythicSim draft [PR #10](https://github.com/dosibjrn/mythicsim-forever-engine/pull/10), HEAD `a55a0202`, now loads sourced Priest L20 race stats and class base HP/mana, but still refuses actor preparation because level-dependent conversions/class preparation are missing. Native smoke [#41812788713](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41812788713) SUCCESS; broad Engine checks [#41812788699](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41812788699) fail on repository-wide unrelated rustfmt diffs and `native_persistent_early_world_kill_clock_boundary` (378 passed / 1 failed).
- **Next:** implement the actual native L20 conversions/class preparation, then connect that actor to the existing paid whole-build + 2D/source-action screen. One changed-HEAD no-record light P4/P5 run must show actor level 20, complete paid screens and positive source-action casts. No proxy or GameIR/SQLite fallback.

## Work2 — Paladin L20 unrestricted P3 ([#845](https://github.com/dosibjrn/forever-sim/issues/845))

- Forever draft [PR #865](https://github.com/dosibjrn/forever-sim/pull/865), HEAD `90f9ef4f`, has a real native player context and native ItemSparse options. Exact-head selected-engine/no-record [#41813962321](https://github.com/dosibjrn/forever-sim/actions/runs/41813962321) SUCCESS; actual P3 **FAIL / provisional 154/210** (73.33%), 40 eligible paid evaluations / 41 attempts, 2,303 legal candidates, 17 slots and 85 top-five items. If Merge records the same scope, conditional M1 gain is **+0.05505 pp**; it is not yet in the ledger.
- Source-paid [#41813962402](https://github.com/dosibjrn/forever-sim/actions/runs/41813962402) SUCCESS. Maintenance [#41813962392](https://github.com/dosibjrn/forever-sim/actions/runs/41813962392) fails after 529 tests pass: an obsolete proxy-diagnostic step runs with native binaries unset, correctly receives `BLOCKED / P3_NATIVE_ITEM_OPTIONS_BINARY_REQUIRED`, then reads the absent `real_source_search_evaluated` field. Remove/replace that stale step; preserve fail-closed behavior (the dedicated refusal step already tests it).
- MythicSim draft [PR #12](https://github.com/dosibjrn/mythicsim-forever-engine/pull/12), SHA `dc53cbda`, has source-backed Paladin context/options; combined native P3/P7.4 smoke [#41813123596](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41813123596) SUCCESS. Broad Engine checks [#41813123502](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41813123502) fail on unchanged world-bridge/fight Clippy findings and the world-clock test.
- **Next:** remove the stale maintenance step, sync PR #865 to latest main, rerun maintenance, then merge. Merge alone performs the single official Paladin P3 recorder; no unchanged no-record rerun or manual ledger edit.

## Next Work2 after Paladin — Shaman L20 unrestricted P3 Intellect witness ([#871](https://github.com/dosibjrn/forever-sim/issues/871))

- Baseline [#41808193281](https://github.com/dosibjrn/forever-sim/actions/runs/41808193281): **93/204 PARTIAL**; Intellect weight is `0.0` with `NONPOSITIVE_RELEVANT_WEIGHT:intellect`; only the positive Spell Power witness was attempted.
- The existing generic paid witness ranks Intellect next for the non-weapon policy and already uses source-authored policies, native item-sized deltas and real CombatRuntime before/after evaluation.
- **Action:** Work2 starts #871 only after #845/PR #865 is integrated because both touch `tools/wf_gate_p3_live.py`. Add only the Intellect witness after the native Spell Power path; keep the 44-evaluation cap. One changed-HEAD no-record run must show a positive Intellect derivative and more than 93/204 comparable assertions before Merge is asked for one official recorder. No numerical gain is presumed.

## Alternatives and guardrails

- Hunter L20 P3 [#827](https://github.com/dosibjrn/forever-sim/issues/827) is complete: two trusted attempts returned BLOCKED with zero source evaluations. Do not rerun unchanged or invent a Hunter policy.
- Mage L30 P3 [#818](https://github.com/dosibjrn/forever-sim/issues/818) is already 129/224 PARTIAL; remaining axes have no demonstrated single cheap repair. Priest #817 and Paladin #845 retain their current owners. Druid L60 Balance P7.4 is PASS; Druid L30/L40 P6 are 200/200 partials.
- Active gates only: P3–P6 and P7.1–P7.5. P1/P2 are retired. No HPS/TPS witnesses, MythicSim self-validation, duplicate unchanged runs, invented weights or fabricated M1 rows.
