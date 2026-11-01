#!/usr/bin/env python3
"""V1 rendered browser/operator workflow acceptance gate.

Runs the real listener UI against the real listener HTTP handler, optimizer HTTP
service and durable SQLite store. Chromium loopback navigation may be blocked by
managed execution environments; the test therefore routes browser API requests
through Playwright to the live listener socket without mocking API responses.
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main()->int:
    env=dict(os.environ)
    env['REQUIRE_CHROMIUM']='1'
    cmd=[sys.executable,'-m','pytest','-q','-r','s','tests/test_v1_browser_workflow_v0114819.py']
    return subprocess.call(cmd,cwd=ROOT,env=env)

if __name__=='__main__':
    raise SystemExit(main())
