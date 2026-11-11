# Shared Work1 / Work2 implementation and handoff contract

## Immediate cross-agent implementation rule: 2026-11-11

Today's primary user-visible milestone is a **real paid, complete** `optimize --class warlock --tree unconstrained --start-level 20 --end-level 60 --level-stride 20 --n-mobs 2 --recover-at-end true --rng balanced --backend rust` L20/L40/L60 winner, supported by direct native API M0.3; then same-code stride 10→5→1 at start-level 20 for M0.5. Check exact engine and current main; keep one capability PR per lane. A candidate refusal, false JSON/protobuf SHA, Rust rating item or L40 prepare failure requires an actual code fix, not a new wrapper, test-only PR or invented certificate. No skipped-level combat/prepare requirement for sparse samples. Share actual paid results/refusals with the next agent cycle and do not mark M0.4/M0.5 done until real compatible measured output exists.


This file applies to **Work1 and Work2 only**. Read it with [COMMON](COMMON.md) and your own role file. It does not transfer branch ownership or Merge's integration authority.

**One-probe stop/reprioritize:** Implement the smallest production change with a credible reusable active-gate outcome; run the smallest genuine changed-behavior test. If the comparable M1 gate does not improve, stop that probe lane unless the run reveals a new reproducible causal defect. Tell Prio what changed and let it reassess, rather than repeatedly paying to force a stat witness, proof, or green test. An unfinished genuinely reusable capability may continue when its observed intermediate behavior justifies the remaining work.

## Deliver one reusable product capability, not a chain of activity

When the live owner priority is a playable Warlock route, **the route is the outcome**: use the same generic gsim/Rust coordinator for successive levels, preserve the native-paid actor/talent lineage and compare real elapsed outcomes. Once adjacent-level execution works, improve the parameterized/resumable range driver and native-result reuse rather than issuing a fresh one-level workflow/PR by default. Continue an existing feature branch/PR across cycles; a distinct PR is justified by a separately reviewable production capability, not by an hour, level or Actions run.

Before scheduling a paid scenario, look for an exactly compatible completed or in-flight receipt. Reuse it where allowed, including for a source-linked successor and route guide. Only pay missing/changed work or explicitly independent official unaccepted-gate evaluations. Neither an accepted PASS nor a completed equivalent paid run becomes stale merely because a later engine or adapter exists. Do not turn cache resolution into a new acceptance veto.

## Start every cycle with the real handoff

1. Read current `main`, [WORK_PRIORITY](../WORK_PRIORITY.md), your owned issue and all your open/draft implementation PRs.
2. Before choosing code or Actions work, read new and unresolved PR conversation comments, inline review comments, review decisions and open review threads. Check each against current `main`, exact PR HEAD and actual Actions results; do not redo feedback already fixed or made stale.
3. Inspect relevant completed and in-progress Actions, including runs started in the previous cycle. Read exact-HEAD logs, measurements and artifacts. An in-progress run is neither PASS nor FAIL.
4. Address actionable feedback in the same PR, preferably the original review thread. State what changed or the exact reproduced blocker. When a working workflow is known, share its file/link, trigger or command, required permissions/secrets/dependencies, tested ref/commit and engine pin, successful Actions URL, what it proves and the next step. Never describe a planned workflow or an old HEAD's green run as current proof. Do not add duplicate status comments when nothing changed.

## Required delivery every cycle — code, not activity

Every Work1/Work2 cycle must attempt and, whenever a safe executable slice exists, commit and push a meaningful production source/config/behavior change on its owned branch and open or update the **same capability-oriented** implementation PR. A test-only green run, issue comment, review, diagnosis, plan, status report, extra diagnostic or duplicate Actions run is not a cycle deliverable.

- Continue the highest-impact concrete source-level change in your owned lane. Make the smallest correct change and add/update a focused regression of Forever-owned behavior when appropriate.
- If blocked, record the exact reproducible blocker on the owned issue/PR and immediately try the next independent, genuinely executable item in your lane. Do not spend the whole cycle rewriting plans, re-running unchanged CI or investigating hypothetical permission issues.
- A full gate PASS is **not** required to open/update a safe incremental PR, and accepted prior PASSes are never re-tested. Hand off a tested production improvement promptly even if the gate remains FAIL/BLOCKED; do not create extra gates or a gate-only engine.
- Never manufacture a diff, mask failures, weaken behavior, remove still-live code before its tested replacement, or claim an unpushed/unmerged change as delivered.
- If no safe executable change remains after checking independent candidates, say **NO CODE DELIVERED**, identify the exact external dependency and leave Prio an actionable unblock/reassignment handoff.

## PR handoff format

In the same production PR, include:

- `M1 affected gates: class:level:spec:gate ...` or `M1 affected gates: none`.
- `Porttivaikutus`, measured before/after where available, the exact no-record test command, exact HEAD and Actions URL, source/ruleset/backend/scenario, remaining FAIL/BLOCKED and the next concrete defect.
- Report `verified/applicable` only for comparable behaviors actually executed. For P7, distinguish measured live-DPS / required-DPS (capped at 100%) from the separate illustrative `E(c)` 80/20 effort heuristic. A small stochastic sample is preliminary; sample count is not gate coverage.

Merge owns Forever-main integration and all official M1 runs/ledger writes. Work agents may run justified branch diagnostics **without** `--record-pass`, but must not post `/m1-run`, change `M1_PASSES.tsv` or publish official counts. A concrete request for a new M1 run goes as one `M1-DISPATCH-REQUEST` comment on your existing owned issue; use the format and ACK workflow in [MERGE](MERGE.md). Do not create a second queue issue.

At cycle end, consider one useful asynchronous regression/acceptance diagnostic on your owned code and hand off its run URL/results target when justified. Do not launch expensive acceptance just to create activity.
