#!/usr/bin/env python3
"""Port explicit, source-native passive recovery time into the retained Rust actor.

Only already-scheduled Rust ManaTick, HealthRegenTick, ItemManaTick and
self-targeted helpful HoT ticks execute during the paid interval. Combat
actions remain queued until the next target begins. No Python Warcraft
mechanics or synthetic resource gains are introduced.
"""
from __future__ import annotations

import sys
from pathlib import Path

MAX_RECOVERY_NS = 300_000_000_000

QUEUE_ANCHOR = "    /// Pop the next live action.\n"
QUEUE_METHOD_MARKER = "pub(crate) fn pop_first_matching_before"
QUEUE_METHOD = """    /// Pop the earliest live action matching the predicate no later than latest_ns.
    /// Nonmatching actions keep their original handles, times and priority.
    pub(crate) fn pop_first_matching_before(
        &mut self,
        latest_ns: i64,
        mut matches: impl FnMut(&T) -> bool,
    ) -> Option<(i64, Handle, T)> {
        let mut deferred = Vec::new();
        let mut result = None;
        while let Some(Reverse(entry)) = self.heap.pop() {
            let index = (entry.sequence() - self.base) as usize;
            let Some(payload) = self.slots.get(index).and_then(Option::as_ref) else {
                continue;
            };
            if matches(payload) {
                if entry.time() <= latest_ns {
                    let payload = self.slots.get_mut(index).and_then(Option::take)
                        .expect("live pending action has a payload");
                    result = Some((entry.time(), Handle(entry.sequence()), payload));
                } else {
                    deferred.push(Reverse(entry));
                }
                break;
            }
            deferred.push(Reverse(entry));
        }
        self.heap.extend(deferred);
        result
    }

"""
QUEUE_TEST_ANCHOR = "    #[test]\n    fn handles_from_before_a_clear_are_inert()"
QUEUE_TEST_MARKER = "fn pop_first_matching_before_preserves_nonmatching_actions_and_order()"
QUEUE_TESTS = """    #[test]
    fn pop_first_matching_before_preserves_nonmatching_actions_and_order() {
        let mut queue = PendingQueue::default();
        queue.push(1, 0, "attack_before");
        queue.push(2, 1, "mana_tick");
        queue.push(3, 0, "attack_after");
        queue.push(4, 1, "health_tick");
        let popped = queue.pop_first_matching_before(3, |action| {
            *action == "mana_tick" || *action == "health_tick"
        });
        assert_eq!(popped.map(|(time, _, action)| (time, action)),
            Some((2, "mana_tick")));
        assert_eq!(queue.pop().map(|(time, _, action)| (time, action)),
            Some((1, "attack_before")));
        assert_eq!(queue.pop().map(|(time, _, action)| (time, action)),
            Some((3, "attack_after")));
        assert_eq!(queue.pop().map(|(time, _, action)| (time, action)),
            Some((4, "health_tick")));
    }

    #[test]
    fn pop_first_matching_before_keeps_a_match_after_the_deadline() {
        let mut queue = PendingQueue::default();
        queue.push(1, 0, "attack");
        queue.push(8, 1, "mana_tick");
        assert!(queue.pop_first_matching_before(7, |action| *action == "mana_tick").is_none());
        assert_eq!(queue.pop().map(|(time, _, action)| (time, action)),
            Some((1, "attack")));
        assert_eq!(queue.pop().map(|(time, _, action)| (time, action)),
            Some((8, "mana_tick")));
    }

"""

