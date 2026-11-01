#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

MODE="both"
EXTRA=()
HAS_VIEW=0
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
    --view|--view=*) HAS_VIEW=1; EXTRA+=("$arg") ;;
    *) EXTRA+=("$arg") ;;
  esac
done
if [[ "$MODE" != "listener" && "$HAS_VIEW" -eq 0 ]]; then EXTRA=(--view smooth "${EXTRA[@]}"); fi

# Git Bash/MSYS rewrites an argument beginning with / into a Windows path
# (e.g. /fast -> C:/Program Files/Git/fast). Disable that conversion only
# for the listener invocation.
run_fast_listener() {
  MSYS2_ARG_CONV_EXCL='*' python -m src.listener --open-path "$OPEN_PATH" "$@"
}

if [[ "$MODE" == "optimize" ]]; then
  exec python -m src.v2.runner "${EXTRA[@]}"
elif [[ "$MODE" == "listener" ]]; then
  exec env MSYS2_ARG_CONV_EXCL='*' python -m src.listener --open-path "$OPEN_PATH" "${EXTRA[@]}"
else
  # Listener is the background process; keep the optimizer attached to the
  # terminal.  This avoids Windows multiprocessing handle-duplication failures
  # that can occur when a Python parent process is itself backgrounded by MSYS.
  run_fast_listener &
  LISTENER_PID=$!
  cleanup(){ kill "$LISTENER_PID" 2>/dev/null || true; }
  trap cleanup EXIT INT TERM
  python -m src.v2.runner "${EXTRA[@]}"
  echo "[fast] optimization complete; listener remains open (Ctrl-C to stop)." >&2
  wait "$LISTENER_PID"
fi
