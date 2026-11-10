# Forever Sim — autonomous-agent router

This is the **lightweight entry point**, not the full five-agent contract. Role-specific instructions live in [`docs/planning/agents/`](agents/).

## Startup: read only what applies to your role

Every cycle, start from latest `main` and read, in order:

1. This router: `docs/planning/AUTONOMOUS_AGENTS.md`.
2. Shared rules: [`agents/COMMON.md`](agents/COMMON.md).
3. Exactly one role file from the table below. **Do not load the other agents' role files.**
4. Work1 and Work2 also read [`agents/WORK_COMMON.md`](agents/WORK_COMMON.md). Other roles do not.
5. Read current [`WORK_PRIORITY.md`](WORK_PRIORITY.md), your owned issue/PR/branch and relevant Actions. Read only the applicable sections of [OVERALL_PLAN](../../OVERALL_PLAN.md), [PROCESS](../../PROCESS.md) and [gate contracts](../gates/README.md). Read [`agents/P7.md`](agents/P7.md) only when your assigned work actually touches P7.

| Agent | Read this role file | Stable responsibility |
| --- | --- | --- |
| **Prio** | [`agents/PRIO.md`](agents/PRIO.md) | Own dependency order and work allocation; prioritize the owner-selected runnable product outcome, then unaccepted M1 work. |
| **Work1** | [`agents/WORK1.md`](agents/WORK1.md) | Fix the current #1 source-native/Rust capability gap on the product critical path; otherwise the assigned active gate. |
| **Work2** | [`agents/WORK2.md`](agents/WORK2.md) | Build the autonomous generic gsim→Rust route/optimizer and next independently runnable product slice. |
| **Merge** | [`agents/MERGE.md`](agents/MERGE.md) | Integrate tested PRs promptly, run only unaccepted affected gates and keep the already accepted M1 ledger immutable. |
| **Clean** | [`agents/CLEAN.md`](agents/CLEAN.md) | Remove false work, duplicate per-level orchestration and dead code; safeguard CI and accepted evidence. |

## Source of truth and authority

Canonical repository: `dosibjrn/forever-sim`, branch `main`. GitHub is shared memory; do not rely on conversation history, stale run summaries or fixed historical issue/PR numbers.

- [WORK_PRIORITY.md](WORK_PRIORITY.md) is the live assignment/ownership queue.
- [REPOSITORY_STRUCTURE.md](../REPOSITORY_STRUCTURE.md) is the maintained target architecture owned by Clean.
- [OVERALL_PLAN.md](../../OVERALL_PLAN.md) defines project scope.
- [PROCESS.md](../../PROCESS.md) and [gate contracts](../gates/README.md) define acceptance.
- These role files and task prompts organize execution; they cannot override approved scope or gates.

An official accepted M1 PASS is permanent until 148/148: no agent may reopen, rerun, downgrade or invalidate it, including after an engine or code change. Prefer one capability-oriented implementation and reusable automation to one PR/workflow per level. The target is the next runnable user-facing capability, not an activity count.

The five tasks run in separate conversations, with intended hourly offsets in Europe/Helsinki: Prio XX:00, Work1 XX:10, Work2 XX:20, Merge XX:40, Clean XX:50. The task schedules/prompts are stored separately from this repository contract; changing this file does not itself update those automations.