FIGHT_METHOD_ANCHOR = "    /// Multiple distinct gsim world deaths on one retained source-Rust actor."
FIGHT_SIGNATURE_OLD = "pub(crate) fn native_two_world_targets(&mut self, target_count: usize)"
FIGHT_SIGNATURE_NEW = "pub(crate) fn native_two_world_targets(&mut self, target_count: usize, recovery_ns: i64)"
FIGHT_HELPER_MARKER = "fn advance_paid_recovery(&mut self, recovery_ns: i64)"
FIGHT_HELPER = """    /// Advance the retained native actor through an explicitly charged recovery interval.
    /// Only already-scheduled source-native resource/HoT ticks run; combat actions remain
    /// queued for the next target. This is not an active heal-spell policy.
    fn advance_paid_recovery(&mut self, recovery_ns: i64)
        -> Result<serde_json::Value, &'static str>
    {
        const MAX_RECOVERY_NS: i64 = 300_000_000_000;
        if !(0..=MAX_RECOVERY_NS).contains(&recovery_ns) {
            return Err("RUST_NATIVE_PAID_RECOVERY_DURATION_INVALID");
        }
        if !world_bridge::acknowledged_lethal() {
            return Err("RUST_NATIVE_PAID_RECOVERY_REQUIRES_LETHAL_ACK");
        }
        let start_ns = self.now;
        let end_ns = self.now.checked_add(recovery_ns)
            .ok_or("RUST_NATIVE_PAID_RECOVERY_CLOCK_OVERFLOW")?;
        let health_before = self.player.health;
        let mana_before = self.player.mana;
        let mut mana_tick_events = 0_u64;
        let mut item_mana_tick_events = 0_u64;
        let mut health_regen_tick_events = 0_u64;
        let mut self_heal_dot_tick_events = 0_u64;

        if recovery_ns > 0 {
            loop {
                // Split field borrows: the queue is mutable while the native spell/dot
                // metadata is read-only for the action predicate.
                let dots = &self.dots;
                let spells = &self.spells;
                let next = self.queue.pop_first_matching_before(end_ns, |action| {
                    match action {
                        Action::ManaTick | Action::HealthRegenTick { .. }
                        | Action::ItemManaTick { .. } => true,
                        Action::DotTick(dot) => {
                            let dot = &dots[*dot];
                            dot.side == Side::Player && spells[dot.spell].flags.helpful
                        }
                        _ => false,
                    }
                });
                let Some((time, handle, action)) = next else {
                    break;
                };
                if time > self.now {
                    self.advance_to(time);
                }
                if !self.handle_still_valid(handle, &action) {
                    continue;
                }
                match action {
                    Action::ManaTick => mana_tick_events += 1,
                    Action::HealthRegenTick { .. } => health_regen_tick_events += 1,
                    Action::ItemManaTick { .. } => item_mana_tick_events += 1,
                    Action::DotTick(_) => self_heal_dot_tick_events += 1,
                    _ => unreachable!("recovery queue returned a non-recovery action"),
                }
                self.run_action(handle, action);
            }
            self.advance_to(end_ns);
        }

        Ok(serde_json::json!({
            "mode": "native_scheduled_regeneration_only",
            "start_ns": start_ns,
            "end_ns": self.now,
            "charged_ns": recovery_ns,
            "mana_before": mana_before,
            "mana_after": self.player.mana,
            "mana_delta": self.player.mana - mana_before,
            "health_before": health_before,
            "health_after": self.player.health,
            "health_delta": self.player.health - health_before,
            "mana_tick_events": mana_tick_events,
            "item_mana_tick_events": item_mana_tick_events,
            "health_regen_tick_events": health_regen_tick_events,
            "self_heal_dot_tick_events": self_heal_dot_tick_events,
        }))
    }

"""

