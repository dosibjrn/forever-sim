#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
exec python -m pytest -q -r s tests/test_v3_checkpoint_failure_semantics_v0114821.py
