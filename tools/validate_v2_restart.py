#!/usr/bin/env python3
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main()->int:
    env=dict(os.environ); env['REQUIRE_CHROMIUM']='1'
    return subprocess.call([sys.executable,'-m','pytest','-q','-r','s','tests/test_v2_restart_persistence_v0114820.py'],cwd=ROOT,env=env)
if __name__=='__main__': raise SystemExit(main())