FIGHT_SETUP_OLD = "        let mut windows = Vec::with_capacity(target_count);\n"
FIGHT_SETUP_NEW = FIGHT_SETUP_OLD + "        let mut recovery_windows = Vec::with_capacity(target_count.saturating_sub(1));\n"
FIGHT_AFTER_WINDOW_OLD = "            previous_health_damage_events = health_damage_events;\n"
FIGHT_AFTER_WINDOW_NEW = FIGHT_AFTER_WINDOW_OLD + """            if index + 1 < target_count && recovery_ns > 0 {
                recovery_windows.push(self.advance_paid_recovery(recovery_ns)?);
            }
"""
FIGHT_REPORT_OLD = '            "paid_recovery": false, "world_targets_killed": target_count,\n'
FIGHT_REPORT_NEW = """            "paid_recovery": recovery_ns > 0,
            "paid_recovery_ns_per_gap": recovery_ns,
            "paid_recovery_ns_total": recovery_ns * (target_count as i64 - 1),
            "recovery_mode": "native_scheduled_regeneration_only",
            "recovery_windows": recovery_windows,
            "world_targets_killed": target_count,
"""
FIGHT_CLOCK_OLD = """            && (if live_world { at_ns <= self.end_of_combat }
                else { at_ns == self.end_of_combat })
"""
FIGHT_CLOCK_NEW = "            && (live_world || at_ns == self.end_of_combat)\n"
FIGHT_CLOCK_COMMENT_OLD = """    /// Until paid downtime is implemented in the native session, accept only
    /// an immediate next pull; skipping scheduled recovery events is illegal.
"""
FIGHT_CLOCK_COMMENT_NEW = """    /// A live world may advance the retained actor through explicit paid
    /// recovery; begin_next_target still requires the committed lethal ACK.
"""
FIGHT_CLOCK_TEST_OLD = "        assert!(!fight.accepts_next_target_clock(cap + 1, cap + 2_000_000, true));"
FIGHT_CLOCK_TEST_NEW = "        assert!(fight.accepts_next_target_clock(cap + 1, cap + 2_000_000, true));"
FIGHT_NEXT_COMMENT_OLD = """                // No free actor reset. This intentionally retains the current
                // no-downtime diagnostic clock until real paid travel/recovery
                // is coupled through the same native/world timeline.
"""
FIGHT_NEXT_COMMENT_NEW = """                // The preceding explicit recovery interval has already advanced
                // this same actor and its native resource events on the world clock.
"""

CLASSES_SIGNATURE_OLD = """pub(crate) fn native_two_world_targets(
    prepared: &crate::contracts::prepared_v2::PreparedV2,
    target_count: usize,
) -> Result<serde_json::Value, String> {"""
CLASSES_SIGNATURE_NEW = """pub(crate) fn native_two_world_targets(
    prepared: &crate::contracts::prepared_v2::PreparedV2,
    target_count: usize,
    recovery_ns: i64,
) -> Result<serde_json::Value, String> {"""
CLASSES_CALL_OLD = ".native_two_world_targets(target_count).map_err(str::to_string)"
CLASSES_CALL_NEW = ".native_two_world_targets(target_count, recovery_ns).map_err(str::to_string)"

PREPARED_SIGNATURE_OLD = "pub fn native_two_world_targets(prepared: &PreparedV2, target_count: usize)"
PREPARED_SIGNATURE_NEW = "pub fn native_two_world_targets(prepared: &PreparedV2, target_count: usize, recovery_ns: i64)"
PREPARED_COUNT_OLD = """    if !(2..=100).contains(&target_count) {
        return Err(PreparedError::Invalid(
            "RUST_MULTI_WORLD_TARGET_COUNT_INVALID".to_owned()));
    }
"""
PREPARED_COUNT_NEW = PREPARED_COUNT_OLD + """    if !(0..=300_000_000_000).contains(&recovery_ns) {
        return Err(PreparedError::Invalid(
            "RUST_NATIVE_PAID_RECOVERY_DURATION_INVALID".to_owned()));
    }
"""
PREPARED_CALL_OLD = "crate::classes::native_two_world_targets(prepared, target_count)"
PREPARED_CALL_NEW = "crate::classes::native_two_world_targets(prepared, target_count, recovery_ns)"

