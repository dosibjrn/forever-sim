from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_capture_script_direct_execution_can_import_repo_src():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    proc = subprocess.run(
        [sys.executable, str(root / "tools" / "capture_wowhead.py"), "--help"],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage:" in proc.stdout.lower()
