"""Tracked SQLite databases are source assets; transient SQLite journals are not."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)


def test_sqlite_sidecars_ignored_and_no_longer_tracked():
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("repository checkout with git metadata required")
    tracked = _git("ls-files", "--", "data/forever").stdout.splitlines()
    assert "data/forever/catalogue/items_2026-09-29.sqlite" in tracked
    assert not any(p.endswith(("-wal", "-shm", "-journal")) for p in tracked)
    for suffix in ("sqlite-wal", "sqlite-shm", "sqlite-journal",
                   "sqlite3-wal", "sqlite3-shm", "sqlite3-journal",
                   "db-wal", "db-shm", "db-journal"):
        transient = f"data/forever/catalogue/__test_sidecar__.{suffix}"
        result = _git("check-ignore", "-q", "--no-index", transient)
        assert result.returncode == 0, (transient, result.stderr)
    # Never ignore source catalogues merely because they are SQLite.
    source = _git("check-ignore", "-q", "--no-index",
                  "data/forever/catalogue/__test_catalogue__.sqlite")
    assert source.returncode == 1, source.stderr