CLI_OLD = """    if args[0] == "native-world-pulls" {
        if args.len() != 5 || args[1] != "--infile" || args[3] != "--targets" {
            return Err("native-world-pulls requires --infile PREPARED_V2.json --targets 2..100".into());
        }
        let target_count = args[4].parse::<usize>()
            .map_err(|_| "native-world-pulls target count must be an integer")?;
        if !(2..=100).contains(&target_count) {
            return Err("native-world-pulls requires --targets 2..100".into());
        }
        let input = fs::read(&args[2]).map_err(|err| err.to_string())?;
        let prepared = prepared_v2(&input)?
            .ok_or("native-world-pulls requires a prepared v2 input")?;
        let report = native_two_world_targets(&prepared, target_count)
            .map_err(|err| err.to_string())?;
        println!("{}", serde_json::json!({
            "engine": "forever-engine",
            "source_sha256": prepared.request_sha256,
            "result": report, "checkpoint_certified": false,
        }));
        return Ok(());
    }
"""
CLI_NEW = """    if args[0] == "native-world-pulls" {
        if !matches!(args.len(), 5 | 7)
            || args[1] != "--infile" || args[3] != "--targets"
            || (args.len() == 7 && args[5] != "--recovery-ns") {
            return Err("native-world-pulls requires --infile PREPARED_V2.json --targets 2..100 [--recovery-ns 0..300000000000]".into());
        }
        let target_count = args[4].parse::<usize>()
            .map_err(|_| "native-world-pulls target count must be an integer")?;
        if !(2..=100).contains(&target_count) {
            return Err("native-world-pulls requires --targets 2..100".into());
        }
        let recovery_ns = if args.len() == 7 {
            args[6].parse::<i64>()
                .map_err(|_| "native-world-pulls recovery must be integer nanoseconds")?
        } else {
            0
        };
        if !(0..=300_000_000_000).contains(&recovery_ns) {
            return Err("native-world-pulls requires --recovery-ns 0..300000000000".into());
        }
        let input = fs::read(&args[2]).map_err(|err| err.to_string())?;
        let prepared = prepared_v2(&input)?
            .ok_or("native-world-pulls requires a prepared v2 input")?;
        let report = native_two_world_targets(&prepared, target_count, recovery_ns)
            .map_err(|err| err.to_string())?;
        println!("{}", serde_json::json!({
            "engine": "forever-engine",
            "source_sha256": prepared.request_sha256,
            "result": report, "checkpoint_certified": false,
        }));
        return Ok(());
    }
"""


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(new) == 1 and source.count(old) == 0:
        return source
    if source.count(old) != 1 or new in source:
        raise ValueError(f"RUST_NATIVE_PAID_RECOVERY_{label}_ANCHOR_DRIFT")
    return source.replace(old, new, 1)


def port_queue(source: str) -> str:
    if QUEUE_METHOD_MARKER in source:
        if (source.count(QUEUE_METHOD_MARKER) != 1
                or source.count(QUEUE_TEST_MARKER) != 1):
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_QUEUE_PARTIAL")
        return source
    if source.count(QUEUE_ANCHOR) != 1 or source.count(QUEUE_TEST_ANCHOR) != 1:
        raise ValueError("RUST_NATIVE_PAID_RECOVERY_QUEUE_ANCHOR_DRIFT")
    source = source.replace(QUEUE_ANCHOR, QUEUE_METHOD + QUEUE_ANCHOR, 1)
    return source.replace(QUEUE_TEST_ANCHOR, QUEUE_TESTS + QUEUE_TEST_ANCHOR, 1)


