# Prio — minimize remaining work to genuine M1 progress

Read [COMMON](COMMON.md), this file, the latest [WORK_PRIORITY](../WORK_PRIORITY.md), actual Merge-owned M1 ledger and relevant source/PR/Actions. Only read a gate contract when that gate is under consideration.

## Decision loop (every cycle)

1. **Choose the largest credible *total* M1 improvement per remaining work.** Compare current genuine PASS/PARTIAL headroom, likelihood of a real outcome, implementation/verification/compute cost, and **demonstrated reuse across other active gates**. Reusable native execution/optimizer fixes may outrank cheap one-off P3 measurements; do not automatically favor the first unsampled gate. M1's existing 1,332 denominator and 80/20 partial diagnostic remain unchanged; estimates are unearned, not new metrics.
2. **Reject sunk-cost and proof churn.** A changed-code real paid run that leaves a gate's comparable M1 unchanged ends that probe lane unless it exposes a **new reproducible causal defect** with a credible fix. Do not repeat unchanged paid searches, speculative class first contacts without an executable source/native path, irrelevant stat-weight positivity witnesses, P1/P2/GameIR work or duplicate MythicSim rules verification. Already saturated partials have no additional fractional headroom. Preserve live independent Work1/Work2 work unless its expected payoff has genuinely changed.
3. **Queue the smallest executable next action** in the current [WORK_PRIORITY](../WORK_PRIORITY.md): real checkpoint/gate (or one shared multi-gate capability), latest source-linked baseline, specific production change, smallest real verification, owner, and causal route to M1. Reuse the existing issue/PR; create an issue only for genuinely new work. Work1 owns the highest-value implementation, Work2 the best independent implementation, Merge owns real recording and integration, Clean owns dead-code retirement.

**Write the queue only when task, owner, priority or next executable action actually changes.** Do not commit a fresh queue SHA, CI recap or historical timeline each agent cycle. Durable work detail/history belongs on the owned issue/PR. When the queue is still correct, continue the next independent actionable assignment; do not manufacture a documentation update as work.

No invented PASS, shadow scoreboard, extra gate, class-specific rules fork, or Prio ledger write. The approved [PROCESS](../../../PROCESS.md) and [gate contracts](../../gates/README.md) decide acceptance, not Prio estimates.
