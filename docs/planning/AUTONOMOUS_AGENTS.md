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
| **Prio** | [`agents/PRIO.md`](agents/PRIO.md) | Own dependency order and work allocation; maximize genuine measured M1 progress. |
| **Work1** | [`agents/WORK1.md`](agents/WORK1.md) | Execute the current #1 critical-path implementation. |
| **Work2** | [`agents/WORK2.md`](agents/WORK2.md) | Execute the highest independent #2+ implementation. |
| **Merge** | [`agents/MERGE.md`](agents/MERGE.md) | Integrate PRs, verify affected gates and own the sole M1 ledger writer role. |
| **Clean** | [`agents/CLEAN.md`](agents/CLEAN.md) | First detect and eliminate counterproductive gate work and invented requirements; also own repository architecture and safe code retirement. |

## Source of truth and authority

Canonical repository: `dosibjrn/forever-sim`, branch `main`. GitHub is shared memory; do not rely on conversation history, stale run summaries or fixed historical issue/PR numbers.

- [WORK_PRIORITY.md](WORK_PRIORITY.md) is the live assignment/ownership queue.
- [REPOSITORY_STRUCTURE.md](../REPOSITORY_STRUCTURE.md) is the maintained target architecture owned by Clean.
- [OVERALL_PLAN.md](../../OVERALL_PLAN.md) defines project scope.
- [PROCESS.md](../../PROCESS.md) and [gate contracts](../gates/README.md) define acceptance.
- These role files and task prompts organize execution; they cannot override approved scope or gates.

The five tasks run in separate conversations, with intended hourly offsets in Europe/Helsinki: Prio XX:00, Work1 XX:10, Work2 XX:20, Merge XX:40, Clean XX:50. The task schedules/prompts are stored separately from this repository contract; changing this file does not itself update those automations.
