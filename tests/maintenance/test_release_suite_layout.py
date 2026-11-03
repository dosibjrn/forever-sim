"""Test that the slow release smoke remains deliberately opt-in after relocation."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_release_suite_paths_and_entry_points():
    assert not (ROOT / "release_tests").exists()
    for name in ("test_forever_release_gate.py", "test_mc_precision_ladder.py"):
        assert (ROOT / "tests" / "release" / name).is_file()
    ini = (ROOT / "pytest.ini").read_text()
    assert "testpaths = tests" in ini
    assert "norecursedirs = release" in ini
    shell = (ROOT / "scripts/commands/run-release-smoke.sh").read_text()
    powershell = (ROOT / "scripts/commands/run-release-smoke.ps1").read_text()
    assert "exec python -m pytest -q tests/release" in shell
    assert "python -m pytest -q tests/release" in powershell


def test_default_collection_excludes_release_but_explicit_path_collects(tmp_path):
    """Use an isolated tiny suite: no heavy simulator import or actual release run."""
    (tmp_path / "tests/release").mkdir(parents=True)
    (tmp_path / "pytest.ini").write_text((ROOT / "pytest.ini").read_text())
    (tmp_path / "tests/test_fast.py").write_text("def test_fast(): assert True\n")
    (tmp_path / "tests/release/test_slow.py").write_text(
        "def test_slow(): assert True\n"
    )
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    def collect(*args):
        p = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", *args],
            cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30
        )
        assert p.returncode == 0, p.stdout + p.stderr
        return p.stdout
    default = collect()
    assert "test_fast.py::test_fast" in default
    assert "test_slow.py::test_slow" not in default
    explicit = collect("tests/release")
    assert "test_slow.py::test_slow" in explicit
    assert "test_fast.py::test_fast" not in explicit


def test_historical_overlay_zip_packagers_retired_but_active_evidence_retained():
    """Legacy ZIP handovers are retired; retained P4-P6 evidence remains available."""
    for name in ("wf360_build_release.py", "wf361_build_release.py", "wf362_build_release.py"):
        assert not (ROOT / "tools" / name).exists()
    for relative in (
        "evidence/wf360/WF360_L30_P4_30S.json",
        "evidence/wf360/WF360_L30_P5_300S.json",
        "evidence/wf360/WF360_L30_P6_FRESH_100MOB.json",
        "evidence/wf361/WF361_WARRIOR_L30_P1_CERTIFICATE.json",
    ):
        assert (ROOT / relative).is_file(), relative
