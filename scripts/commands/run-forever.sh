#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
START_LEVEL=11
END_LEVEL=60
WORKERS=
NO_LISTENER=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --start-level) START_LEVEL="$2"; shift 2;;
    --end-level) END_LEVEL="$2"; shift 2;;
    --workers) WORKERS="$2"; shift 2;;
    --no-listener) NO_LISTENER=1; shift;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
COMMON=(--ruleset forever --start-level "$START_LEVEL" --end-level "$END_LEVEL" --view smooth)
[[ -n "$WORKERS" ]] && COMMON+=(--workers "$WORKERS")
for CLS in mage paladin druid; do
  echo "[forever] running $CLS L$START_LEVEL->$END_LEVEL" >&2
  python -m src.v2.runner "${COMMON[@]}" --class "$CLS"
done
if [[ "$NO_LISTENER" -eq 0 ]]; then
  exec env MSYS2_ARG_CONV_EXCL='*' python -m src.listener --open-path /decisions
fi
