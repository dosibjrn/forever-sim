# FOREVER SIM — active M1 work queue

**Priority policy:** choose the active checkpoint-gate with the **highest credible *incremental* genuine M1 measured-float gain per unit implementation, acceptance-run and compute work**. Do **not** always pick the nearest-to-complete 9/9 checkpoint. Calculate M1 from the [single official ledger](M1_PASSES.tsv) and [m1_progress.py](../../tools/m1_progress.py). A new PASS can add one gate-equivalent (1/1332 = 0.075075 percentage points), a new eligible PARTIAL only its genuine measured fraction, and improvements of already-recorded PARTIALs only the positive change above the previous high-water mark. An unexecuted gate is **not a FAIL**. No credit is awarded before Merge records a real production outcome. The accepted gate contracts remain [PROCESS](../../PROCESS.md) and [gates](../gates/README.md).

## Execute in this order

### #1 — cheapest likely incremental M1 result: Druid L60 unrestricted P3 — [issue #732](https://github.com/dosibjrn/forever-sim/issues/732)

- **Chosen gate:** `druid:60:unrestricted:P3`; **not yet measured** in M1 (no ledger row). The same-level Druid **Balance P3** and Druid **unrestricted P3** at L20/L30/L40 already have accepted PASS rows; the existing `tools/wf_gate_p3_live.py` directly supports `unrestricted` without named spec-frontier construction. This is a credible *low-risk hypothesis*, **not** proof of a future PASS.
- **Best next action / owner: Merge.** Run the **existing real P3 gate exactly once** via its trusted single-target recorder, on current main. No architecture work, extra eligibility checks, fake data, new gate harness or code changes first. A P3 budget is up to 44 paid source evaluations, versus the 300 s + 1,000 fights used by P7 searches. Use issue #732 and existing [Prio issue #131](https://github.com/dosibjrn/forever-sim/issues/131) as dispatch handoff; only Merge launches and records the run.
- **Expected gain if PASS:** +1 genuine gate-equivalent = **+0.075075 M1 percentage points**. An eligible executed PARTIAL may add a smaller measured amount; FAIL/BLOCKED may add zero. No earned gain is claimed before the trusted result.
- **If real FAIL:** record first exact source error or failed P3 predicate and give Work1 the smallest **observed production-code repair** once its in-flight #729 PR is handed off. Do not assume any defect or duplicate an active owner branch.

### #2 — highest current production repair: Druid L60 Balance P7.5 — Work1 [PR #729](https://github.com/dosibjrn/forever-sim/pull/729)

- **Measured evidence:** post-#726 [heavy run #41737592618](https://github.com/dosibjrn/forever-sim/actions/runs/41737592618) completed a 300.000154 s cold search and 1,000-fight native+2D final; Balanced selection 714.626826 DPS but frozen Stochastic mean **655.545821 DPS**, below **708.092235 DPS** accepted-prior floor and **677.220060 DPS** external-only floor. Result **FAIL**, not a workflow failure or M1 improvement. Existing P7.5 PARTIAL `736.8768/753.7756` remains the high-water mark.
- **Work1:** finish PR #729's genuinely paid crossover-RNG stream isolation, test its affected Forever-owned search behavior, and hand off to Merge. This may improve repeatability, **not proven DPS**. After a production change and Merge integration, one justified exact-main P7.5 acceptance run—not a repeated unchanged heavy run. A P7.5 PASS over existing ~97.76% PARTIAL adds only the remaining ~0.0224 gate-equivalent, much less immediate M1 float than a new cheap P3 PASS, although it advances the first checkpoint.
- **No competing Prio implementation branch.** Work1 retains ownership.

### #3 — independent joint optimizer lane: Work2 [issue #15](https://github.com/dosibjrn/forever-sim/issues/15) / [PR #728](https://github.com/dosibjrn/forever-sim/pull/728)

- #720's APL condition preservation was merged; PR #728 refreshes formerly blocked source-native L60 optimizer baseline fixtures. Its 5s × 28 diagnostic is **not** accepted gate credit and PR #728 declares `M1 affected gates: none`. Complete only as ongoing owned work; **do not prioritize more matrix, HPS/TPS diagnostics or architecture work over a verifiable positive active-gate float opportunity**.
- Next Work2 task should be **named by its measurable affected P3–P7.5 gate**, actual runtime failure or paid search throughput outcome before any additional expansion. No second Python Warcraft legality subsystem.

### #4 — next distinct real failed gate once higher return work is handled: Druid L60 Balance P7.4 — [issue #131](https://github.com/dosibjrn/forever-sim/issues/131)

- [Heavy production #41721736018](https://github.com/dosibjrn/forever-sim/actions/runs/41721736018): 300.000119 s search, cold Balanced screen **727.920799 DPS**, frozen 1,000-Stochastic live mean **692.819689 DPS**, under required **720.9117 DPS**. Real `P7_4_FROZEN_STOCHASTIC_DPS_BELOW_REFERENCE_FLOOR`.
- A next action must **improve paid winner stochastic generalization/final selection**, not merely repeat the same 300-second acceptance or validate MythicSim's mechanics. Work1 picks it up after its existing P7.5 PR; any new bounded implementation issue must name the concrete observed production weakness and targeted validation.

## Independent Clean ownership — not an M1 gain item by itself

Clean owns deletion of dead **P1/P2 and GameIR** dependencies under [#357](https://github.com/dosibjrn/forever-sim/issues/357)/[#359](https://github.com/dosibjrn/forever-sim/issues/359), including [PR #714](https://github.com/dosibjrn/forever-sim/pull/714). Deleting retired code is valuable architecture maintenance but **not** top M1 gate priority unless an active gate's measured progress depends on it. No GameIR replacement, parallel source-legality rules, or invented new proof conditions.

## Every future Prio cycle

1. Read newest main, M1 ledger and relevant genuine run evidence; compare the **incremental float actually available** and estimated cost across unmeasured, PARTIAL and FAIL active gate candidates.
2. Choose the **highest believable float gain per unit real effort**, not whichever checkpoint is nearest 9/9. Favor a one-off inexpensive already runnable gate over an hour-long heavy optimization when justified. Preserve nonduplicated in-flight PRs.
3. Create or sharpen exactly one executable issue with checkpoint/gate, observed result (or NOT YET MEASURED), concrete next operation, causal M1 effect, owner, cost and exact verification. Put it here; do not award PASS/PARTIAL yourself. Only Merge performs trusted ledger runs and writes M1.

**Agent entry:** [AUTONOMOUS_AGENTS](AUTONOMOUS_AGENTS.md), [Prio role](agents/PRIO.md). Keep this queue short and current. No M1 ledger edits outside Merge.
