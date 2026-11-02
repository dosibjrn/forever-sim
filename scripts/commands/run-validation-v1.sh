#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export REQUIRE_CHROMIUM=1
exec python -m pytest -q -r s tests/test_v1_browser_workflow_v0114819.py
