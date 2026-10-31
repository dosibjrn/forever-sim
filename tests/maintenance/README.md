# Repository maintenance contracts

Normally collected tests for repository structure and command integration.

| File | Contract |
| --- | --- |
| `test_root_launcher_relocation.py` | Issue #14 phase 2A auxiliary shell/PowerShell launchers |
| `test_root_launcher_phase2b.py` | Issue #14 phase 2B alternate launchers |
| `test_release_suite_layout.py` | Explicit-only slow release suite collection |
| `test_sqlite_sidecar_git_hygiene.py` | Canonical SQLite DBs tracked; WAL/SHM sidecars ignored |
| `test_maintenance_layout.py` | This directory's paths, workflow wiring and test discovery contract |

All four moved tests have their original assertions; the only source change
in each is `ROOT = Path(__file__).resolve().parents[2]` (was `parents[1]`).
Normal `pytest -q` collects these; `tests/release/` remains explicitly opt-in.

Targeted test run:

```bash
python -m pytest -q tests/maintenance
```

Bash/PowerShell launcher syntax and stubbed command tests also run through the
root launcher workflow. `test_release_suite_layout.py` tests implicit versus
explicit pytest collection using an isolated temporary suite.

If a GitHub Actions job has no allocated runner/steps, it is NOT test PASS.
