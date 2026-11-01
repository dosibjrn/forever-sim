# Paladin mechanics tests

Ten normally collected WoW Forever Paladin regression modules were moved
**byte-for-byte** from the old flat `tests/` directory.

They exercise spell rank/modifier semantics, source coefficients and provenance,
talent/gearing choices, role item candidates, Fury absorption, SQLite runtime
selection, and weapon stat budgets.

Source snapshots use the production catalogue's absolute `FIXTURE_ROOT`.
These tests do not depend on their own `__file__` location or imports from
other `tests.*` modules.

Run all Paladin tests:

```bash
python -m pytest -q tests/mechanics/paladin
```

This folder participates in default pytest discovery. Slow `tests/release/`
remains opt-in. The separate workflow checks structure, collection, and a
narrow set of actual regressions; it does not certify any full P1–P7 checkpoint.
