# Worker contract — small gates, integrator-owned merges

**Canonical truth:** [PROCESS](../PROCESS.md) (approved v2.10), [OVERALL PLAN](../OVERALL_PLAN.md) (approved v5), [README](../README.md) and [evidence index](evidence/README.md). Git stores history. Never replace approved text with a PROPOSED draft.

**Current scoreboard:** **0 / 148 fully accepted checkpoints**. Levels 20,30,40,60 only; 9 unrestricted + 4 Druid profiles + 8×3 other profiles = 37 per level. No L50.

**Responsibilities:** worker creates an individual `work/*` branch, implements **one formal gate for one class/level/profile**, runs its tests, commits reproducible evidence. **Integrator** reviews acceptance, scope, CI and evidence and alone promotes the accepted gate into `main`. Do not bundle pending unrelated changes, change approved acceptance criteria silently, or present green compilation as a gameplay gate PASS.

## Previously accepted: Druid L60 Balance P7.1 (Rust)

The owner explicitly approved P7.1 using the real pinned Rust engine and exact reconstructed, validated Rust request: **728.1936126415858 DPS / 10,000 fights**. See [owner's Druid gate decision](evidence/druid-p7/README.md) and [raw reproducible Rust evidence](evidence/druid-l60-balance/p7.1/README.md). Do **not** require repeating this accepted owner decision before working on the next slice.

**Truthful technical limits:** this owner's specific P7.1 Rust acceptance is not proof of an unexecuted **live gsim-2D↔native** integration. Under PROCESS v2.9, **Rust is preferred; Go is equally accepted** wherever the selected genuine pinned engine implements the necessary semantics. Later/new live gates still require real causal gsim-2D↔selected-Rust/Go feedback; do not fabricate it.

## Next work item: Druid L60 Balance — P7.2

**Do only this gate**: independent cold **300 s rotation/APL-only search**, fixed pinned reference gear and talents, real executable legal candidates, saved reference encounter, buffs and consumes. No seeding with saved reference APL. Persist each genuinely paid candidate and winning rotation; evaluate on compatible stochastic scoring against **99% of the pinned external 728.1936126415858 DPS reference (= 720.91167651517 DPS)** using the runtime and integration specified by PROCESS, or explicitly document the approved alternative before claiming PASS.

**Evidence location:** `docs/evidence/druid-l60-balance/p7.2/` with exact source/ruleset/database commit, gear/enchant IDs, talent points, APL, buffs/debuffs, consumes, engine binaries/hashes, build/run logs, paid candidate counts, 2D→combat→2D causal logs when applicable, DPS distribution, validator, and any required holdout.

If blocked, record **BLOCKED** with the real missing precondition. Do not do P7.3/P7.4/P7.5 or a broad refactor as part of this work item.

Afterward: P7.3 talent-only → P7.4 gear-only → P7.5 independent joint gear×talents×APL, each one branch/one gate.

**Reference floors:** P7.2–P7.4 individually require `DPS >= 0.99 × saved external reference`; P7.1 keeps exact reference matching, and P7.5 still requires `max(external reference, 0.99 × strongest compatible P7.1–P7.4 result)` using the **mean DPS of >=1,000 independently frozen stochastic fights; no one-sided 95% CI/PASS limit**. Previous P7.1–P7.4 means must be explicitly **accepted, legal and comparable** on the pinned source/engine/encounter/RNG/scoring; rerun incompatible winners on matched settings. Never automatically use PR #23's unvalidated 797.362 DPS as prior. The 1% tolerance never excuses exceeding the search budget or missing live engine↔2D evidence. [Shared pure threshold implementation](../src/game/p7_reference_floors.py) is available to future executable gate runners; it does not certify a run by itself. Full 148 certification also needs compatible P1–P6 evidence.

Report each W as: `branch | formal gate | changed files | engine revision | CI/logs | measured outcome | evidence path | PASS/FAIL/BLOCKED | next smallest action`.
