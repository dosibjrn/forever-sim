# Mage mechanics and selection regression tests

Normally collected cross-engine Mage tests for:
- Classic Ice Barrier and Frostbite/Shatter interactions
- Forever Ice Lance selection across specs and levels
- Real frozen-state Ice Lance behavior
- Forever periodic spell critical strikes

The initial seven modules and another sixteen Mage modules were moved
**without changing their source bytes**. The added modules cover Frost,
Arcane, Fire, gear, school tuning, runtime models, search fidelity and
listener decision output. None depends on test-file-relative fixture paths or
imports another `tests.*` module. The engine modularity regression reads the
**production engine's** `engine.__file__` (not the test file's own location).

The existing layout smoke and the added extended-layout contract verify the
two incremental migration batches. Both are part of ordinary pytest discovery.

Run the group:

```bash
python -m pytest -q tests/mechanics/mage
```

It remains part of regular `python -m pytest -q` discovery. Unlike
`tests/release/`, it is not excluded by `norecursedirs`.

The existing Mage-group workflow checks collection and the file-layout contracts.
Collection PASS alone **does not** prove all mechanics tests PASS, and this
migration is not checkpoint certification.
