#!/usr/bin/env python3
"""Port the native same-actor next-target primitive into the maintained Rust fork.

This edits Rust source only. It does not implement game mechanics in Python,
claim a gsim 100-mob run, or replace the existing one-shot simulator.
"""
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(source: str, old: str, new: str, marker: str) -> str:
    if marker in source:
        if source.count(marker) != 1:
            raise ValueError(f"partial or ambiguous already-applied Rust port: {marker}")
        if new not in source:
            # Work2's later early-kill clock port is a verified descendant of
            # this source method, not a partially applied base migration.
            if marker == "    pub(crate) fn begin_next_target(&mut self":
                from port_native_early_retarget import HELPER, NEW_GUARD, TEST
                typed_rng_test = TEST.replace(
                    "DruidAgent::fight(&prepared)",
                    "DruidAgent::fight(&prepared, crate::core::rng::RngMode::Stochastic)",
                    1,
                )
                if (source.count(HELPER) == 1 and source.count(NEW_GUARD) == 1
                        and sum(source.count(candidate) for candidate in (TEST, typed_rng_test)) == 1):
                    return source
            if marker == "    fn native_persistent_next_target_retains_actor_and_native_queue()":
                # Early-world clock adds an adjacent Rust test before this
                # original test. Require both entire tests to be intact.
                from port_native_early_retarget import TEST
                typed_rng_test = TEST.replace(
                    "DruidAgent::fight(&prepared)",
                    "DruidAgent::fight(&prepared, crate::core::rng::RngMode::Stochastic)",
                    1,
                )
                typed_rng_fight_test = FIGHT_TEST.replace(
                    "DruidAgent::fight(&prepared)",
                    "DruidAgent::fight(&prepared, crate::core::rng::RngMode::Stochastic)",
                    1,
                ).rstrip("\n")
                early_test_count = sum(source.count(candidate) for candidate in (TEST, typed_rng_test))
                fight_test_count = sum(source.count(candidate) for candidate in (FIGHT_TEST.rstrip("\n"), typed_rng_fight_test))
                if early_test_count == 1 and fight_test_count == 1:
                    return source
            raise ValueError(f"partial or ambiguous already-applied Rust port: {marker}")
        return source
    if source.count(old) != 1:
        raise ValueError(f"missing/ambiguous Rust anchor for {marker}")
    return source.replace(old, new, 1)


FIGHT_METHOD = """    /// Begin a second distinct world target on the SAME native actor.
    /// No iteration reset, resource reset, cooldown reset, aura reset or queue clear.
    /// Until paid downtime is implemented in the native session, accept only
    /// an immediate next pull; skipping scheduled recovery events is illegal.
    pub(crate) fn begin_next_target(&mut self, at_ns: i64, next_end_ns: i64)
        -> Result<(), &'static str>
    {
        if at_ns != self.end_of_combat || at_ns < self.now || next_end_ns <= at_ns {
            return Err("RUST_NEXT_TARGET_CLOCK_INVALID");
        }
        if world_bridge::enabled() {
            world_bridge::begin_next_target(at_ns)?;
        }
        self.advance_to(at_ns);
        // Target auras/armor are new; player, pets, timers and queued
        // native actions remain exactly those of the preceding encounter.
        // A defeated target can still have active debuffs. End ONLY its aura
        // lifetime before reset; never call global cleanup on the actor.
        self.aura_done_iteration(Side::Target);
        self.reset_unit(Side::Target);
        self.pull_started_at = at_ns;
        self.duration = next_end_ns;
        self.end_of_combat = next_end_ns;
        self.execute_phase = 0;
        self.next_execute_phase();
        self.schedule(at_ns, PRIORITY_PREPULL + 1, Action::EncounterStart);
        Ok(())
    }

"""