def port_fight(source: str) -> str:
    if FIGHT_SIGNATURE_NEW in source:
        required = (
            FIGHT_HELPER_MARKER, '"paid_recovery_ns_total"', '"recovery_windows"',
            FIGHT_CLOCK_NEW.strip(), FIGHT_CLOCK_TEST_NEW,
        )
        if (any(source.count(marker) != 1 for marker in required)
                or FIGHT_SIGNATURE_OLD in source
                or FIGHT_CLOCK_OLD in source
                or FIGHT_CLOCK_TEST_OLD in source):
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_FIGHT_PARTIAL")
        return source
    if (source.count(FIGHT_SIGNATURE_OLD) != 1
            or source.count(FIGHT_METHOD_ANCHOR) != 1
            or source.count(FIGHT_SETUP_OLD) != 1
            or source.count(FIGHT_AFTER_WINDOW_OLD) != 1
            or source.count(FIGHT_REPORT_OLD) != 1
            or source.count(FIGHT_CLOCK_OLD) != 1
            or source.count(FIGHT_CLOCK_COMMENT_OLD) != 1
            or source.count(FIGHT_CLOCK_TEST_OLD) != 1
            or source.count(FIGHT_NEXT_COMMENT_OLD) != 1
            or FIGHT_HELPER_MARKER in source):
        raise ValueError("RUST_NATIVE_PAID_RECOVERY_FIGHT_ANCHOR_DRIFT")
    source = source.replace(FIGHT_SIGNATURE_OLD, FIGHT_SIGNATURE_NEW, 1)
    source = source.replace(FIGHT_METHOD_ANCHOR, FIGHT_HELPER + FIGHT_METHOD_ANCHOR, 1)
    source = source.replace(FIGHT_SETUP_OLD, FIGHT_SETUP_NEW, 1)
    source = source.replace(FIGHT_AFTER_WINDOW_OLD, FIGHT_AFTER_WINDOW_NEW, 1)
    source = source.replace(FIGHT_REPORT_OLD, FIGHT_REPORT_NEW, 1)
    source = source.replace(FIGHT_CLOCK_OLD, FIGHT_CLOCK_NEW, 1)
    source = source.replace(FIGHT_CLOCK_COMMENT_OLD, FIGHT_CLOCK_COMMENT_NEW, 1)
    source = source.replace(FIGHT_CLOCK_TEST_OLD, FIGHT_CLOCK_TEST_NEW, 1)
    source = source.replace(FIGHT_NEXT_COMMENT_OLD, FIGHT_NEXT_COMMENT_NEW, 1)
    return source


def is_composed_paid_recovery_source(source: str) -> bool:
    """Accept only the complete paid-recovery descendant with health and mana receipts."""
    try:
        if port_fight(source) != source:
            return False
    except ValueError:
        return False
    required = (
        FIGHT_SIGNATURE_NEW,
        FIGHT_HELPER_MARKER,
        '"paid_recovery_ns_total"',
        '"recovery_windows"',
        FIGHT_CLOCK_NEW.strip(),
        FIGHT_CLOCK_COMMENT_NEW.strip(),
        FIGHT_CLOCK_TEST_NEW,
        FIGHT_NEXT_COMMENT_NEW.strip(),
        '"native_health_damage_taken"',
        '"native_health_damage_events"',
        '"native_combat_mana_regen_actual_gain"',
        '"native_combat_mana_regen_events"',
    )
    return all(source.count(marker) == 1 for marker in required)


# The selected production Rust pin already requires explicit typed RNG.
# Recovery adds a separate duration; it must never drop the RNG argument.
RNG_TYPE = "crate::core::rng::RngMode"
CLASSES_SIGNATURE_TYPED_OLD = CLASSES_SIGNATURE_OLD.replace(
    "    target_count: usize,\n", "    target_count: usize,\n    rng_mode: " + RNG_TYPE + ",\n")
CLASSES_SIGNATURE_TYPED_NEW = CLASSES_SIGNATURE_TYPED_OLD.replace(
    "    rng_mode: " + RNG_TYPE + ",\n",
    "    rng_mode: " + RNG_TYPE + ",\n    recovery_ns: i64,\n")
PREPARED_SIGNATURE_TYPED_OLD = PREPARED_SIGNATURE_OLD.replace(
    "target_count: usize)", "target_count: usize, rng_mode: " + RNG_TYPE + ")")
