#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REQUIRE_CHROMIUM=1 python -m pytest -q tests/test_listener_rendered_contract_v01140.py
