# WF446 compact full snapshot (packaging only)

This package is a **cleaned copy** of `WF446_RECONSTRUCTED_FULL_P2_RED_WIP_2026-10-16.zip`, not a new accepted simulator version.
Original input SHA256: `6b69bc2cec5171a49d4fc234cffeb91de88d7e336303bb1d3b3200891ed723d4`

Core preserved byte-for-byte: **source, tests, tools, scripts, databases and source captures, existing state**.
Evidence directly named in code/tests/tools and current WF443–446 lineage is also retained.
Historical handovers, superseded plans, generated run reports and non-referenced evidence are
**not shipped in the runtime ZIP**; they are in `WF446_HISTORICAL_EVIDENCE_ARCHIVE_2026-10-16.zip`. No history was destroyed.

**Protected process:** `PROCESS_WOW_FOREVER_v2_2026-10-15.md`;
**approved plan:** `OVERALL_PLAN_WOW_FOREVER_v5_APPROVED_2026-10-15.md`.
The original `START_HERE.md` is outdated and was archived. This README replaces it as
the packaging entry point without changing either protected authority document.
WF446 is **P2 RED / WIP**. This repackaging does not turn 0/148 into 1/148.

Smoke: `python -m pytest -q tests/test_wf446_joint_spell_crit_haste_tdd.py`
Full suite: `python -m pytest -q` (not claimed passing in this package).

`COMPACT_INVENTORY.json` contains all retained hashes and archived file paths.