PREPARED_SIGNATURE_TYPED_NEW = PREPARED_SIGNATURE_TYPED_OLD.replace(
    "rng_mode: " + RNG_TYPE + ")", "rng_mode: " + RNG_TYPE + ", recovery_ns: i64)")
PREPARED_CALL_TYPED_OLD = PREPARED_CALL_OLD.replace(
    "prepared, target_count)", "prepared, target_count, rng_mode)")
PREPARED_CALL_TYPED_NEW = PREPARED_CALL_TYPED_OLD.replace(
    "target_count, rng_mode)", "target_count, rng_mode, recovery_ns)")

CLI_TYPED_OLD = (CLI_OLD
    .replace('args.len() != 5 || args[1] != "--infile" || args[3] != "--targets"',
             'args.len() != 7 || args[1] != "--infile" || args[3] != "--targets" || args[5] != "--rng-mode"')
    .replace('let report = native_two_world_targets(&prepared, target_count)',
             'let mode = RngMode::parse_cli(&args[6])?;\n        let report = native_two_world_targets(&prepared, target_count, mode)'))
CLI_TYPED_NEW = (CLI_TYPED_OLD
    .replace('args.len() != 7 || args[1] != "--infile" || args[3] != "--targets" || args[5] != "--rng-mode"',
             '!matches!(args.len(), 7 | 9) || args[1] != "--infile" || args[3] != "--targets" || args[5] != "--rng-mode" || (args.len() == 9 && args[7] != "--recovery-ns")')
    .replace('let mode = RngMode::parse_cli(&args[6])?;',
             '''let mode = RngMode::parse_cli(&args[6])?;
        let recovery_ns = if args.len() == 9 {
            args[8].parse::<i64>().map_err(|_| "native-world-pulls recovery must be integer nanoseconds")?
        } else { 0 };
        if !(0..=300_000_000_000).contains(&recovery_ns) {
            return Err("native-world-pulls requires --recovery-ns 0..300000000000".into());
        }''')
    .replace('native_two_world_targets(&prepared, target_count, mode)',
             'native_two_world_targets(&prepared, target_count, mode, recovery_ns)'))


def port_classes(source: str) -> str:
    if CLASSES_SIGNATURE_TYPED_NEW in source:
        if (source.count(CLASSES_SIGNATURE_TYPED_NEW) != 1
                or source.count(CLASSES_CALL_NEW) != 9
                or CLASSES_SIGNATURE_TYPED_OLD in source or CLASSES_CALL_OLD in source):
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_TYPED_CLASSES_PARTIAL")
        return source
    if CLASSES_SIGNATURE_TYPED_OLD in source:
        if (source.count(CLASSES_SIGNATURE_TYPED_OLD) != 1
                or source.count(CLASSES_CALL_OLD) != 9
                or source.count("::fight(prepared, rng_mode)?.native_two_world_targets(target_count)") != 9):
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_TYPED_CLASSES_ANCHOR_DRIFT")
        return source.replace(CLASSES_SIGNATURE_TYPED_OLD, CLASSES_SIGNATURE_TYPED_NEW, 1).replace(
            CLASSES_CALL_OLD, CLASSES_CALL_NEW)
    if CLASSES_SIGNATURE_NEW in source:
        if (source.count(CLASSES_SIGNATURE_NEW) != 1
                or source.count(CLASSES_CALL_NEW) != 9
                or CLASSES_SIGNATURE_OLD in source
                or CLASSES_CALL_OLD in source):
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_CLASSES_PARTIAL")
        return source
    if source.count(CLASSES_SIGNATURE_OLD) != 1 or source.count(CLASSES_CALL_OLD) != 9:
        raise ValueError("RUST_NATIVE_PAID_RECOVERY_CLASSES_ANCHOR_DRIFT")
    source = source.replace(CLASSES_SIGNATURE_OLD, CLASSES_SIGNATURE_NEW, 1)
    return source.replace(CLASSES_CALL_OLD, CLASSES_CALL_NEW)


