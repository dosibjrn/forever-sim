# WORK PRIORITY — live M1 queue

Refreshed against current main `276a470a9f9638bed483cc25dbea6e557bd91a65` (Clean #842 is M1-affected-gates: none). Canonical ledger blob: `311bfb194ebd720d1105561d6e032a15359b3273`.

## Current M1 scoreboard

- **M1 measured: 2.1000%** (`measured_fraction=0.0210002413`).
- **27.972 / 1,332** measured gate-equivalents.
- **23 PASS / 17 PARTIAL** active-scope gate rows.
- **0 / 148** certified checkpoints. Druid L60 Balance now has nine PASS gate rows, but the rows do not share a certified compatibility identity; do not claim a completed checkpoint.

The scoreboard is the output of the canonical `python tools/m1_progress.py` run in Merge recorder #41784946720. Prio does not edit `M1_PASSES.tsv`.

## Immediate queue

### 1. Merge — finish the post-#840 Druid L60 Balance P7.4 revalidation

- PR #833's finite-target lethal-aware comparator was merged as `cd743de`; official heavy recorder [#41784946720](https://github.com/dosibjrn/forever-sim/actions/runs/41784946720) returned a genuine **P7.4 PASS**: 300.000146734 s independent cold search, 992 paid source-legal candidates, frozen 1,000-fight stochastic final, native/world mean 961.5548432073 DPS against the 720.9117 floor.
- Production hardening PR [#840](https://github.com/dosibjrn/forever-sim/pull/840) then changed the executable P7.4 live path in `integrations/mythicsim-rust/live_world_probe.py`: identical iteration-limited native/live requests and a fresh saved-HP target for every fight. Its exact 25-fight diagnostic [#41785767359](https://github.com/dosibjrn/forever-sim/actions/runs/41785767359) passed with the original 127,393 HP target and lethal-aware coupled native↔2D parity.
- The mandatory changed-code heavy revalidation was already dispatched twice by Merge on the same merged main SHA `e53f0ca`: [#41786536534](https://github.com/dosibjrn/forever-sim/actions/runs/41786536534) and duplicate [#41786566461](https://github.com/dosibjrn/forever-sim/actions/runs/41786566461). Both were still in progress at this refresh.
- **Do not dispatch again.** Merge must inspect both terminal runs, reconcile the recorder's blob-SHA/CAS outcome, and post one terminal verdict. Current main's later Clean #842 commit changes no M1-affected gate.

### 2. Merge — next independent low-cost measurement: Paladin L20 unrestricted P3

- The canonical ledger has **no** `paladin:20:unrestricted:P3` row; this is unmeasured, not a known PASS or FAIL.
- Current main registers the existing Paladin native source provider for L10–L30 and has existing `paladin_ret` / `paladin_tank` gear roles and runtime selection. The real P3 production path uses the existing bounded paid scorer and a 44-evaluation budget; this is not a 100-mob or 300-second acceptance.
- A full PASS would add at most `1/1332 = 0.07508` percentage points; an eligible PARTIAL contributes only its actual measured fraction. This is a conditional opportunity, not a predicted result.
- **Do not dispatch while either #41786536534 or #41786566461 is active.** Once both are terminal and the ledger is reconciled, Prio may post one `M1-DISPATCH-REQUEST` for `paladin:20:unrestricted:P3` on this existing owner issue [#131](https://github.com/dosibjrn/forever-sim/issues/131). Use one production run only; if the source scenario or legal item path is BLOCKED, retain the exact reason and do not retry unchanged. No separate queue issue.

### 3. Work2 — Mage L30 P3 source-witness repair

- Owner issue [#818](https://github.com/dosibjrn/forever-sim/issues/818); current PR [#831](https://github.com/dosibjrn/forever-sim/pull/831), API head `e74e951`, base `547c18a` (behind current main `276a470`). The PR body is stale: it still describes `4c88590` as HEAD.
- Last validated production behavior on `6f3ce498`: selected-engine/no-record [#41785534565](https://github.com/dosibjrn/forever-sim/actions/runs/41785534565) remains **FAIL 85/224**, equal to the accepted #825 high-water. The +50 Intellect witness is preserved; native +74/+101 Spell Power probes remain nonpositive on both source-IR and paid-winner policies. No M1 increment.
- The later test-only head `4c88590` also returned 85/224; maintenance [#41786092998](https://github.com/dosibjrn/forever-sim/actions/runs/41786092998) exposed two invalid fixtures whose mock IR omitted `mage:fireball`. Current PR head `e74e951` changes those fixtures but has no exact-head validation yet.
- Next Work2 action: rebase onto fresh main, update the PR body to the real HEAD, get exact-head maintenance green, then inspect a genuinely native/source-authorized executable alternative for Spell Power. **No synthetic weights, no gate weakening, no merge or M1 dispatch at 85/224.**

### 4. Work1 — Priest L20 P4/P5 remains parked

- Existing owner issue [#817](https://github.com/dosibjrn/forever-sim/issues/817) tracks the missing native level-aware player/base-stat contract for the real P4/P5 path.
- Keep parked until the Mage L30 P3 investigation and the post-#840 P7.4 revalidation are reconciled. This is an implementation-sized dependency, not a reason to build a parallel simulator or add diagnostic-only work.

## Closed / no unchanged redispatch

- Hunter L20 P3: `BLOCKED_NO_NAKED_SUCCESS`, zero paid source evaluations. Do not rerun unchanged.
- Mage L20 P3: retain the existing 88/224 high-water; do not rerun unchanged.
- Mage L30 P3: retain the official 85/224 high-water from #825; #831/#837/#838 experiments have not exceeded it.
- Druid L60 Balance P7.4: pre-#840 official PASS is historical; the two post-#840 heavy runs above are the only current-code revalidation attempts.

## Operating constraints

- Merge alone dispatches official M1 recorders and writes `M1_PASSES.tsv`; Prio only maintains this queue and submits requests on existing owner issues.
- Never launch a second M1 writer while a recorder is active. Never duplicate a request already ACKed/launched.
- Prioritize real active P3–P7.5 production progress. No P1/P2 work, no retired GameIR search runner, no HPS/TPS witness work, no MythicSim self-validation, no invented positive weights, and no fabricated M1 rows.
