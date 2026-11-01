# Explicit release-only test suite

These tests were relocated from `release_tests/` without changing their test
functions or simulation logic. `test_mc_precision_ladder.py` runs real stochastic
search and is intentionally not part of normal fast test collection.

- **Normal:** `python -m pytest -q` (uses `testpaths = tests` and
  `norecursedirs = release`; skips this directory)
- **Release:** `python -m pytest -q tests/release`
- **Wrappers:** `bash scripts/commands/run-release-smoke.sh`, or
  `pwsh -File scripts/commands/run-release-smoke.ps1`

Explicit path selection overrides `norecursedirs`, including an individual
`tests/release/test_mc_precision_ladder.py` target. This behavior is asserted
by `tests/test_release_suite_layout.py` with an isolated pytest fixture.

Never interpret a passing collection-only test as passing real release smoke.
