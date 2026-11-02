#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export REQUIRE_CHROMIUM=1
exec python -m pytest -q -r s tests/test_v2_restart_persistence_v0114820.py
