# Generic search, frontier and policy regression tests

Seven existing test modules were relocated **byte-for-byte** from the flat
`tests/` directory. They cover the generic talent/policy search kernel,
source-backed gear sensitivity and fixed-point selection, level-frontier
construction, mode-aware policy execution and cross-mode behavior.

The migrated tests import `src.*` modules directly; none imports another
`tests.*` module or uses `__file__` to locate its fixtures. Some use
`Path("src/...")` and `Path("data/...")` with the repository **working
directory**, exactly as before the move.

Run this group, from repository root:

```bash
python -m pytest -q tests/generic/search
```

The group remains included in ordinary `python -m pytest -q` discovery,
unlike the slow opt-in `tests/release/` suite.

No new GitHub Actions workflow is introduced: the existing workflows had
overly broad old `tests/test_generic_*.py` PR filters, which are narrowed in
this cleanup. A failure before any runner steps start is **not** a test FAIL
and neither test collection nor a maintenance move certifies P1–P7.
