#!/usr/bin/env python3
"""Apply the tiny world-boundary seam to an EXACT pinned MythicSim Rust checkout.

This edits the actual upstream fight scheduler and damage accounting, never
a parallel simulator. Abort if any upstream anchor drifts.
"""
from pathlib import Path
import argparse
import subprocess
import sys

REV = "666fe17a42682068a3c8497d88d5fa3732cbdfb9"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"PINNED_RUST_WORLD_PATCH_ANCHOR_MISMATCH {path} {old[:70]!r}")
    path.write_text(text.replace(old, new))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("checkout", type=Path)
    args = p.parse_args()
    root = args.checkout.resolve()
    if subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip() != REV:
        raise SystemExit("PINNED_RUST_REVISION_MISMATCH")
    src = root / "src"
    fight = src / "core/fight.rs"
    replace_once(fight, "mod absorb;\n", "pub(crate) mod world_bridge;\nmod absorb;\n")
    replace_once(fight,
        "        let iterations = self.config.iterations;\n",
        "        if world_bridge::enabled() {\n"
        "            self.config.iterations = world_bridge::requested_iterations(self.config.iterations);\n"
        "        }\n"
        "        let iterations = self.config.iterations;\n")
    replace_once(fight,
        "            self.run_once();\n",
        "            if world_bridge::enabled() { world_bridge::begin_iteration(iteration as u32); }\n"
        "            self.run_once();\n")
    replace_once(fight,
        "        while self.step() {}\n        self.cleanup();",
        "        while self.step() {}\n"
        "        if world_bridge::enabled() { world_bridge::finish(self.duration, self.encounter_damage_taken); }\n"
        "        self.cleanup();")
    replace_once(fight,
        "    fn step(&mut self) -> bool {\n",
        """    fn step(&mut self) -> bool {
        if world_bridge::enabled() {
            let next_native = self.queue.peek_time().unwrap_or(NEVER_EXPIRES)
                .min(self.autos.min_time).min(self.min_task_time)
                .min(self.end_of_combat);
            if let Some(boundary) = world_bridge::due(next_native, self.end_of_combat) {
                if boundary > self.now { self.advance_to(boundary); }
                let (distance, front) = world_bridge::exchange(
                    boundary, self.duration, self.encounter_damage_taken);
                if distance != self.config.distance {
                    self.config.distance = distance;
                    self.changed(reads::CASTS);
                }
                // Facing can invalidate cached APL FrontOfTarget conditions
                // even when the distance is unchanged. Mirror range's
                // production invalidation at the native scheduler boundary.
                if self.config.melee.in_front_of_target != front {
                    self.config.melee.in_front_of_target = front;
                    self.changed(reads::CASTS);
                }
                return true;
            }
        }
""")
    damage = src / "core/fight/damage.rs"
    replace_once(damage,
        "        if result.target == Side::Target {\n            self.encounter_damage_taken += result.damage;\n        }",
        """        if result.target == Side::Target {
            self.encounter_damage_taken += result.damage;
            if result.damage > 0.0 {
                // Pre-pull source hits are genuine target damage. Keep their
                // negative native clock; gsim applies them at the first t=0
                // boundary, before the next native combat decision.
                // Source-native Fight owns spell caster; the gsim world
                // must not misattribute a real pet hit to its player.
                let caster = self.caster(spell);
                let (caster_type, caster_index, caster_label) = match caster {
                    Side::Player => ("", 0, String::new()),
                    Side::Pet(index) => ("pet", index as u32, self.label_of(caster)),
                    _ => panic!("RUST_WORLD_UNSUPPORTED_DAMAGE_CASTER"),
                };
                super::world_bridge::record_damage(
                    self.now, result.damage, result.crit(), result.landed(), periodic,
                    format!("{:?}", self.spells[spell].id), self.label_of(result.target),
                    caster_type, caster_index, caster_label,
                );
            }
        }""")
    prepared = src / "engine/prepared.rs"
    replace_once(prepared,
        "    let report = classes::run_prepared(prepared).map_err(PreparedError::Invalid)?;",
        """    if crate::core::fight::world_bridge::enabled() {
        crate::core::fight::world_bridge::start(&prepared.request_sha256);
    }
    let report = classes::run_prepared(prepared).map_err(PreparedError::Invalid)?;""")
    module = Path(__file__).with_name("world_bridge.rs")
    target = src / "core/fight/world_bridge.rs"
    if target.exists():
        raise SystemExit("RUST_WORLD_MODULE_ALREADY_EXISTS")
    target.write_bytes(module.read_bytes())
    # The production P7 searches select balanced RNG via WOWSIM_RNG_MODE,
    # but pinned upstream has no native consumer for that flag. Apply the
    # existing WF652/659/660 core-RNG patches to this SAME pinned checkout,
    # after the world seam and before either Actions workflow builds it.
    # Both M1 and native-world Actions call this exact production patcher.
    for name in ("wf652_apply_balanced.py", "wf659_typed_rng.py",
                 "wf660_boolean_migration.py"):
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name(name))],
            cwd=root, check=True,
        )
    # Historical native L60 diagnostics found legal >100% crit thresholds.
    # Reuse their tested fix in the ACTUAL selected production Rust build:
    # stochastic treats p >= 1 as certain, p <= 0 as impossible, while NaN
    # remains a hard error. Apply AFTER WF659's typed dispatch is installed.
    subprocess.run(
        [sys.executable, str(Path(__file__).with_name("rng_extreme_probability_fix.py")),
         "--patch-engine", str(root)],
        cwd=root, check=True,
    )
    # Existing old-repo CI invariant; don't allow untyped comparisons to
    # silently bypass the quota RNG in future source additions.
    subprocess.run(
        [sys.executable, str(Path(__file__).with_name("wf659_rng_boolean_audit.py")),
         str(src)],
        cwd=root, check=True,
    )
    rng = (src / "core/rng.rs").read_text()
    if ("WOWSIM_RNG_MODE" not in rng or "SimRng::Balanced" not in rng
            or "wf_l60_rng_extreme_tests" not in rng):
        raise SystemExit("PINNED_RUST_BALANCED_RNG_PATCH_NOT_APPLIED")
    print("PATCHED_EXACT_PINNED_RUST_FIGHT_WORLD_SEAM_AND_TYPED_BALANCED_RNG")


if __name__ == "__main__":
    main()
