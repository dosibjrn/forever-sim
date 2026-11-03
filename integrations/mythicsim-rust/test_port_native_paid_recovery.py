"""Fail-closed and idempotency tests for the selected-Rust paid-recovery port."""
import importlib.util
from pathlib import Path
import port_native_early_retarget as early_retarget
import port_native_persistent_target as persistent_target

spec = importlib.util.spec_from_file_location(
    "native_paid_recovery_port",
    Path(__file__).with_name("port_native_paid_recovery.py"))
port = importlib.util.module_from_spec(spec)
spec.loader.exec_module(port)

QUEUE = """
impl<T> PendingQueue<T> {
    /// Pop the next live action.
    pub(crate) fn pop(&mut self) -> Option<(i64, Handle, T)> { None }
}
#[cfg(test)]
mod tests {
    #[test]
    fn handles_from_before_a_clear_are_inert() {}
}
"""
queued = port.port_queue(QUEUE)
assert port.port_queue(queued) == queued
assert queued.count("pub(crate) fn pop_first_matching_before") == 1
assert queued.count("pop_first_matching_before_preserves_nonmatching_actions_and_order") == 1
assert "self.heap.extend(deferred);" in queued
for broken in (QUEUE.replace("/// Pop the next live action.", "/// unrelated"),
               QUEUE + QUEUE):
    try:
        port.port_queue(broken)
    except ValueError:
        pass
    else:
        raise AssertionError("RUST_NATIVE_PAID_RECOVERY_QUEUE_MUST_FAIL_CLOSED")

FIGHT = """
    /// Until paid downtime is implemented in the native session, accept only
    /// an immediate next pull; skipping scheduled recovery events is illegal.
    fn accepts_next_target_clock(&self, at_ns: i64, next_end_ns: i64,
        live_world: bool) -> bool
    {
        at_ns >= self.now && at_ns >= 0 && next_end_ns > at_ns
            && (if live_world { at_ns <= self.end_of_combat }
                else { at_ns == self.end_of_combat })
    }
    #[test]
    fn native_persistent_early_world_kill_clock_boundary() {
        assert!(!fight.accepts_next_target_clock(cap + 1, cap + 2_000_000, true));
    }
    /// Multiple distinct gsim world deaths on one retained source-Rust actor.
    pub(crate) fn native_two_world_targets(&mut self, target_count: usize)
        -> Result<serde_json::Value, &'static str>
    {
        let mut windows = Vec::with_capacity(target_count);
        let mut previous_damage = 0.0;
        let mut previous_health_damage = 0.0_f64;
        let mut previous_health_damage_events = 0;
        for index in 0..target_count {
            if index != 0 {
                // No free actor reset. This intentionally retains the current
                // no-downtime diagnostic clock until real paid travel/recovery
                // is coupled through the same native/world timeline.
                let next_at = self.now.checked_add(1_000_000);
            }
            let total_damage = self.encounter_damage_taken;
            windows.push(serde_json::json!({
                "index": index,
                "actor_health": self.player.health,
                "actor_mana": self.player.mana,
            }));
            previous_damage = total_damage;
            previous_health_damage = health_damage;
            previous_health_damage_events = health_damage_events;
        }
        let report = serde_json::json!({
            "paid_recovery": false, "world_targets_killed": target_count,
        });
    }
"""
fight = port.port_fight(FIGHT)
assert port.port_fight(fight) == fight
assert fight.count("fn advance_paid_recovery(&mut self, recovery_ns: i64)") == 1
assert fight.count('"paid_recovery_ns_total"') == 1
assert fight.count('"recovery_windows"') == 1
assert "self.queue.pop_first_matching_before" in fight
assert "live_world || at_ns == self.end_of_combat" in fight
assert "assert!(fight.accepts_next_target_clock(cap + 1" in fight
for broken in (FIGHT.replace("let mut windows = Vec::with_capacity(target_count);", ""),
               FIGHT.replace('"paid_recovery": false', '"forged_paid_recovery": false')):
    try:
        port.port_fight(broken)
    except ValueError:
        pass
    else:
        raise AssertionError("RUST_NATIVE_PAID_RECOVERY_FIGHT_MUST_FAIL_CLOSED")

print("RUST_NATIVE_PAID_RECOVERY_PORT_IDEMPOTENT_AND_FAIL_CLOSED")

# The paid-recovery port changes the early-retarget clock test. The earlier
# persistent-target port must still accept this exact composed descendant on
# the second source-port pass, while rejecting any partial/drifted extension.
source = FIGHT[FIGHT.index("    #[test]"):]
source = source.replace(
    early_retarget.TEST_MARKER, "fn fixture_clock_boundary()"
).replace(
    port.FIGHT_CLOCK_TEST_OLD,
    "        assert!(!fight.accepts_next_target_clock(cap + 2, cap + 2_000_000, true));",
)
method_anchor = "    /// Go " + chr(96) + "Simulation.reset" + chr(96) + " and " + chr(96) + "Environment.reset" + chr(96) + ".\n"
source += (
    "\n" + persistent_target.FIGHT_METHOD
    + method_anchor
    + persistent_target.FIGHT_TEST.rstrip("\n") + "\n"
)
source = early_retarget.port_source(source)
source = port.port_fight(source)
method_marker = "    pub(crate) fn begin_next_target(&mut self"
method_new = persistent_target.FIGHT_METHOD + method_anchor
assert persistent_target.replace_once(
    source, method_anchor, method_new, method_marker
) == source

test_anchor = "mod tests {\n    use super::{Mp5Path, Side, DEFENDERS, MAX_TARGETS};"
test_new = test_anchor + "\n\n" + persistent_target.FIGHT_TEST.rstrip("\n")
test_marker = "    fn native_persistent_next_target_retains_actor_and_native_queue()"
assert persistent_target.replace_once(
    source, test_anchor, test_new, test_marker
) == source

broken = source.replace(port.FIGHT_CLOCK_TEST_NEW, "        assert!(true);", 1)
try:
    persistent_target.replace_once(
        broken, method_anchor, method_new, method_marker
    )
except ValueError:
    pass
else:
    raise AssertionError("PERSISTENT_TARGET_PORT_MUST_REJECT_PAID_RECOVERY_DRIFT")

print("RUST_PERSISTENT_TARGET_PORT_ACCEPTS_EXACT_PAID_RECOVERY_DESCENDANT")
