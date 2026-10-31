# Historical WF evidence — not the current certification ledger

This folder stores historical raw simulations, source observations, run logs, and prior acceptance attempts (e.g. `evidence/wf430/`). Treat each record according to its own original context and executable revision.

**Current accepted gate and build status:** [root README](../README.md) → [curated docs/evidence](../docs/evidence/README.md). A historical file named `PASS` is not sufficient to certify a current checkpoint.

**Compatibility warning:** Some actual code reads this tree by fixed relative path; for example `src/game/checkpoint_acceptance_status.py` reads `evidence/wf360`, `evidence/wf365`, and `evidence/wf367`. Do not rename or move this tree merely to consolidate folder names. Require targeted consumer and regression checks first.

[Repository structure and migration plan](../docs/REPOSITORY_STRUCTURE.md).
