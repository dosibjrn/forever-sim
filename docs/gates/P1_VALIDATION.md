# P1 — validate source-legal ability effects on the selected production engine

**Status:** Approved P1 validation contract, 2026-11-01. This guide explains
[PROCESS v2.11](../../PROCESS.md), not a second competing gate specification.
It does not assert that any checkpoint or native effect has already passed.

## Boundary

P1 validates **what abilities the selected production simulator can do**;
it does not require a particular code architecture.

1. **Source inventory:** derive the (class, level, permitted spec/talents, ruleset)
   legal spell/rank frontier independently of implementation. Use verified
   acquisition and talent/rune grants to establish legality. Raw source-index
   level hints are only *candidates*, never accepted evidence that the spell is learned.
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
   conditional trigger unresolved, or source acquisition unresolved. Confirm
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
| `tools/wf_p1_native_effects.py` | Run real pinned native Rust APL-present/absent pair when supplied executable and request | **Diagnostic only**, not timing-preserving |
| `tests/test_wf_p1_native_blackbox.py` | Source/schema/regression tests; no mocked native combat PASS | **None** |
| `tools/wf_gate.py --gate P1` | Existing historical selected-gsim provider | Not silently replaced by this experiment |

The existing gsim-specific diagnostic remains useful for gsim backend
regressions. **Its `2/61` Hunter L20 action count is not native MythicSim P1
coverage.** A missing gsim GameIR slice at L60 does not mean a native L60
spell is missing.

## Next production task

Expose/consume genuine spell-by-ID execution or other condition-appropriate
native mechanism on pinned MythicSim, plus actual event/state observations.
Run a positive and effect-neutral control through **that** engine. Complete
source learned/talent legality and optimizer admission independently.
Only then allow `tools/wf_gate.py` to report native P1 PASS for the selected
checkpoint. Do not invent missing mechanics in a Python test adapter and do
not manually update PASS ledgers.

The source-only 18-case matrix can be GREEN while **zero** native abilities
have been executed. That is correct; P1 itself remains unresolved.
