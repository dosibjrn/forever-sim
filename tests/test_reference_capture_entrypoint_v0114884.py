from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path


def test_talentsforever_capture_direct_entrypoint_has_no_repo_import_dependency():
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ); env.pop("PYTHONPATH", None)
    p = subprocess.run([sys.executable, str(root / "tools" / "capture_talentsforever_references.py"), "--help"],
                       cwd=root, env=env, capture_output=True, text=True, timeout=10)
    assert p.returncode == 0, p.stderr
    assert "TalentsForever" in p.stdout
    assert (root / "talentsforever-capture.sh").exists()
