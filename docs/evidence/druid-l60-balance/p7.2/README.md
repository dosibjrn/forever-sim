# Druid L60 Balance — P7.2 WF641 owner acceptance

**Historical WF641 owner-accepted P7.2 outcome (2026-10-29), under the specifically requested 1% P7.2 tolerance.** This is a decision record, not a technical gate certification; tolerance governance is intentionally outside this worker PR.

## Frozen search evidence
- Pinned external MythicSim reference: **728.1936126415858 DPS**.
- Allowed threshold: **0.99 × reference = 720.91167651517 DPS**.
- Actual WF641 independent 2,000-fight stochastic holdout: **728.066961377931 DPS**, sample SD **43.964445679560335 DPS**.
- Holdout exceeds tolerance floor by **7.15528486276 DPS**; point estimate is **0.0174% below reference**.
- Historical search: **300.262573476 wall seconds** (**exceeds a strict 300.000s cap; NOT a compliant cold-search timing result**), **11,861 unique paid Rust candidates** (100-fight screening), native Rust pinned engine `666fe17a42682068a3c8497d88d5fa3732cbdfb9`.
- Winning order of the ten saved APL actions: `[3,0,4,5,8,1,7,6,9,2]`. The saved reference APL was excluded from search initialization; it was used separately for baseline regression.
- Native 10,000-fight regression: **728.1936126415858 DPS**, exact reproduction of external reference.
- Original search runner copied from commit `f77820f37223df854514464a3ad8220bd2adbddb` to `integrations/mythicsim-rust/rotation_search.py`.
- Previous raw run report and frozen request were produced in local WF641/WF642 artifacts, **not committed** to this repo. These summaries are **not replacements** for full raw causal logs and source-configuration witnesses.

## Acceptance vs evidence
The owner explicitly accepts WF641 as **P7.2 PASS** using the 1% reference-DPS tolerance. This records the management acceptance, **not a fabricated technical trace**. Remaining technical exceptions: WF641 was native Rust-only (no proved interactive gsim 2D ↔ Rust causal trace); optimizer changed priority order but not arbitrary new source-legal conditions/actions; no self-contained raw source inputs/logs in this Git directory. These gaps must remain visible to the integration agent; do not assert that all technical gate subconditions were run.

P7.3 may proceed as a separate work branch while integration agent reviews this PR. No P7.3 changes are bundled here.

## Reviewer follow-up
- PROCESS policy edits were reverted in this branch. Governance and the precise P7.2/P7.3/P7.4 exception require a separate decision/PR; P7.1 and P7.5 remain unchanged.
- The updated runner now imposes one end-to-end deadline across screening, subprocess execution, holdout and report writing. This does **not** retroactively validate WF641's 300.2626-second run.
- A mocked native-CLI regression suite and GitHub Actions check exercise the search runner. This is software regression coverage, **not** proof of a reproduced native Rust search.
- The frozen source request, original full paid candidate output, and original native holdout report have **not** been recovered from the historical worker run and therefore cannot be claimed as committed evidence. New runs should commit or attach them with sufficient reproduction metadata.
