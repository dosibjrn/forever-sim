#!/usr/bin/env bash
# Bootstrap and safely update the public MythicSim Rust fork.
# No changes to Forever gate predicates or main; only promote a tested Rust revision.
set -Eeuo pipefail

UPSTREAM="sage3648/mythicsim-forever-engine"
FORK="dosibjrn/mythicsim-forever-engine"
PIN="666fe17a42682068a3c8497d88d5fa3732cbdfb9"
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${FOREVER_RUST_FORK_TOKEN:?Set FOREVER_RUST_FORK_TOKEN as a repository Actions secret (public_repo-capable PAT)}"
export GH_TOKEN="$FOREVER_RUST_FORK_TOKEN"

who="$(gh api user --jq .login)"
if [[ "$who" != "dosibjrn" ]]; then
  echo "::error::Fork token authenticated as $who, expected dosibjrn."
  exit 1
fi

if ! gh api "repos/$FORK" >/dev/null 2>&1; then
  echo "Creating public upstream fork $FORK"
  gh api --method POST "repos/$UPSTREAM/forks" -f name=mythicsim-forever-engine >/dev/null
fi

# GitHub's fork creation endpoint is asynchronous.
ready=0
for _ in {1..40}; do
  if gh api "repos/$FORK" >/dev/null 2>&1; then ready=1; break; fi
  sleep 3
done
if [[ "$ready" != 1 ]]; then
  echo "::error::Fork did not become available; no integration version was changed."
  exit 1
fi
actual_parent="$(gh api "repos/$FORK" --jq '.parent.full_name // ""')"
is_fork="$(gh api "repos/$FORK" --jq '.fork')"
visibility="$(gh api "repos/$FORK" --jq '.private')"
if [[ "$actual_parent" != "$UPSTREAM" || "$is_fork" != true || "$visibility" != false ]]; then
  echo "::error::Destination exists but is not the expected public fork of $UPSTREAM."
  exit 1
fi

gh auth setup-git
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git clone --quiet --filter=blob:none "https://github.com/$UPSTREAM.git" "$work/engine"
cd "$work/engine"
git config user.name "Forever Rust integration"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git remote add fork "https://github.com/$FORK.git"
git fetch --quiet fork main
git fetch --quiet origin main

# Fork main tracks the complete upstream history, not a cherry-picked subset.
# Non-fast-forward updates are rejected; no force push, no custom validations overwritten.
git push fork refs/remotes/origin/main:refs/heads/main
echo "FORK_UPSTREAM_MAIN=$(git rev-parse refs/remotes/origin/main)" >> "${GITHUB_OUTPUT:-/dev/null}"

test_engine() {
  local mode="$1"
  echo "Testing exact candidate $(git rev-parse HEAD)"
  cargo test --locked --lib wf652_balanced_tests
  cargo test --locked --lib wf_l60_rng_extreme_tests
  cargo test --locked --lib
  CARGO_PROFILE_RELEASE_LTO=off CARGO_PROFILE_RELEASE_CODEGEN_UNITS=16 cargo build --release --locked
  # Historical fixture is a regression witness; failure must be investigated,
  # never silently deleted or rebranded as an accepted new reference.
  if [[ "$mode" == baseline ]]; then
    # EXACT old engine reference is a permanent regression witness.
    (cd "$PROJECT" && python3 integrations/mythicsim-rust/verify_reference.py \
      --engine "$PWD/../engine/target/release/forever-engine")
  elif [[ "$mode" == upstream ]]; then
    # New upstream mechanics can change DPS legitimately. Keep the old witness,
    # but validate the new source identity, native↔2D causality, real RNG, and
    # actual changed score before updating the integration branch.
    python3 "$PROJECT/integrations/mythicsim-rust/wf659_rng_boolean_audit.py" "$PWD/src"
    (cd "$PROJECT" && python3 integrations/mythicsim-rust/verify_upstream_candidate.py \
      --engine "$OLDPWD/engine/target/release/forever-engine" \
      --out "$GITHUB_WORKSPACE/rust-upstream-candidate.json")
  else
    echo "::error::Unrecognized Rust validation mode $mode"; exit 2
  fi
}

if git ls-remote --exit-code --heads fork forever-integration >/dev/null 2>&1; then
  git fetch --quiet fork forever-integration
  git switch --quiet --create forever-integration fork/forever-integration
  echo "Existing fork integration branch retained."
else
  git switch --quiet --create forever-integration "$PIN"
  python3 "$PROJECT/integrations/mythicsim-rust/patch_world_ingress.py" "$PWD"
  git add src
  if git diff --cached --quiet; then
    echo "::error::Expected Rust source changes are missing."
    exit 1
  fi
  git commit -qm "feat(forever): preserve source-native 2D bridge and typed balanced RNG"
  # First publish a reproducible patched historical source. This protects
  # our implementation while upstream main continues advancing independently.
  test_engine baseline
  git push fork HEAD:refs/heads/forever-integration
fi

# Merge ALL upstream changes; do not skip commits or choose a curated subset.
# A conflict is a real porting task. Never silently discard our own Rust changes.
if ! git merge --no-ff --no-edit refs/remotes/origin/main; then
  echo "::error::Upstream/Rust integration conflict; both fork branches are preserved."
  git diff --name-only --diff-filter=U
  exit 1
fi

test_engine upstream
sha="$(git rev-parse HEAD)"
git push fork HEAD:refs/heads/forever-integration
echo "FORK_ENGINE_SHA=$sha" >> "${GITHUB_OUTPUT:-/dev/null}"
echo "Validated and pushed fork revision $sha."
echo "No Forever gate or production submodule was auto-promoted."
