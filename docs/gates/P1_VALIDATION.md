# P1 — validate source-legal ability effects on the selected production engine

**Status:** Approved P1 validation contract, 2026-11-01. This guide explains
[PROCESS v2.11](../../PROCESS.md), not a second competing gate specification.
It does not assert that any checkpoint or native effect has already passed.

## Boundary

P1 validates **what abilities the selected production simulator can do**;
it does not require a particular code architecture.

1. **Selected native inventory:** use the (class, level, spec, talents, ruleset)
   candidate space and MythicSim's own native prepare/validation to decide
   which spell/rank requests are valid or unsupported. Forever must not maintain
   trainer, learned-spellbook, source-acquisition-batch or quest-proof checks.
   Historical source-index lists may help diagnostics, but cannot override native.
2. **Applicability:** keep the explicitly approved, scenario-specific
   `DOES_NOT_AFFECT_SIM` list separate from test results. Identify autoattacks,
   pet actions, passive/auxiliary spells and uncertain grants by their real roles;
   never count a pet skill as a missing player cast action. Changing the scenario
   requires reconsidering its applicability decisions.
3. **Production execution:** for combat effects, run real pinned MythicSim Rust/Go
   with appropriate resource/form/target/trigger conditions. Observe native
   damage, healing, overhealing, resources, stats, real auras/DoTs, CC or analogous
   behavior. A deterministic controlled positive/negative experiment or
   comparable targeted real-runtime assertion is enough. A per-spell 100-mob
   fight, raid log, or vast repeated RNG test is **not** a P1 requirement.
4. **World-dependent mechanics:** use the *real* gsim 2D world coupled to the
   selected MythicSim executor only when the tested behavior depends on
   range, movement, geometry, facing or another world-owned effect. Do not
   demand a 2D wrapper for a native direct-damage/heal effect.
5. **Outcome and candidate reachability:** label each source-legal applicable
   ability as executed behavior observed, not observed, unexecutable,
   or conditional trigger unresolved. Native INVALID and UNSUPPORTED remain distinct. Confirm
   actual selected-engine candidate usability as part of final P1, but never
   equate a missing Python GameIR action with a missing MythicSim ability.

**Important:** equal spell registration, a cast counter, a mock event, a
source-index name, or a non-executed CI test is not behavioral proof.
An APL entry removal is useful as a *diagnostic* but can change timing and
other action selection; it does not alone prove a spell's isolated effect.
No backend union of incomplete implementations can be treated as P1 PASS.

## Current small implementation

| Tool | Purpose | Acceptance authority |
| --- | --- | --- |
| `tools/p1_native_source_inventory.py` | Source-only candidates, role separation, scenario applicability; no GameIR | **None**; candidates may be unverified |
| `tools/wf_p1_native_scope_matrix.py` | Class/level source inputs for 9 classes × L20/L60 | **None**; no native effects are executed |
| `tools/wf_p1_native_effects.py` | Run a selected-Rust PreparedV2 one-action/no-action control pair and observe native direct-effect delta; 2D is opt-in only for world-owned effects | **Diagnostic only**, never a P1 PASS |
| `tools/wf_gate_p1_live.py` | First native-owned live caller: Druid L20 source Claw (spell ID 1082) goes through PreparedV2; optimizer candidate reachability remains separately checked | **Partial migration only**; all other actions remain transitional |
| `tests/gates/test_wf_p1_native_blackbox.py` | Request-shaping and fail-closed native-refusal boundary tests; no mocked native combat PASS | **None** |
| `tools/wf_gate.py --gate P1` | Existing hybrid live provider: the Druid L20 Claw pilot is native, remaining actions retain the historical GameIR path | Not full native P1; do not record PASS |

The remaining gsim-specific diagnostic is still useful for backend
regressions. **Its `2/61` Hunter L20 action count is not native MythicSim P1
coverage.** The Druid L20 Claw route is one native direct-effect observation,
not a complete native inventory or a P1 acceptance result. A missing gsim
GameIR slice at L60 does not mean a native L60 spell is missing.

The Claw pilot uses source spell ID 1082 only to select the test. Its
checkpoint-level label is Forever-side metadata: the selected Rust
RaidSimRequest schema has no player-level field, so this experiment makes no
level-specific acquisition claim. Native INVALID/UNSUPPORTED/no-effect
responses remain visible and never fall back to GameIR.

## Partial coverage and estimated effort (not P1 acceptance)

[Draft PR #60](https://github.com/dosibjrn/forever-sim/pull/60) explored `observed/checked` and thresholds 50/80/85/88/91/93/95/97/99 %. Keep **the real measured coverage ratio**; optionally show a separate **Pareto-estimated work completed percentage**, under the stated hypothesis that the first 80% of comparable cases cost 20% of work and the last 20% cost 80%. See [the calculation and caveats](../planning/GATE_PROGRESS_80_20.md). **Do not use Pareto to change work ordering,** turn its estimate into a PASS gate, or chase artificial `effect_probe_progress_naksut` ticks. Toy-gsim results are not native PASS. On the **selected real production engine**, count actually observed effects over the currently classified relevant source-legal ability set. Show native refusals and conditional-trigger cases separately; mark diagnostic coverage *provisional* until a real native ability inventory and execution are measured. Never silently shrink the denominator or equate 80% to P1 PASS.

## Next production task

Continue migrating the remaining P1 actions from GameIR runtime execution to
the selected native PreparedV2 request/response path. Keep optimizer candidate
reachability as a separate check, but do not reintroduce source acquisition,
rank-legality, or Python effect proofs. The Claw pilot is a direct-damage
control experiment, not a complete P1 gate. Only after the full applicable
native inventory and effect set is exercised may `tools/wf_gate.py` report
native P1 PASS for the selected checkpoint. Do not invent missing mechanics in
a Python test adapter and do not manually update PASS ledgers.

The source-only 18-case matrix can be GREEN while **zero** native abilities
have been executed. That is correct; P1 itself remains unresolved.
