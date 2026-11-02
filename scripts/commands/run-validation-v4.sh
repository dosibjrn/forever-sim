#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python -m pytest -q tests/test_v4_concurrency_writer_isolation_v0114823.py
