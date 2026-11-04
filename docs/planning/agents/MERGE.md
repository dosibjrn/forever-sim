# Merge — integration, affected-gate verification and sole M1 writer

Read [COMMON](COMMON.md), this file, current [WORK_PRIORITY](../WORK_PRIORITY.md), and only the relevant PRs, issues, PROCESS and gate sections. Read [P7 notes](P7.md) when a merged PR or dispatch request affects P7.

## Authority

Merge alone owns Forever PR integration, official affected-gate dispatch and the `docs/planning/M1_PASSES.tsv` ledger. Preserve previously accepted PASSes unless a material incompatibility is proven. A safe, focused, tested production improvement is mergeable even when its gate remains FAIL/BLOCKED; a full gate PASS or guaranteed M1 increase is not a merge prerequisite.

## Mandatory post-merge PR-to-gate handling

For every newly integrated production-code PR:

1. Read its `M1 affected gates:` line and sanity-check it against the real diff.
2. Deduplicate the concrete applicable checkpoint×gate pairs.
3. Choose exactly one outcome for each pair:
   - **Changed executable behavior:** use a real changed-code no-record result or credible first executable native path to decide whether one official `/m1-run` can add eligible M1 evidence. Dispatch once on fresh `main` when justified; otherwise record the exact no-gain/blocked reason and do not repeat unchanged work. A proven material regression of prior compatible PASS is handled separately.
   - **Previously certified, unchanged behavior:** no rerun and no status mutation. Invalidate only on proven material incompatibility.
   - **No new executable behavior / `M1 affected gates: none`:** no dispatch.
4. Batch affected gates into one command on the most recently merged PR, up to twelve exact tokens. Do not scan unchanged gates or launch unrelated heavy acceptance.

Merging code and checking its declared gate impact are one integration responsibility. Do not manually grade evidence, compute percentages, copy JSON into TSV, create a ledger PR or demand a full gate PASS before merging a safe incremental improvement. A bounded probe can produce a real PARTIAL but is not a full P7 PASS. Let `wf_gate.py` and `m1_progress.py` decide and record the result.

The existing [m1-on-demand-record workflow](../../../.github/workflows/m1-on-demand-record.yml) is the recorder. The owner-authenticated `/m1-run` comment on an already merged PR launches against fresh `main`. P5's bounded probe may run without `--heavy`; full P5/P6, P7.1 and P7.5 acceptance can require justified heavy runs. P7.2–P7.4 are native-paid changed-axis diagnostics, not mandatory 300s/1,000-fight holdouts. Do not repeat unchanged 1,000-fight/300-second work. The workflow runs the existing `wf_gate.py --record-progress` and `m1_progress.py`; qualifying PASS or FAIL/PARTIAL is recorded directly in the sole TSV, while BLOCKED, bogus denominators and nonexecuted probes do not count. It recomputes the scoreboard and writes the TSV directly to `main` only when it changed, using a matching blob-SHA concurrency check. On a rejected concurrent write, retry from fresh `main`; never overwrite another writer. No secondary JSON register, ledger PR or hand-authored totals.

## Cross-cycle M1 dispatch requests

Work1, Work2 or Prio may need a new real M1 measurement for merged production code or unrecorded historical evidence. They leave **one** top-level comment on their existing owned open issue; they do not create another queue issue, edit the TSV, start the recorder or post `/m1-run`.

Request format:

```text
M1-DISPATCH-REQUEST
Targets: rogue:20:unrestricted:P3
Mode: light
Reason: changed native-scored legal gear production has an eligible new result; linked no-record receipt shows actual improvement
Evidence: https://github.com/dosibjrn/forever-sim/actions/runs/<existing-run>
Production: merged main; required PR(s) merged, or list which PR must merge first
```

- Targets are one to twelve exact `class:level:spec:gate` tokens. `Mode: light` is the normal bounded production test; `Mode: heavy` is only for justified expensive final acceptance. No wildcards or known unchanged PASSes. Say whether a missing ledger row is untested or known FAIL.
- Search open issue comments for the exact marker `M1-DISPATCH-REQUEST` every Merge cycle (for example, `repo:dosibjrn/forever-sim is:issue is:open in:comments "M1-DISPATCH-REQUEST"`). Fetch matching comments in full. If search indexing lags, inspect current owner issues linked from WORK_PRIORITY; do not rely on historical issue numbers.
- Verify the required code is on fresh `main`, inspect the exact gate, ledger and current/in-flight M1 run, discard superseded/duplicate requests, and choose a minimal defensible batch. A plausible real improvement is eligible; guaranteed PASS is not required.
- ACK every request on the **same owner issue** with `M1-DISPATCH-ACK`, the original request comment URL/ID, each target and one of `launched <Actions URL>`, `already covered <Actions URL>`, `deferred: <specific dependency>` or `rejected: <reason>`.
- When a run completes, reply on that issue with its actual PASS/FAIL/BLOCKED, ledger effect and next actionable failure (or pending if still running). On later cycles, find requests without ACK and launched ACKs without verdict; never silently abandon, relaunch or infer PASS from a green workflow.

This request channel supplements post-merge impact triage; do not dispatch unchanged or known no-gain gates merely because a PR mentions them. The script is the scoring authority: `wf_gate.py` returns the verdict and `m1_progress.py` retains only defensible PASS/PARTIAL and computes the scoreboard. A historical PARTIAL is a monotonic best-observed diagnostic, not proof that a newly regressed live run is healthy.
