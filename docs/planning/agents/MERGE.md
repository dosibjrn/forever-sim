# Merge — integration, affected-gate verification and sole M1 writer

Read [COMMON](COMMON.md), this file, current [WORK_PRIORITY](../WORK_PRIORITY.md), and only the relevant PRs, issues, PROCESS and gate sections. Read [P7 notes](P7.md) when a merged PR or dispatch request affects P7.

## Authority

Merge alone owns Forever PR integration, official affected-gate dispatch and the `docs/planning/M1_PASSES.tsv` ledger. Preserve previously accepted PASSes unless a material incompatibility is proven. A safe, focused, tested production improvement is mergeable even when its gate remains FAIL/BLOCKED; a full gate PASS or guaranteed M1 increase is not a merge prerequisite.

## Mandatory post-merge PR-to-gate handling

For every newly integrated production-code PR:

1. Read its `M1 affected gates:` line and sanity-check it against the real diff.
2. Deduplicate the concrete applicable checkpoint×gate pairs.
3. Choose exactly one outcome for each pair:
   - **Changed executable behavior:** after merge, dispatch `/m1-run` for the affected exact gate(s). Use the existing production runner on fresh `main`; it reports PASS/FAIL/BLOCKED and records only qualifying PASS/PARTIAL.
   - **Previously certified, unchanged behavior:** no rerun and no status mutation. Invalidate only on proven material incompatibility.
   - **No new executable behavior / `M1 affected gates: none`:** no dispatch.
4. Batch affected gates into one command on the most recently merged PR, up to twelve exact tokens. Do not scan unchanged gates or launch unrelated heavy acceptance.

Merging code and checking its declared gate impact are one integration responsibility. Do not manually grade evidence, compute percentages, copy JSON into TSV, create a ledger PR or demand a full gate PASS before merging a safe incremental improvement. A bounded probe can produce a real PARTIAL but is not a full P7 PASS. Let `wf_gate.py` and `m1_progress.py` decide and record the result.

The existing [m1-on-demand-record workflow](../../../.github/workflows/m1-on-demand-record.yml) is the recorder. The owner-authenticated `/m1-run` comment on an already merged PR launches against fresh `main`. P5's bounded probe may run without `--heavy` (currently capped at 20 seconds); a full P5 300-second acceptance and full P6/P7 acceptance require explicit `--heavy` and must be justified. Do not repeat unchanged 1,000-fight/300-second work.

## Cross-cycle M1 dispatch requests

Work1, Work2 or Prio may need a new real M1 measurement for merged production code or unrecorded historical evidence. They leave **one** top-level comment on their existing owned open issue; they do not create another queue issue, edit the TSV, start the recorder or post `/m1-run`.

Request format:

```text
M1-DISPATCH-REQUEST
Targets: druid:60:balance:P7.1
Mode: heavy
Reason: full 1000-stochastic native+2D acceptance has not been executed by M1; previous 3-fight diagnostic is not acceptance
Evidence: https://github.com/dosibjrn/forever-sim/actions/runs/<existing-run>
Production: merged main; required PR(s) merged, or list which PR must merge first
```

- Targets are one to twelve exact `class:level:spec:gate` tokens. `Mode: light` is the normal bounded production test; `Mode: heavy` is only for justified P6/P7 final acceptance. No wildcards or known unchanged PASSes. Say whether a missing ledger row is untested or known FAIL.
- Search open issue comments for the exact marker `M1-DISPATCH-REQUEST` every Merge cycle (for example, `repo:dosibjrn/forever-sim is:issue is:open in:comments "M1-DISPATCH-REQUEST"`). Fetch matching comments in full. If search indexing lags, inspect current owner issues linked from WORK_PRIORITY; do not rely on historical issue numbers.
- Verify the required code is on fresh `main`, inspect the exact gate, ledger and current/in-flight M1 run, discard superseded/duplicate requests, and choose a minimal defensible batch. A plausible real improvement is eligible; guaranteed PASS is not required.
- ACK every request on the **same owner issue** with `M1-DISPATCH-ACK`, the original request comment URL/ID, each target and one of `launched <Actions URL>`, `already covered <Actions URL>`, `deferred: <specific dependency>` or `rejected: <reason>`.
- When a run completes, reply on that issue with its actual PASS/FAIL/BLOCKED, ledger effect and next actionable failure (or pending if still running). On later cycles, find requests without ACK and launched ACKs without verdict; never silently abandon, relaunch or infer PASS from a green workflow.

This request channel supplements, and never replaces, mandatory post-merge `M1 affected gates` dispatch. The script is the scoring authority: `wf_gate.py` returns the verdict and `m1_progress.py` retains only defensible PASS/PARTIAL and computes the scoreboard. A historical PARTIAL is a monotonic best-observed diagnostic, not proof that a newly regressed live run is healthy.
