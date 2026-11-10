# Shared autonomous-agent contract

This file contains only rules that apply to all five agents. Read it together with the lightweight router in [AUTONOMOUS_AGENTS.md](../AUTONOMOUS_AGENTS.md) and exactly one role file.

**Canonical repository:** `dosibjrn/forever-sim`, branch `main`. GitHub `main` is shared memory and the source of truth for current assignments and contracts. The goal remains **148/148 genuinely certified checkpoints**; read live counts from the approved evidence, never from this document or an old conversation.

## Owner-controlled agent descriptions

**Agent descriptions and operating contracts are immutable during autonomous work cycles.** No agent (Prio, Work1, Work2, Merge or Clean) may edit, rewrite, update, move or delete `docs/planning/AUTONOMOUS_AGENTS.md` or any file under `docs/planning/agents/` **unless the user explicitly and separately requests the particular instruction change**. This includes an agent's own description, another agent's description, COMMON, WORK_COMMON and gate-specific agent notes. An issue, a PR, old/stale wording, a changed M1 verdict, repo cleanup, or an agent's self-identified improvement is **not** owner authorization.

Keep changing priorities, assignments, runs and results in `docs/planning/WORK_PRIORITY.md`, the owned issue/PR and the canonical Merge-owned M1 ledger—not in static role descriptions. If a role description conflicts with current verified work, follow higher-priority owner decisions and the live queue, note the stale text in the existing issue/PR, and continue the real gate work **without silently changing any agent-description file**. Role-contract changes require a new explicit user request.

## Owner decision: permanent PASS and route-first capability (2026-11-10)

**Once Merge has recorded an official M1 PASS, that gate is finished permanently through 148/148.** No agent may re-run, reopen, invalidate, downgrade, or request fresh proof of an accepted gate because source SHA, runtime, API, optimizer or other code later changed, or because a newer comparison/compatibility concern appears. Fix genuine newly discovered production defects forward with focused changed-code tests; do not question the historical gate's accepted validation value. Unrecorded green workflows, diagnostics and PARTIAL are not accepted PASSes. Only unaccepted gates are eligible for future official M1 work.

The immediate metric for current owner-selected work is **next executable player-facing capability**, especially the Warlock route and self-driving generic level-range orchestrator. Start automation while advancing M0.5, reuse exact compatible completed/in-flight native-paid results and prefer one continuing feature PR to repeated per-level PR/workflow ceremonies. Formal still-unaccepted M1 certification remains independent and cannot block releasing honestly labeled measured/provisional product output.

## Authority

- [OVERALL_PLAN](../../../../OVERALL_PLAN.md) defines **what** the project is building.
- [PROCESS](../../../../PROCESS.md) and [gate contracts](../../gates/README.md) define **how** work is accepted.
- [WORK_PRIORITY](../WORK_PRIORITY.md) is the live, current-only work allocation and ownership queue.
- This contract and role files organize work; they do not override approved scope, process or gates.
- Continue the existing owned issue/branch/PR. Do not rely on stale conversation summaries, fixed historical issue numbers or old task prompts. Do not take another agent's owned branch.

## Owner decision #1: MythicSim owns Warcraft mechanics

Forever must not recreate or require trainer/quest/rank acquisition certificates, source-acquisition ledgers, versioned spellbook proofs, index-to-client identity certificates, or an independent Warcraft legality/semantic proof in any active P3–P7.5 gate, optimizer or route.

**MythicSim Rust is authoritative** for Warcraft source facts, spell/rank acquisition, talent/gear/enchant/APL legality, combat effects and game-world execution. Forever defines scenarios, generates/optimizes candidates, calls and observes the native engine, and records the existing gates.

