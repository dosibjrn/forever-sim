#!/usr/bin/env bash
# Finish the private mage-level-sim -> public forever-sim STATE snapshot.
# Requires Git Bash or bash, git, git-lfs, tar and authenticated Git access.
# Existing public PR branches and issues are preserved. No old Git history is copied.
set -euo pipefail
OLD_URL="${OLD_URL:-https://github.com/dosibjrn/mage-level-sim.git}"
NEW_URL="${NEW_URL:-https://github.com/dosibjrn/forever-sim.git}"
command -v git >/dev/null || { echo "git required" >&2; exit 2; }
command -v tar >/dev/null || { echo "tar required" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 required for byte/stage parity check" >&2; exit 2; }
git lfs version >/dev/null 2>&1 || { echo "git-lfs required to preserve canonical source assets" >&2; exit 2; }
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
echo "[1/7] Clone original private main (read-only)"
git clone --depth=1 --single-branch --branch main "$OLD_URL" "$work/old"
git -C "$work/old" lfs pull
echo "[2/7] Clone destination public main"
git clone --depth=1 --single-branch --branch main "$NEW_URL" "$work/new"
echo "[3/7] Preflight: do not publish obvious embedded credentials"
if git -C "$work/old" grep -I -nE 'gh[pousr]_[a-zA-Z0-9]{30,}|github_pat_[a-zA-Z0-9_]{40,}|-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----|AKIA[A-Z0-9]{16}' -- . > "$work/secret-hits"; then
  echo "Potential credentials found. Review privately before publishing. Aborting."
  sed -E 's/:.*/: [redacted match]/' "$work/secret-hits" | head -30
  exit 4
fi
echo "[4/7] Copy only tracked source paths, preserving public migration controls"
# A full working-tree tar could also copy ignored/untracked private files;
# forcing 'git add -A' would then publish them without any source-index audit.
python3 "$work/new/scripts/verify_public_snapshot.py" \
  --source "$work/old" --emit-selected-paths > "$work/selected-paths.z"
tar -C "$work/old" --null -T "$work/selected-paths.z" -cf - | tar -C "$work/new" -xf -
echo "[5/7] Check that any source LFS pointers are materialized"
unresolved="$(find "$work/new" -type f \( -name '*.sqlite' -o -name '*.db' -o -name '*.bin' -o -name '*.zip' \) -not -path '*/.git/*' -exec grep -Il '^version https://git-lfs.github.com/spec/v1' {} + || true)"
if [[ -n "$unresolved" ]]; then
  echo "Source LFS assets unresolved; aborting:" >&2
  echo "$unresolved" >&2
  exit 5
fi
echo "[6/7] Stage public main snapshot (not historical commits)"
# Stage only selected source paths, not unrelated files in the public clone.
# Literal pathspecs handle filenames containing '[' or '*'.
GIT_LITERAL_PATHSPECS=1 git -C "$work/new" add -A --force \
  --pathspec-from-file="$work/selected-paths.z" --pathspec-file-nul
python3 "$work/new/scripts/verify_public_snapshot.py" --source "$work/old" --target "$work/new"
git -C "$work/new" diff --cached --stat
if git -C "$work/new" diff --cached --quiet; then
  echo "Already up to date; no change required."
  exit 0
fi
echo
echo "WARNING: This publishes the selected private repository working-tree files PUBLICLY."
echo "Review origin and rights to included data, evidence and source captures."
read -r -p "Publish this state to forever-sim main? Type PUBLISH: " confirmation
[[ "$confirmation" == "PUBLISH" ]] || { echo "Cancelled"; exit 3; }
git -C "$work/new" -c user.name="Forever Sim migration" -c user.email="migration@users.noreply.github.com" commit -m "migration: complete source main snapshot without previous Git history"
echo "[7/7] Push to public main. Only the manual smoke workflow remains enabled."
git -C "$work/new" push origin HEAD:main
echo "Snapshot published. Verify the Actions runner smoke before enabling old workflows."
