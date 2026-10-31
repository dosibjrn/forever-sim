#!/usr/bin/env bash
# Replay uniquely changed old private branches on the new public snapshot.
# Run only AFTER complete_public_migration.sh. This does NOT reproduce history.
# It skips old branches that have no distinct working-tree delta or cannot apply.
set -euo pipefail
OLD_URL="${OLD_URL:-https://github.com/dosibjrn/mage-level-sim.git}"
NEW_URL="${NEW_URL:-https://github.com/dosibjrn/forever-sim.git}"
REPORT="${REPORT:-$PWD/forever-sim-branch-migration-report.txt}"
git lfs version >/dev/null 2>&1 || { echo "git-lfs required" >&2; exit 2; }
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
echo "Cloning original with full branch history for merge-base diffs..."
git clone "$OLD_URL" "$work/old"
git clone "$NEW_URL" "$work/new"
test -f "$work/new/src/game/runtime/simulator.py" || {
 echo "Public main not complete. Run scripts/complete_public_migration.sh first." >&2; exit 3;
}
read -r -p "This will create additional PUBLIC branches. Type PUBLISH: " answer
[[ "$answer" == "PUBLISH" ]] || exit 4
printf 'Branch migration report — %s\n' "$(date -u +'%FT%TZ')" > "$REPORT"
ok=0; empty=0; existing=0; failed=0
while IFS= read -r branch; do
  [[ "$branch" == HEAD || "$branch" == main || -z "$branch" ]] && continue
  if git -C "$work/new" show-ref --quiet --verify "refs/remotes/origin/$branch"; then
    printf 'ALREADY PRESENT: %s\n' "$branch" >> "$REPORT"
    existing=$((existing+1))
    continue
  fi
  # Replay branch changes since its merge-base with original main, not the
  # differences caused by its being behind the newer main.
  git -C "$work/old" diff --binary --full-index "origin/main...origin/$branch" -- . ':(exclude).github/workflows/**' > "$work/changes.patch"
  if [[ ! -s "$work/changes.patch" ]]; then
    printf 'NO NON-WORKFLOW DELTA: %s\n' "$branch" >> "$REPORT"
    empty=$((empty+1))
    continue
  fi
  if grep -aEq 'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----' "$work/changes.patch"; then
    printf 'SKIP POSSIBLE SECRET: %s\n' "$branch" >> "$REPORT"
    failed=$((failed+1))
    continue
  fi
  git -C "$work/new" checkout -q -B "$branch" origin/main
  if ! git -C "$work/new" apply --3way --index "$work/changes.patch" > "$work/apply.log" 2>&1; then
    printf 'CONFLICT: %s (manual replay needed)\n' "$branch" >> "$REPORT"
    failed=$((failed+1))
    git -C "$work/new" reset --hard -q
    git -C "$work/new" clean -fdq
    continue
  fi
  if git -C "$work/new" diff --cached --quiet; then
    printf 'ALREADY IN PUBLIC MAIN: %s\n' "$branch" >> "$REPORT"
    empty=$((empty+1))
    continue
  fi
  git -C "$work/new" -c user.name="Forever Sim migration" -c user.email="migration@users.noreply.github.com" commit -qm "migration: replay private branch $branch without history"
  if git -C "$work/new" push -q origin "HEAD:refs/heads/$branch"; then
    printf 'PORTED: %s\n' "$branch" >> "$REPORT"
    ok=$((ok+1))
  else
    printf 'PUSH FAILED: %s\n' "$branch" >> "$REPORT"
    failed=$((failed+1))
  fi
done < <(git -C "$work/old" for-each-ref --format='%(refname:lstrip=3)' refs/remotes/origin)
printf 'TOTAL ported=%d already-present=%d empty=%d failed=%d\n' "$ok" "$existing" "$empty" "$failed" | tee -a "$REPORT"
echo "Detailed report: $REPORT"
echo "Legacy automatic Actions workflows were intentionally excluded. Existing PR branches were not overwritten."
