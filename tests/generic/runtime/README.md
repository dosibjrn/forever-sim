# Generic combat runtime test suite

Twelve pre-existing test modules moved **byte-for-byte** from the flat test
directory. Coverage includes event scheduling, autoattacks, energy/rage/combo
points, healing/recovery and mitigation, multi-actor combat, timed summons,
totems, and talent modifiers.

The tests import from `src.*` and have **no test-file-relative fixtures**.
Several use `Path("src/game/...")` to inspect production source; these are
intentionally repository-working-directory-relative and require invoking
pytest from the repository root, as before.

```bash
python -m pytest -q tests/generic/runtime
```

Default `pytest -q` still collects this group. The slow `tests/release/`
suite remains opt-in. The workflow includes a structure check and a
collection-only pass; it does not establish P1–P7 checkpoint certification.
