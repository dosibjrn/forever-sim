# Generic combat runtime test suite

Existing source-backed runtime test modules are grouped by behavior.
Coverage includes action readiness, periodic effects, multi-action caster
policy, event scheduling, autoattacks, energy/rage/combo points, healing and
recovery, mitigation, multi-actor combat, timed summons, totems, and talents.

The tests import from `src.*` and have **no test-file-relative fixtures**.
Several use `Path("src/game/...")` to inspect production source; these are
intentionally repository-working-directory-relative and require invoking
pytest from the repository root, as before.

```bash
python -m pytest -q tests/generic/runtime
```

Default `pytest -q` still collects this group. The slow `tests/release/`
suite remains opt-in. The private layout-only Actions workflow was not
migrated; no layout smoke is evidence of P1–P7 checkpoint certification.
