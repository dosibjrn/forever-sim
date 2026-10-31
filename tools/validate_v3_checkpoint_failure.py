#!/usr/bin/env python3
from __future__ import annotations
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
raise SystemExit(subprocess.call([sys.executable,'-m','pytest','-q','-r','s','tests/test_v3_checkpoint_failure_semantics_v0114821.py'],cwd=ROOT))
