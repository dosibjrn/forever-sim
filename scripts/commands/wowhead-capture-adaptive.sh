#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
PROFILE="${WOWHEAD_CHROME_PROFILE:-$PWD/.wowhead-chrome-profile}"
exec python tools/capture_wowhead_adaptive.py \
  --channel chrome \
  --user-data-dir "$PROFILE" \
  "$@"
