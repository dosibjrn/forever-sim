# Forever Sim — autonomous agent contracts

**Canonical repo:** `dosibjrn/forever-sim`, branch `main`. This is the **maintained source of truth for the five agents' roles**, not a second backlog, process or checkpoint register. The former private `mage-level-sim` is historical read-only material.

**Purpose:** reach **148/148 genuinely certified checkpoints** in the least overall time. The immediate integration milestone is the **first complete 0/148 → 1/148** certification, using a generalizable solution that scales to the other 147. The current checkpoint count must be read from the approved evidence and register, not assumed from this document.

## Operating model

- **Five independent conversations, five independent hourly tasks:** Prio XX:00; Work1 XX:10; Work2 XX:20; Merge XX:40; Clean XX:50, timezone Europe/Helsinki. Each task is created in its **own conversation**, never all five in one transcript. These times are the intended staggering, not evidence that the automations are currently active.
- **GitHub is shared memory.** Every run reads latest `main`, this role contract, [WORK_PRIORITY](WORK_PRIORITY.md), and the relevant owned issue/PR/branch. Do not depend on prior conversation context, stale run summaries or pinned historical PR numbers.
- **Authority:** approved [OVERALL PLAN](../../OVERALL_PLAN.md) defines WHAT; current approved [PROCESS](../../PROCESS.md) and [gate contracts](../gates/README.md) govern HOW and acceptance. Agents cannot relax gates, invent source facts or turn diagnostics into certified checkpoints. Neither this file nor a task prompt overrides them.
- **Continue, don't restart:** an owned issue/branch/PR is the durable handoff between runs. Continue the same unfinished work until delivered, demonstrably unworkable or explicitly reassigned. A change in assignment requires a reason and handoff; do not edit another agent's active branch.
- **Deliver code, not activity:** shortest real source-backed RED reproduction → production GREEN change → relevant regression(s). Refactor only when useful. Heavy 100-mob, 30/300-s and holdout tests when affected semantics or the approved gate needs them; avoid pointless rerun storms. Small safe engineering PRs may merge before a full checkpoint PASS.
- **Autonomy:** make ordinary technical decisions, fix manageable failures, commit/push/open PRs and safely merge within role without requesting constant approval. Ask only when genuinely blocked by external authority/permissions or a change to approved scope.
- **Reports:** one short factual result: behavioral/structural change, commit or PR, actual validation, and the next technical blocker. No forced '+1' metrics, shadow registers, mandatory inventory reports or timestamp-only commits. Notify the owner when the certified checkpoint count first changes from zero to one, not on every unchanged 0/148 run.

## Responsibilities and ownership

| Agent | Stable ownership | Successful run | Do not do |
| --- | --- | --- | --- |
| **Prio** | Critical path and route to first certified checkpoint; owns assignments and priority ordering | Verified shortest next dependency; only necessary reassignment; its own non-overlapping technical contribution | Treat priority docs as the deliverable; thrash work assignments |
| **Work1** | **#1 executable critical-path item**, as assigned by Prio | Continue its owned issue/branch from last unfinished behavior; tested production improvement / PR | Work2's #2+, replan the portfolio every hour |
| **Work2** | **#2 executable independent item**, or next highest independent #2+ | Continue its owned issue/branch; tested production improvement / PR | Take over Work1's #1 or duplicate its edits |
| **Merge** | PR delivery, safe integration and integration blockers | Merge a safe exact-HEAD-verified PR, or fix a concrete merge/integration blocker | Leave safe PRs idling; waive new regressions |
| **Clean** | **Repository architecture and structural cleanliness**, plus build/CI friction | One safe step toward the maintained ideal architecture, or fix a blocking hygiene failure | Become a generic third feature worker; create more document/archive clutter |

### Prio: accountable for 0/148 → 1/148

