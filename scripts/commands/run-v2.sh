#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

MODE="both"
EXTRA=()
OPEN_PATH="/fast"
EXPECT_RULESET=0
for arg in "$@"; do
  if [[ "$EXPECT_RULESET" -eq 1 ]]; then
    [[ "$arg" == "forever" ]] && OPEN_PATH="/decisions"
    EXPECT_RULESET=0
  fi
  case "$arg" in
    --optimize-only) MODE="optimize" ;;
    --listener-only|--listen) MODE="listener" ;;
    --ruleset) EXPECT_RULESET=1; EXTRA+=("$arg") ;;
    --ruleset=forever) OPEN_PATH="/decisions"; EXTRA+=("$arg") ;;
    *) EXTRA+=("$arg") ;;
  esac
done

if [[ "$MODE" == "optimize" ]]; then
  exec python -m src.v2.runner "${EXTRA[@]}"
elif [[ "$MODE" == "listener" ]]; then
  exec env MSYS2_ARG_CONV_EXCL='*' python -m src.listener --open-path "$OPEN_PATH" "${EXTRA[@]}"
else
  python -m src.v2.runner "${EXTRA[@]}" &
  OPT_PID=$!
  trap 'kill "$OPT_PID" 2>/dev/null || true' EXIT INT TERM
  env MSYS2_ARG_CONV_EXCL='*' python -m src.listener --open-path "$OPEN_PATH" "${EXTRA[@]}"
  wait "$OPT_PID"
fi