BRIDGE_METHOD = """/// Switch the acknowledged world target without restarting the native clock
/// or ACK ancestry. Only a future same-actor session may call this; legacy
/// independent iterations intentionally continue to use begin_iteration().
pub(crate) fn begin_next_target(at_ns: i64) -> Result<(), &'static str> {
    BRIDGE.with(|state| {
        let mut state = state.borrow_mut();
        let bridge = state.as_mut().ok_or("RUST_WORLD_NOT_STARTED")?;
        if !bridge.pending.is_empty() {
            return Err("RUST_WORLD_UNACKNOWLEDGED_DAMAGE");
        }
        if at_ns <= bridge.last_tick_ns || at_ns < 0 {
            return Err("RUST_WORLD_NEXT_TARGET_CLOCK_REWOUND");
        }
        bridge.iteration = bridge.iteration.checked_add(1)
            .ok_or("RUST_WORLD_TARGET_INDEX_OVERFLOW")?;
        bridge.last_health = None; // new world target, not a healed old one
        bridge.next_tick_ns = at_ns;
        // Deliberately preserve sequence, previous_ack_id, last_tick_ns,
        // event_ordinal and source identity across targets.
        Ok(())
    })
}

"""

FIGHT_TEST = """    #[test]
    fn native_persistent_next_target_retains_actor_and_native_queue() {
        use super::{Action, PRIORITY_PREPULL, PRIORITY_REGEN};
        let prepared: crate::contracts::prepared_v2::PreparedV2 = serde_json::from_str(
            include_str!(concat!(env!("CARGO_MANIFEST_DIR"),
                "/fixtures/mage/prepared-v2/balance-druid-revelation.prepared.json"))
        ).unwrap();
        let mut fight = crate::classes::druid::agent::DruidAgent::fight(&prepared).unwrap();
        if !fight.extra_targets_built {
            fight.build_extra_targets();
            fight.build_exclusive_tracking();
            fight.apply_enemy_slow_priorities();
        }
        eprintln!("NATIVE_NEXT_TARGET_STAGE=initial_reset");
        fight.reset();
        fight.schedule(0, PRIORITY_PREPULL + 1, Action::EncounterStart);
        let mut steps = 0;
        while fight.step() {
            steps += 1;
            assert!(steps < 100_000, "first native pull did not terminate");
        }
        assert!(steps > 1, "native combat did not execute");
        eprintln!("NATIVE_NEXT_TARGET_STAGE=first_pull_done");
        let first_end = fight.end_of_combat;
        let kept_mana = fight.config.max_mana * 0.37;
        let kept_health = fight.config.max_health * 0.61;
        fight.player.mana = kept_mana;
        fight.player.health = kept_health;
        let kept_timer = fight.timers.first().copied();
        let future = fight.queue.push(first_end + 5_000_000, PRIORITY_REGEN, Action::ManaTick);
        let old_now = fight.now;
        assert_eq!(fight.begin_next_target(first_end - 1, first_end + 2_000_000_000),
            Err("RUST_NEXT_TARGET_CLOCK_INVALID"));
        assert_eq!(fight.now, old_now);
        eprintln!("NATIVE_NEXT_TARGET_STAGE=transition");
        fight.begin_next_target(first_end, first_end + 2_000_000_000).unwrap();
        assert_eq!(fight.player.mana, kept_mana);
        assert_eq!(fight.player.health, kept_health);
        assert_eq!(fight.timers.first().copied(), kept_timer);
        assert!(fight.queue.cancel(future), "queued native future action was lost");
        assert!(fight.next_execute >= first_end);
        let mut second_steps = 0;
        while fight.step() {
            second_steps += 1;
            assert!(second_steps < 100_000, "second native pull did not terminate");
        }
        assert!(second_steps > 0, "second target did not run native combat");
        assert!(fight.now >= first_end, "native clock reset on second target");
    }

"""

BRIDGE_TEST = """#[cfg(test)]
mod persistent_next_target_tests {
    use super::{begin_next_target, Bridge, BRIDGE};

    #[test]
    fn world_persistent_next_target_preserves_ack_and_monotonic_clock() {
        BRIDGE.with(|state| *state.borrow_mut() = Some(Bridge {
            iteration: 0, sequence: 4, next_tick_ns: 130_000_000,
            last_tick_ns: 120_000_000, last_health: Some(40.0),
            previous_ack_id: "ack-from-first-target".into(),
            source_hash: "a".repeat(64), event_ordinal: 3, pending: Vec::new(),
        }));
        assert_eq!(begin_next_target(120_000_000),
            Err("RUST_WORLD_NEXT_TARGET_CLOCK_REWOUND"));
        begin_next_target(121_000_000).unwrap();
        BRIDGE.with(|state| {
            let state = state.borrow();
            let bridge = state.as_ref().unwrap();
            assert_eq!(bridge.iteration, 1);
            assert_eq!(bridge.sequence, 4);
            assert_eq!(bridge.last_tick_ns, 120_000_000);
            assert_eq!(bridge.next_tick_ns, 121_000_000);
            assert_eq!(bridge.previous_ack_id, "ack-from-first-target");
            assert_eq!(bridge.event_ordinal, 3);
            assert_eq!(bridge.last_health, None);
        });
        BRIDGE.with(|state| *state.borrow_mut() = None);
    }
}
"""


