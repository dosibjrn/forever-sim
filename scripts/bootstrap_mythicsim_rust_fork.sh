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

# Packaging-only integrity check. Never re-evaluate a completed M1/P1-P7 gate,
# compare modern rules to an obsolete DPS number, or assert MythicSim parity.
# The Rust compiler ensures the merged *source* is buildable for consumers.
check_engine_source() {
  echo "Checking compilability of Rust source $(git rev-parse HEAD)"
  cargo check --locked
  echo "SOURCE_BUILDABLE_NO_GATE_REVALIDATION"
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
  check_engine_source
  git push fork HEAD:refs/heads/forever-integration
fi

# Merge ALL upstream changes; do not skip commits or choose a curated subset.
# A conflict is a real porting task. Never silently discard our own Rust changes.
if ! git merge --no-ff --no-edit refs/remotes/origin/main; then
  echo "::error::Upstream/Rust integration conflict; both fork branches are preserved."
  git diff --name-only --diff-filter=U
  exit 1
fi

# The 114+ new upstream commits added Bernoulli call sites after the original
# typed-RNG migration. Port those exact source decisions into the one common
# RNG before auditing and testing; do not skip or weaken the audit.
python3 "$PROJECT/integrations/mythicsim-rust/port_upstream_paladin_typed_rng.py" "$PWD"
git add src/classes/paladin/spells/strikes.rs src/classes/paladin/spells/heals.rs
if ! git diff --cached --quiet; then
  git commit -m "fix(forever): route new Paladin proc decisions through typed RNG"
fi

# Preserve native scheduler events beyond a pull boundary on the fork itself.
# A future stateful two-target session must be able to resume queued events
# instead of silently consuming them at the previous target's deadline.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_pull_queue.py" "$PWD"
git add src/core/fight.rs
if ! git diff --cached --quiet; then
  git commit -m "fix(forever): retain native post-pull scheduled events"
fi

# Add the native same-actor next-target primitive and monotonic world ACK
# continuation to the maintained Rust engine, not a Python game model.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_persistent_target.py" "$PWD"
git add src/core/fight.rs src/core/fight/world_bridge.rs
if ! git diff --cached --quiet; then
  git commit -m "feat(forever): continue native actor and world ACK across targets"
fi

# Expose the same selected Rust actor in an executable two-window diagnostic.
# This is native-only: no two mob kills, live gsim ACK or paid recovery is claimed.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_two_pull_cli.py" "$PWD"
git add src/core/fight.rs src/classes.rs src/engine/prepared.rs src/lib.rs src/main.rs
if ! git diff --cached --quiet; then
  git commit -m "feat(forever): expose selected native same-actor two-window diagnostic"
fi

# The second source-backed target's armor ramp must use the retained native clock.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_target_ramp_clock.py" "$PWD"
git add src/core/fight.rs
if ! git diff --cached --quiet; then
  git commit -m "fix(forever): schedule second-target armor effects at global native time"
fi

# Require the ACTUAL gsim-native lethal HP/death/hash acknowledgement before
# the same Rust actor may switch to its next distinct world target.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_world_lethal_ack.py" "$PWD"
git add src/core/fight/world_bridge.rs
if ! git diff --cached --quiet; then
  git commit -m "fix(forever): require native lethal world ACK before Rust retarget"
fi

# The two-target native state and world ACK regressions must pass before
# a new fork revision is published; compilation alone is insufficient.
cargo test --locked --lib persistent_next_target

# This is an engine packaging update, not a gate or native reference test.
check_engine_source
sha="$(git rev-parse HEAD)"
git push fork HEAD:refs/heads/forever-integration
echo "FORK_ENGINE_SHA=$sha" >> "${GITHUB_OUTPUT:-/dev/null}"
echo "Validated and pushed fork revision $sha."
echo "No Forever gate or production submodule was auto-promoted."
