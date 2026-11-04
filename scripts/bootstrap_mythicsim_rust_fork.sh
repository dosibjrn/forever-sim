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

# Preserve the source-legal three-rank Improved Entangling Roots selection
# in the real Rust preparer. Executable root/damage/break effects are a later
# native Rust slice; rank intake alone never awards P1/P2 acceptance.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_improved_roots_rank.py" "$PWD"
python3 "$PROJECT/integrations/mythicsim-rust/port_native_entangling_roots_dot.py" "$PWD"
# Stage every actual Rust source and regression file changed by these two ports.
# Staging only talents.rs silently omitted Roots behavior from the published fork.
git add src/classes/druid/prepare/talents.rs src/classes/druid/prepare/balance.rs \
  src/classes/druid/prepare/export.rs src/contracts/prepared_v2.rs \
  src/classes/druid/agent.rs src/classes/druid/prepared/coverage.rs \
  tests/classes/druid/prepare.rs
if ! git diff --cached --quiet; then
  git commit -m "feat(forever): prepare source-native Entangling Roots damage and talent ranks"
fi

# Expose the selected native Druid talent layout as versioned wire metadata.
# This API reports layout only; native prepare remains the legality authority.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_talent_layout_api.py" "$PWD"
git add src/classes/druid/prepare.rs src/lib.rs src/main.rs
if ! git diff --cached --quiet; then
  git commit -m "feat(forever): export native Druid talent layout metadata"
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

# A gsim source-native lethal ACK may finish a mob earlier than the fixed
# duration cap; only the existing live-world bridge can authorize the handoff.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_early_retarget.py" "$PWD"
git add src/core/fight.rs
if ! git diff --cached --quiet; then
  git commit -m "fix(forever): allow early live-world target kill clock without native reset"
fi

# Stop real world-coupled native combat only after its committed gsim lethal
# HP/death/hash ACK; preserve the current native actor for future retargeting.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_world_lethal_terminal.py" "$PWD"
git add src/core/fight.rs src/core/fight/world_bridge.rs
if ! git diff --cached --quiet; then
  git commit -m "fix(forever): end current world pull at confirmed native lethal ACK"
fi

# Publish the same real source-Rust two-distinct-world-target CLI exercised
# by the retained gsim CombatRuntime integration regression. This is NOT a
# paid 100-mob route or an acceptance gate.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_two_world_cli.py" "$PWD"
git add src/core/fight.rs src/classes.rs src/engine/prepared.rs src/lib.rs src/main.rs
if ! git diff --cached --quiet; then
  git commit -m "feat(forever): expose retained Rust actor to two real gsim world kills"
fi

# Expose actual Rust health damage resource deltas per target, including
# incoming source-native attacks when the prepared scenario enables them.
# Reporting does not add mechanics, fake survival or claim paid recovery.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_health_damage_receipts.py" "$PWD"
git add src/core/fight.rs
if ! git diff --cached --quiet; then
  git commit -m "feat(forever): retain source-native damage receipts across 2D kills"
fi

# Preserve measured mana regeneration from the genuine Rust 2-second tick
# resources in each retained world-target receipt. This is in-combat source
# evidence, not between-pull idle regeneration or paid recovery.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_mana_regen_receipts.py" "$PWD"
git add src/core/fight.rs
if ! git diff --cached --quiet; then
  git commit -m "feat(forever): report native mana regeneration across retained world kills"
fi

# Publish gsim's actually observed world movement into the retained native
# actor's existing Rust casting rules. Keep the world as movement authority;
# do not duplicate spell legality in the Python 2D driver.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_gsim_moving.py" "$PWD"
git add src/core/fight.rs src/core/fight/world_bridge.rs
if ! git diff --cached --quiet; then
  git commit -m "feat(forever): apply real gsim movement to native cast legality"
fi

# The canonical RNG contract is typed and required at the native boundary.
# Never publish an environment-selected stochastic optimizer fallback.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_typed_rng.py" "$PWD"
# Final idempotent pass normalizes the talent API before the bounded runtime
# iteration option is added to the public sim CLI.
python3 "$PROJECT/integrations/mythicsim-rust/port_native_talent_layout_api.py" "$PWD"
python3 "$PROJECT/integrations/mythicsim-rust/port_native_sim_iterations.py" "$PWD"
git add README.md src/core/rng.rs src/core/fight.rs src/classes.rs src/engine/prepared.rs \
  src/lib.rs src/main.rs src/classes/*/agent.rs src/classes/*/prepared.rs
git add tests/
if ! git diff --cached --quiet; then
  git commit -m "feat(forever): require typed RNG mode throughout native combat"
fi

# Existing native retarget regressions and new live terminal predicate must
# pass before publishing this selected Rust integration.
cargo test --locked --lib persistent_next_target
cargo test --locked --lib world_lethal_terminal
# Native Druid P2 witnesses must pass before the selected Rust integration is published.
cargo test --locked --lib native_improved_roots_rank_intake
cargo test --locked --lib druid_talent_layout_api_tests

# This is an engine packaging update, not a gate or native reference test.
check_engine_source
sha="$(git rev-parse HEAD)"
git push fork HEAD:refs/heads/forever-integration
echo "FORK_ENGINE_SHA=$sha" >> "${GITHUB_OUTPUT:-/dev/null}"
echo "Validated and pushed fork revision $sha."
echo "No Forever gate or production submodule was auto-promoted."