def port_fight(source: str) -> str:
    source = replace_once(
        source,
        "    end_of_combat: i64,\n    /// Go ",
        "    end_of_combat: i64,\n    pull_started_at: i64,\n    /// Go ",
        "    pull_started_at: i64,",
    )
    source = replace_once(
        source,
        "            end_of_combat: config.base_duration,\n            execute_phase: 0,",
        "            end_of_combat: config.base_duration,\n            pull_started_at: 0,\n            execute_phase: 0,",
        "            pull_started_at: 0,",
    )
    source = replace_once(
        source,
        "        self.execute_phase = 0;\n        self.next_execute_phase();\n        self.end_of_combat = self.duration;",
        "        self.pull_started_at = 0;\n        self.end_of_combat = self.duration;\n        self.execute_phase = 0;\n        self.next_execute_phase();",
        "        self.pull_started_at = 0;\n        self.end_of_combat = self.duration;",
    )
    source = replace_once(
        source,
        "        self.next_execute = ((1.0 - proportion) * self.duration as f64) as i64;",
        "        self.next_execute = self.pull_started_at +\n            ((1.0 - proportion) * (self.end_of_combat - self.pull_started_at) as f64) as i64;",
        "        self.next_execute = self.pull_started_at +",
    )
    source = replace_once(
        source,
        "    /// Go `Simulation.reset` and `Environment.reset`.\n",
        FIGHT_METHOD + "    /// Go `Simulation.reset` and `Environment.reset`.\n",
        "    pub(crate) fn begin_next_target(&mut self",
    )
    source = replace_once(
        source,
        "mod tests {\n    use super::{Mp5Path, Side, DEFENDERS, MAX_TARGETS};",
        "mod tests {\n    use super::{Mp5Path, Side, DEFENDERS, MAX_TARGETS};\n\n" + FIGHT_TEST.rstrip("\n"),
        "    fn native_persistent_next_target_retains_actor_and_native_queue()",
    )
    return source


def port_bridge(source: str) -> str:
    # A later source patch deliberately tightens the already-installed Rust
    # method. Reapplying the base port must recognize ONLY that exact hardened
    # descendant, not treat any method with the same name as idempotent.
    if "RUST_WORLD_NEXT_TARGET_NOT_NATIVE_LETHAL" in source:
        from port_native_world_lethal_ack import OLD, NEW
        if BRIDGE_METHOD.count(OLD) != 1:
            raise ValueError("base Rust world-retarget anchor drifted")
        hardened = BRIDGE_METHOD.replace(OLD, NEW, 1)
        if source.count(hardened) != 1:
            raise ValueError("hardened Rust world-retarget method is ambiguous")
    else:
        source = replace_once(
            source,
            "pub(crate) fn due(next_native_ns: i64, end_ns: i64) -> Option<i64> {",
            BRIDGE_METHOD + "pub(crate) fn due(next_native_ns: i64, end_ns: i64) -> Option<i64> {",
            "pub(crate) fn begin_next_target(at_ns: i64)",
        )
    if "fn world_persistent_next_target_preserves_ack_and_monotonic_clock()" not in source:
        source += "\n" + BRIDGE_TEST
    elif source.count("fn world_persistent_next_target_preserves_ack_and_monotonic_clock()") != 1:
        raise ValueError("duplicate bridge regression")
    return source


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_persistent_target.py RUST_ENGINE_ROOT")
    root = Path(argv[1]) / "src/core"
    changes = 0
    for path, transform in ((root / "fight.rs", port_fight),
                            (root / "fight/world_bridge.rs", port_bridge)):
        old = path.read_text()
        new = transform(old)
        if old != new:
            path.write_text(new)
            changes += 1
    print("RUST_NATIVE_PERSISTENT_NEXT_TARGET_PORTED" if changes
          else "RUST_NATIVE_PERSISTENT_NEXT_TARGET_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
