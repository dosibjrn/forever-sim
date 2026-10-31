#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
exec python tools/capture_forever_abilities_sqlite.py \
  --channel chrome \
  --user-data-dir "${WOWHEAD_CHROME_PROFILE:-$PWD/.wowhead-chrome-profile}" \
  "$@"
