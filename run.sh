#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

MODE="both"
EXTRA=()
DEFAULT_IMPORT_STATE_DIR="state-hide-2026-07-09-1907"
for arg in "$@"; do
  case "$arg" in
    --optimize-only) MODE="optimize" ;;
    --listener-only|--listen) MODE="listener" ;;
    continue) ;; # resume is always the default
    *) EXTRA+=("$arg") ;;
  esac
done

# Reuse historical optimizer discoveries as guidance-only priors.
# Keep optimizer-only defaults separate so --listener-only still accepts listener args.
OPT_EXTRA=("${EXTRA[@]}")
if [[ -d "$DEFAULT_IMPORT_STATE_DIR" ]]; then
  OPT_EXTRA=(--import-state-dir "$DEFAULT_IMPORT_STATE_DIR" "${OPT_EXTRA[@]}")
else
  echo "[run] optional old state not found: $DEFAULT_IMPORT_STATE_DIR (continuing without it)" >&2
fi

# Fast analytic proposals are guidance/challengers, never authority.  If a Fast
# run has published a bridge, offer its full paths to MC startup replay and also
# import its per-level talent/respec priors alongside native MC seeds.
FAST_BRIDGE_DIR="state/v2/mc_bridge"
if [[ "$MODE" != "listener" && -f "$FAST_BRIDGE_DIR/top_candidates.json" ]]; then
  python -m src.v2.mc_bridge --inject || echo "[run] warning: Fast->MC challenger injection failed; continuing" >&2
  OPT_EXTRA=(--import-state-dir "$FAST_BRIDGE_DIR" "${OPT_EXTRA[@]}")
fi

if [[ "$MODE" == "optimize" ]]; then
  exec python -m src.master_optimizer "${OPT_EXTRA[@]}"
elif [[ "$MODE" == "listener" ]]; then
  exec python -m src.listener "${EXTRA[@]}"
else
  python -m src.master_optimizer "${OPT_EXTRA[@]}" &
  OPT_PID=$!
  trap 'kill "$OPT_PID" 2>/dev/null || true' EXIT INT TERM
  python -m src.listener
  wait "$OPT_PID"
fi