- Before every Prio/Work1/Work2/Clean implementation cycle, read current [WORK_PRIORITY](../WORK_PRIORITY.md); consult the relevant source-boundary decisions [#357](https://github.com/dosibjrn/forever-sim/issues/357) and [#359](https://github.com/dosibjrn/forever-sim/issues/359) only when the live change touches source/mechanics authority. Check the selected MythicSim fork and other proven production modules before adding functionality.
- Never add or extend GameIR, a parallel Python game model, a Forever game-legality/source catalogue, or a Python workaround for missing Rust behavior.
- Delete dead callers and their GameIR dependencies outright. Migrate only behavior proven necessary for active P3–P7.5 gate execution or actual optimizer use to the existing native boundary, then remove the duplicate. Preserve real effects, candidate reachability, native refusals, world/2D/100-mob semantics, approved gates and historical M1/PASS records; do not move code merely to remove imports.
- Owner decision #2 (2026-11-03): P1 ability and P2 talent gates are retired from formal acceptance. Active gates are P3–P6 and P7.1–P7.5 (nine per checkpoint); preserve historical P1/P2 ledger rows but ignore them in M1 and reject new P1/P2 records. Do not schedule or recreate P1/P2 work.
- Owner clarification (2026-11-04): **retire P1, P2 and GameIR rather than rebuilding their obsolete behavior behind new adapter checks.** Delete unused historical/test/diagnostic callers along with their old GameIR implementation. Migrate **only** behavior proven necessary for active P3–P7.5 gate execution or actual optimizer use; otherwise no native replacement is required. Change the Rust fork only for a specifically reproduced missing capability on such an active caller. Use an ordinary fork branch/PR; `/rust-fork-sync` is only the privileged sync path.
- Owner direction (2026-11-04): prioritize genuine failing active P3–P7.5 gates on the nearest completable checkpoint before discretionary architecture cleanup. Do not move or duplicate code merely to remove a GameIR import. Remove Python legality checks only where they actually pre-veto candidates that MythicSim already judges; change Rust only when a real gate run demonstrates a missing required interface/capability.

## Trusted-engine boundary: do not validate MythicSim

Do not add tests, audits or Python checks to prove that native talent ranks, spell/gear/enchant/APL legality, ability effects or other Warcraft mechanics are correct. A native `INVALID` or `UNSUPPORTED` response is authoritative, not a claim Forever must independently verify.

Test only changed Forever-owned behavior: request serialization, forwarding to native, response propagation and classification of `VALID` / `INVALID` / `UNSUPPORTED` / execution errors. Use fixtures/mocks for response mapping; add a focused real native integration test only when Forever's invocation or result handling changed and that test is needed to verify the integration.

For a Forever-only change that removes duplicate rules or changes only the adapter, Rust source compilation, native-gameplay tests, independent rules audits and revalidation of the unchanged pinned engine are **not** PR/merge prerequisites. Auto-triggered Rust workflows are informational when no Rust source or gitlink changed. Verify the changed integration when a real engine source/gitlink change requires it; do not turn that into a Warcraft-rules audit.

## Do not invent problems or blockers

- A blocker requires concrete evidence: a reproducible production/source FAIL, a real error, an unmet approved PROCESS/gate requirement, or a specifically named missing capability. Cite the run, source or exact criterion.
- Distinguish **proven defect**, **not yet tested**, and **possible risk**. A missing PASS from an unrun acceptance test is not proof that implementation, build or source data is broken.
- The approved gate defines the requirements. Do not add extra exhaustive-combination, source-audit, UI-proof or compatibility conditions unless that gate explicitly requires them.
- Continue owned work, run the smallest relevant production test when useful, fix the first real FAIL, regress it and proceed. Do not start speculative investigations or slow a working merge with hypothetical risks.
- Report what is proven, what remains untested and the next actual gate requirement. If evidence is absent, say the test has not run; do not promote a hypothesis to a blocker.

This rule does not relax OVERALL_PLAN, PROCESS or any gate. It prevents invented acceptance requirements and unsupported failure claims.

## Operating model

- Five independent conversations and five separate hourly tasks: Prio XX:00, Work1 XX:10, Work2 XX:20, Merge XX:40, Clean XX:50, Europe/Helsinki. These are intended offsets, not proof that an automation is enabled.
- Each cycle starts from latest `main`, this shared contract, the agent's own role file, current [WORK_PRIORITY](../WORK_PRIORITY.md), and the relevant owned issue/PR/branch. Read only the relevant sections of OVERALL_PLAN, PROCESS and gate docs.
- Each agent reads **only its own role file**. Work1 and Work2 also read [WORK_COMMON](WORK_COMMON.md). Read [P7 notes](P7.md) only when the assigned work actually touches P7. Do not load the other agents' contracts.
- Continue, do not restart: owned issues/branches/PRs are durable handoffs. Change assignment only for a proven priority/dependency reason and hand off unfinished work.
- Make ordinary technical decisions and carry work through commit/PR/merge within the role's authority. Ask only when blocked by external authority/permissions or a change to approved scope.

## GitHub Actions

At cycle end, consider whether the next real test/build/production run is concretely useful, ready and allowed. Start it on an existing workflow when justified; do not wait for a long run to finish. Link the run, exact ref/SHA, purpose and next check in the existing owned issue or PR. No separate agent logs, timestamp PRs or result registers.

Use existing workflows first. Prefer focused, economical runs. Do not repeat unchanged 300-second searches, 1,000-fight stochastic holdouts or hourly heavy acceptance. A green CI run or starting a workflow does not itself prove a gate PASS. Work1 and Work2 inspect their own relevant completed and in-progress Actions at cycle start; other agents inspect relevant results as needed.

## M1 reporting and ownership

When M1 is material to the result, lead with **`M1 measured: X.XXXX% (float=0.XXXXXXXXXX)`**, read from latest `main` using `python tools/m1_progress.py` and its `measured_percent` / `measured_fraction` values. This is partial-inclusive diagnostic coverage, **not** certified checkpoint percentage, acceptance or forecast. Do not derive it from `C/148`, an SVG, CI or a previous conversation. If the live scoreboard is unavailable, say so. Avoid repeating unchanged `0/148` boilerplate. The official certified `C/148` checkpoint and `N/1332` active PASS-gate counts are separate facts; report them only when they change, the user asks, or a specific gate issue needs them.

**Only Merge** launches the trusted M1 recorder and records or commits `docs/planning/M1_PASSES.tsv`. A true PASS requires an accepted production run and PROCESS predicate; PARTIAL remains diagnostic and never increments the certified gate count. Keep one ledger row per genuine PASS / bounded PARTIAL as defined by the production script: no per-gate evidence documents or secondary registers. Nine genuine active gate PASSes automatically certify a checkpoint; **no extra compatibility certificate, metadata audit or shadow approval** is allowed. A real runtime mismatch belongs in the affected gate. Prio, Work1, Work2 and Clean must not edit the ledger, invoke the recorder or promise a numerical increase.

Every production-code PR must contain `M1 affected gates: class:level:spec:gate ...` for concrete affected gates, or `M1 affected gates: none` when no gate behavior changed. This is an execution hint, not a manually assigned verdict. Merge's exact dispatch and recording procedure is in [MERGE](MERGE.md).


## Incremental progress and reports

Split unfinished gates only into existing, testable production behaviors and never change the approved priority order. For a genuinely comparable count, report measured `passed/known applicable` and coverage `c`; a separate illustrative work-effort heuristic may be shown as `E=0.25*c` for `c<=0.8`, otherwise `E=0.2+4*(c-0.8)`. This encodes an assumed 80/20 effort curve; it is **not** observed engineer-hours, acceptance or a scheduling signal. Mark both figures provisional when source scope is unknown. Do not apply the curve to heterogeneous/small steps, invent denominators, create shadow KPIs or chase PR #60 diagnostic ticks. Report one short factual result: measured M1 headline when available, actual behavior/structural change, commit/PR, real validation and next concrete action.
