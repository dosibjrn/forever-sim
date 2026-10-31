# Generic class-adapter regression suite

This directory groups 15 existing generic-engine tests covering:

- Druid / Bear routes, profiles and policy choices
- Hunter pet and cross-class actor integration
- Mage generic decisions and source-faithful scoring
- Priest, Rogue, Shaman, Warlock and Warrior adapters

Every original test module was moved **byte-for-byte**. Some tests inspect
`src/game/runtime/simulator.py`, `src/game/policy.py` or a SQLite catalogue
through repository-root-relative paths. Run from the repository root as before.

```bash
python -m pytest -q tests/generic/classes
```

These tests remain part of normal pytest collection. The Actions workflow
checks structure and collection only; it does not certify the game's
mechanics or P1–P7 acceptance, and skipped jobs do not imply PASS.
