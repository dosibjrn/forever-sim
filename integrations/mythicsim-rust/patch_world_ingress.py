#!/usr/bin/env python3
"""Apply the tiny world-boundary seam to an EXACT pinned MythicSim Rust checkout.

This edits the actual upstream fight scheduler and damage accounting, never
a parallel simulator. Abort if any upstream anchor drifts.
"""
from pathlib import Path
import argparse
import subprocess

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
                self.config.melee.in_front_of_target = front;
                return true;
            }
        }
""")
    damage = src / "core/fight/damage.rs"
    replace_once(damage,
        "        if result.target == Side::Target {\n            self.encounter_damage_taken += result.damage;\n        }",
        """        if result.target == Side::Target {
            self.encounter_damage_taken += result.damage;
            if self.now >= 0 && result.damage > 0.0 {
                super::world_bridge::record_damage(
                    self.now, result.damage, result.crit(), result.landed(), periodic,
                    format!("{:?}", self.spells[spell].id), self.label_of(result.target),
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
    print("PATCHED_EXACT_PINNED_RUST_FIGHT_WORLD_SEAM")


if __name__ == "__main__":
    main()
