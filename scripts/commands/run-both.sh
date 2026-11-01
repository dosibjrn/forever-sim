#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

SCHOOL="all"
FROST=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --school)
      [[ $# -ge 2 ]] || { echo "--school requires all|frost|fire|arcane" >&2; exit 2; }
      SCHOOL="$2"; shift 2 ;;
    --school=*) SCHOOL="${1#--school=}"; shift ;;
    --frost) FROST=1; shift ;;
    *) echo "run-both.sh: unsupported argument: $1 (supported: --frost, --school)" >&2; exit 2 ;;
  esac
done
if [[ "$FROST" -eq 1 ]]; then
  [[ "$SCHOOL" == "all" || "$SCHOOL" == "frost" ]] || { echo "--frost conflicts with --school $SCHOOL" >&2; exit 2; }
  SCHOOL="frost"
fi
case "$SCHOOL" in all|frost|fire|arcane) ;; *) echo "invalid --school: $SCHOOL" >&2; exit 2;; esac

# On Windows/Git Bash use the PowerShell launcher to avoid MSYS path/handle issues.
if [[ -n "${MSYSTEM:-}" ]] && command -v powershell.exe >/dev/null 2>&1; then
  PS1_WIN="$(cygpath -w "$PWD/scripts/commands/run-both.ps1")"
  if [[ "$SCHOOL" == "frost" ]]; then
    exec env MSYS2_ARG_CONV_EXCL='*' powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_WIN" -Frost
  else
    exec env MSYS2_ARG_CONV_EXCL='*' powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_WIN" -School "$SCHOOL"
  fi
fi

# One listener, then Fast proposals first, then the normal persistent MC search.
MSYS2_ARG_CONV_EXCL='*' python -m src.listener --open-path /fast &
LISTENER_PID=$!
cleanup(){ kill "$LISTENER_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "[both] phase 1/2: Fast analytic proposal search (school=$SCHOOL)" >&2
python -m src.v2.runner --view smooth --workers 1 --school "$SCHOOL"

echo "[both] phase 2/2: MC search (school=$SCHOOL; native candidates + Fast challengers/priors)" >&2
./run.sh --optimize-only --school "$SCHOOL"
wait "$LISTENER_PID"