def port_prepared(source: str) -> str:
    if PREPARED_SIGNATURE_TYPED_NEW in source:
        if (source.count(PREPARED_SIGNATURE_TYPED_NEW) != 1
                or source.count(PREPARED_COUNT_NEW) != 1
                or source.count(PREPARED_CALL_TYPED_NEW) != 1
                or PREPARED_SIGNATURE_TYPED_OLD in source
                or PREPARED_CALL_TYPED_OLD in source):
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_TYPED_PREPARED_PARTIAL")
        return source
    if PREPARED_SIGNATURE_TYPED_OLD in source:
        if (source.count(PREPARED_SIGNATURE_TYPED_OLD) != 1
                or source.count(PREPARED_COUNT_OLD) != 1
                or source.count(PREPARED_CALL_TYPED_OLD) != 1):
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_TYPED_PREPARED_ANCHOR_DRIFT")
        return (source.replace(PREPARED_SIGNATURE_TYPED_OLD, PREPARED_SIGNATURE_TYPED_NEW, 1)
                .replace(PREPARED_COUNT_OLD, PREPARED_COUNT_NEW, 1)
                .replace(PREPARED_CALL_TYPED_OLD, PREPARED_CALL_TYPED_NEW, 1))
    if PREPARED_SIGNATURE_NEW in source:
        if (source.count(PREPARED_SIGNATURE_NEW) != 1
                or source.count(PREPARED_COUNT_NEW) != 1
                or source.count(PREPARED_CALL_NEW) != 1
                or PREPARED_SIGNATURE_OLD in source
                or source.count(PREPARED_COUNT_OLD) != 1
                or PREPARED_CALL_OLD in source):
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_PREPARED_PARTIAL")
        return source
    if (source.count(PREPARED_SIGNATURE_OLD) != 1
            or source.count(PREPARED_COUNT_OLD) != 1
            or source.count(PREPARED_CALL_OLD) != 1):
        raise ValueError("RUST_NATIVE_PAID_RECOVERY_PREPARED_ANCHOR_DRIFT")
    source = source.replace(PREPARED_SIGNATURE_OLD, PREPARED_SIGNATURE_NEW, 1)
    source = source.replace(PREPARED_COUNT_OLD, PREPARED_COUNT_NEW, 1)
    return source.replace(PREPARED_CALL_OLD, PREPARED_CALL_NEW, 1)


def port_main(source: str) -> str:
    if CLI_TYPED_NEW in source:
        if source.count(CLI_TYPED_NEW) != 1 or CLI_TYPED_OLD in source:
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_TYPED_CLI_PARTIAL")
        return source
    if CLI_TYPED_OLD in source:
        if source.count(CLI_TYPED_OLD) != 1:
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_TYPED_CLI_ANCHOR_DRIFT")
        return source.replace(CLI_TYPED_OLD, CLI_TYPED_NEW, 1)
    if CLI_NEW in source:
        if source.count(CLI_NEW) != 1 or CLI_OLD in source:
            raise ValueError("RUST_NATIVE_PAID_RECOVERY_CLI_PARTIAL")
        return source
    if source.count(CLI_OLD) != 1:
        raise ValueError("RUST_NATIVE_PAID_RECOVERY_CLI_ANCHOR_DRIFT")
    return source.replace(CLI_OLD, CLI_NEW, 1)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_paid_recovery.py RUST_ENGINE_ROOT")
    root = Path(argv[1]) / "src"
    edits = (
        (root / "core/queue.rs", port_queue),
        (root / "core/fight.rs", port_fight),
        (root / "classes.rs", port_classes),
        (root / "engine/prepared.rs", port_prepared),
        (root / "main.rs", port_main),
    )
    changed = 0
    for path, port in edits:
        before = path.read_text()
        after = port(before)
        if after != before:
            path.write_text(after)
            changed += 1
    print("RUST_NATIVE_PAID_RECOVERY_PORTED" if changed
          else "RUST_NATIVE_PAID_RECOVERY_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
