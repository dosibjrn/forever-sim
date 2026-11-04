# FOREVER SIM — active M1 work queue

**Policy:** choose the active checkpoint-gate with the greatest credible **incremental genuine M1 measured-float gain per total work/time**. A previously accepted PASS has no remaining gain. A new real PASS adds one gate-equivalent (1/1332 = 0.075075 percentage points); a genuine measured PARTIAL adds only its recorded fraction, or the rise above its prior high-water mark. **NOT YET MEASURED is not FAIL.** Only Merge runs the official recorder/writes `M1_PASSES.tsv`. No P1/P2, GameIR replacement or unrelated HPS/TPS witness work in this queue.

**Latest main ledger at this decision:** M1 measured: **1.0855% (float=0.0108551409)**; 12/1332 active PASS gates. Measured M1 is partial-inclusive diagnostic, **not** certified checkpoint acceptance. See [ledger](M1_PASSES.tsv) / [scorer](../../tools/m1_progress.py).

## #1 — Merge: cheapest credible next unmeasured active gate — [issue #738](https://github.com/dosibjrn/forever-sim/issues/738)

- **Selected gate:** `druid:60:unrestricted:P4`, **NOT YET MEASURED** (no official row). Adjacent `druid:60:balance:P4` has [real PASS](https://github.com/dosibjrn/forever-sim/actions/runs/41505778030); same-level unrestricted P3 has just [passed 230/230](https://github.com/dosibjrn/forever-sim/actions/runs/41741730565). The existing class/level search and source inputs make a one-off P4 worth attempting without preparatory code.
- **Action / exact dispatch:** **Merge** must post exactly `/m1-run --heavy druid:60:unrestricted:P4` on an already-merged PR (or use `workflow_dispatch` with `allow_heavy=true`). This flag is mandatory: without `--heavy`, `.github/workflows/m1-on-demand-record.yml` leaves `FOREVER_P4_P5_FULL_SOURCE` unset and `tools.wf_gate_p4_live.run_live` takes its default **6s partial-only** path. With `--heavy`, the recorder sets `FOREVER_P4_P5_FULL_SOURCE=1`, uses a 900s timeout and invokes the existing full 30s cold whole-build search plus complete 100-mob finalist. Do not mistake the 6s diagnostic PARTIAL for the requested P4 acceptance.
  Record the actual PASS / eligible execution-derived PARTIAL / FAIL / BLOCKED only. No change to predicates, extra proof, new wrapper, hand-made numerator or prior code fix. Link the real output and canonical TSV receipt. A clean new PASS can add **+0.075075 M1 percentage points**; an eligible measured PARTIAL only its actual fraction/1332; no earned gain until recorded.
- **Cost/selection rationale:** one 30s search plus final 100-mob run, versus the 300s + 1,000-fight stochastic P7.4 repair/acceptance. The latter may advance the nearest 8/9 checkpoint but is currently a genuine observed FAIL and needs production improvement. If P4 fails, give Work1 the **first observed** P4 code defect only after preserving its P7.4 ownership. Do not invent a failure from absence of a row.

## #2 — Work1: highest-value distinct real FAIL, nearest 8/9 checkpoint — Druid L60 Balance P7.4 ([issue #131](https://github.com/dosibjrn/forever-sim/issues/131))

- **Proven:** [real run #41721736018](https://github.com/dosibjrn/forever-sim/actions/runs/41721736018) completed a 300.000119s search; frozen 1,000-Stochastic mean **692.819689 DPS**, short of required **720.9117 DPS**, yielding `P7_4_FROZEN_STOCHASTIC_DPS_BELOW_REFERENCE_FLOOR`. There is no accepted P7.4 ledger row.
- **Next implementation:** Work1 fixes a concrete production winner-selection/search generalization weakness that raises the paid frozen Stochastic result; test changed Forever-owned behavior, hand off through PR, then ask Merge for **one** fresh exact-gate heavy run. Do not rerun unchanged 300s search or validate MythicSim mechanics as a substitute.
- **Updated dependency:** Work1 [PR #729](https://github.com/dosibjrn/forever-sim/pull/729) **merged**, and Druid L60 Balance **P7.5 is now a true PASS** from [official run #41741229700](https://github.com/dosibjrn/forever-sim/actions/runs/41741229700); do not keep scheduling P7.5 or claim its old PARTIAL remains active. P7.4 success could add a full 1/1332 gate-equivalent and potentially complete the first checkpoint if compatibility is established.

## #3 — Work2: independent real P3 blocker — Mage/Priest L20 unrestricted P3 ([issue #737](https://github.com/dosibjrn/forever-sim/issues/737))

- **Proven baseline:** [Mage L20 real provider #41732764084](https://github.com/dosibjrn/forever-sim/actions/runs/41732764084) **FAIL 57/165**, 44 paid probes; no official Mage/Priest P3 ledger row. An explicit `qualified_wand_dps_proxy` incorrectly triggers equipped-weapon applicability before matching the canonical item/source fact; other real missing stat-weight blockers remain.
- **Action:** Work2 removes this **observed false equipped-wand dependency** on the production P3 path, tests Mage/Priest proxy versus real equipped-source mode, then executes the focused real providers and hands the genuine gate outcomes to Merge. Removing a false blocker can increase actually verified gear-stat assertions, but neither a PASS nor numerical M1 credit is presumed. Work2's unrelated HPS/TPS matrix/witness diagnostics are **not** an M1-priority gate task.

## Independent Clean lane — not gate credit

Clean owns retirement of dead **P1/P2 and GameIR** under [#357](https://github.com/dosibjrn/forever-sim/issues/357) / [#359](https://github.com/dosibjrn/forever-sim/issues/359) and [PR #714](https://github.com/dosibjrn/forever-sim/pull/714). Delete dead callers; retain only proven live P3–P7.5 dependencies and actual optimizer use. Do not add a second game model or promote architecture cleanup to a fake M1 gate.

## Next Prio cycle

Re-read newest `main`, [Prio role](agents/PRIO.md), official ledger, actual production results and current owned issues/PRs; recompute expected **incremental M1 gain per effort**. Select **one** active gate and its most effective next real operation; create/sharpen an executable issue, update this queue and do not duplicate work already executing. Do not edit the Merge-owned ledger or invent eligibility gates. [Router](AUTONOMOUS_AGENTS.md).