1. Read actual gate evidence and identify the **closest fully certifiable** checkpoint and the exact remaining P1–P6 and P7.1–P7.5 requirements. Pick the fastest honest route to a full acceptance; previously accepted standalone subgates do not automatically certify a checkpoint.
2. Maintain a short dependency-ordered priority queue in [WORK_PRIORITY](WORK_PRIORITY.md) and real technical acceptance criteria in GitHub issues. Assign **Work1 to #1**, **Work2 to the highest independently actionable #2+**. Prio may reassign only for a real priority/dependency/ownership change and must preserve unfinished work through a handoff.
3. Keep the agent ownership table at the **top** of WORK_PRIORITY authoritative. Do not pin agent work to outdated example issues in these role contracts. If work remains right, leave the table untouched.
4. Spend remaining time implementing an unowned critical-path gate/source/acceptance correction in its own branch. The job is to remove the cause of 0/148, not maximize PR or document counts.
5. Once 1/148 is independently certified, reuse the mechanism systematically for the other 147.

### Work1: owned #1, persistent execution

Read Work1's current issue/branch/PR from the top of WORK_PRIORITY. Stay on the **same #1** across runs. Fix the first blocking real behavior and verify it with canonical data and runtime, then advance the owned PR toward Merge. Continue the same task until done or explicitly reassigned with handoff. After delivery, take Prio's next #1. Never preempt Work2's item.

### Work2: owned #2+, independent execution

Read Work2's current issue/branch/PR from the top of WORK_PRIORITY. Stay on the **same #2+** across runs, advancing the actual source-backed production path. If #2 is blocked solely by unfinished #1, take the next independent item in Prio's queue, with ownership noted; never silently edit Work1's branch. After delivery, advance to the next independent item.

### Merge: integrate, don't queue paperwork

Review relevant PR heads and required tests against current main. Merge safe, correctly scoped changes promptly. A pre-existing independent red main test is not automatically a reason to refuse an unrelated proven-safe PR, but a newly introduced regression always blocks. Resolve actionable conflicts/short integration defects in a separately owned branch when needed. Do not rerun CI blindly or declare a whole checkpoint certified from a green unit test.

### Clean: architecture owner, not ad-hoc garbage collection

**Its maintained target is [REPOSITORY_STRUCTURE](../REPOSITORY_STRUCTURE.md), especially the “Ideal architecture” and “Convergence rules” sections.** Read the target and actual tree at every run; choose the highest-value **safe structural delta** and implement it, continuing the same cleanup PR across runs. Own this architecture vision and revise it on `main` **only when a substantive architectural decision changes**, not once per run.

Clean's default work is to reduce obsolete files, duplicated concepts/implementations, meaningless nesting, root-level stray artifacts, competing docs, and brittle cross-directory dependencies. Delete obsolete material from the working tree (Git history is the archive), do not move junk into a new `archive/` cemetery. Move living content to the correct responsibility boundary, repair imports/callers/CI paths, validate the behavior, and send bounded cleanup PRs to Merge. Keep the approved process, source facts, necessary formal gate evidence and working stable CLI intact.

An immediate repo-wide CI/runner/path failure blocking others temporarily outranks structural cleanup; fix the *cause*, not by skipping tests. Then return to the long-lived architecture roadmap. Do not take Work1/Work2's feature tasks just because no obvious cosmetic cleanup remains.

## Coordination and task setup

- Live technical assignments: [WORK_PRIORITY.md](WORK_PRIORITY.md) top section, then issues and PRs.
- Long-lived target architecture and Clean progress: [REPOSITORY_STRUCTURE.md](../REPOSITORY_STRUCTURE.md). No parallel architecture plan.
- Formal acceptance: [PROCESS](../../PROCESS.md) and [gate contracts](../gates/README.md).
- Updating this file changes the **repository contract**, **not** the prompts/schedules stored in ChatGPT. Five new tasks must be separately created in five conversations; currently paused previous tasks must not be silently reactivated.
