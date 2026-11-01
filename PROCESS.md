# WoW Forever — PROCESS v2.10 (approved, reorganized)

**Scope:** This file governs HOW the project is developed. [OVERALL_PLAN.md](OVERALL_PLAN.md) v5 defines WHAT and the DONE DONE target. The detailed approved gate predicates now live in [docs/gates/](docs/gates/README.md). This is a **structural split of v2.10**, not a gate relaxation or a new approval of altered product goals. Git history preserves the former consolidated PROCESS and its v2.3–v2.10 change records.

## Authority and change control

- Explicit owner instructions take precedence. Approved PROCESS governs implementation/acceptance; approved OVERALL PLAN governs product goals; [WORK_PRIORITY](docs/planning/WORK_PRIORITY.md), issues and work plans may be freely reprioritized within those constraints.
- **Only an explicit owner instruction/approval may substantively change PROCESS, its linked gate criteria, or OVERALL PLAN.** Update canonical files via reviewed Git commits; rely on Git history, not numbered sibling documents or repeated approval logs.
- Any conflicting lower-level instructions lose. Do not silently change acceptance thresholds, source legality, backend rules, or the 148-checkpoint scope.
- **Known unresolved conflict:** OVERALL_PLAN v5 still mentions the old Decisions P7 challenger; approved PROCESS v2.10 replaced it with MythicSim P7.1–P7.5. Disclose the discrepancy; do not silently rewrite OVERALL_PLAN.

## Acceptance contract

- The scoreboard has **148 checkpoints**: nine unrestricted classes × four levels (20, 30, 40, 60) = 36; Druid four profiles × four levels = 16; eight other classes × three profiles × four levels = 96. There is no L50 checkpoint.
- A checkpoint counts only when **P1–P6 and P7.1–P7.5** pass with current, compatible pinned source, ruleset and production engine evidence. P1–P6 assess continuous **100-mob leveling**; P7 assesses a separate pinned MythicSim DPS-reference encounter. Never splice incompatible proofs.
- **No additional implicit gates.** Tests, metadata, compilation, static manifests, native-only diagnostics, partial evidence and green CI are not a substitute for the actual stated predicate. Report PASS/FAIL/BLOCKED truthfully. Preserve previously accepted owner-specific historical decisions and disclose their limits.
- Exact requirements and runtime authority:
  - [Common acceptance, engines, sources and transition](docs/gates/COMMON.md)
  - [P1 abilities and P2 talents](docs/gates/P1-P2.md)
  - [P3 gear smoke](docs/gates/P3.md)
  - [P4–P6 independent search and 100-mob comparison](docs/gates/P4-P6.md)
  - [P7.1–P7.5 MythicSim reference and live integration](docs/gates/P7.md)
- Stable CLI: `python tools/wf_gate.py --class <class> --level <level> --gate P1` (or P2–P7.5). Live execution is authoritative; see [runtime contract](docs/gates/RUNTIME_AUTHORITY.md).

## Delivery and evidence

1. Prioritize the smallest **material critical-path improvement** toward 148/148, not documents, run counts, checklists or status theater. Use the mutable work priority and actionable issues; parallelize independent code work.
2. Develop in an isolated branch. For a new/repaired gate, show **RED → GREEN → REFACTOR** against the *same* behavioral predicate; refactor shared mechanisms rather than implementing per-class exceptions, then rerun relevant cross-class/level regressions.
3. A passing **formal gate** needs tested production behavior and reproducible evidence: pinned source/ruleset/runtime/config, exact input, measured output, relevant candidates, comparisons and causal traces. Commit evidence under `docs/evidence/` and merge the individually accepted gate to `main`; do not mix failed/pending gates into a PASS claim or inflate 0/148. Previously valid unchanged evidence may be reused when hashes match.
4. Safe engineering changes can be merged independently after relevant tests, **without claiming a formal gate PASS**. Record actionable blockers instead of fabricating evidence or adding verification bureaucracy. Prefer fast focused checks; run expensive 30s/300s/100-mob proofs only for real affected acceptance.
5. Use sourced Forever data and justified Classic defaults where Forever is unknown. Implement and test observable mechanics; don't require live-server measurement or speculative semantic-certification rounds. No invented game values, no hidden source completeness gates; see [common source rules](docs/gates/COMMON.md).

The former consolidated v2.10 document, including its historical approvals, remains in Git history. Its **active gate predicates** were separated into the linked files above, not rescinded.
