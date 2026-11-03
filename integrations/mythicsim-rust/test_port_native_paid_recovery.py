"""Fail-closed and idempotency tests for the selected-Rust paid-recovery port."""
import importlib.util
from pathlib import Path
import port_native_early_retarget as early_retarget
import port_native_persistent_target as persistent_target
import port_native_two_world_cli as two_world_cli

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
assert early_retarget.port_source(source) == source

broken_early_retarget = source.replace(port.FIGHT_CLOCK_NEW, "            && false\\n", 1)
try:
    early_retarget.port_source(broken_early_retarget)
except ValueError:
    pass
else:
    raise AssertionError("EARLY_RETARGET_PORT_MUST_REJECT_PAID_RECOVERY_DRIFT")

method_marker = "    pub(crate) fn begin_next_target(&mut self"
method_new = persistent_target.FIGHT_METHOD + method_anchor
assert persistent_target.replace_once(
    source, method_anchor, method_new, method_marker
) == source

# The production pin already uses explicit typed RNG in both injected tests.
typed_source = source.replace(
    "crate::classes::druid::agent::DruidAgent::fight(&prepared)",
    "crate::classes::druid::agent::DruidAgent::fight(&prepared, crate::core::rng::RngMode::Stochastic)",
)
assert typed_source.count("crate::core::rng::RngMode::Stochastic") == 2
assert early_retarget.port_source(typed_source) == typed_source
assert persistent_target.replace_once(
    typed_source, method_anchor, method_new, method_marker
) == typed_source

test_anchor = "mod tests {\n    use super::{Mp5Path, Side, DEFENDERS, MAX_TARGETS};"
test_new = test_anchor + "\n\n" + persistent_target.FIGHT_TEST.rstrip("\n")
test_marker = "    fn native_persistent_next_target_retains_actor_and_native_queue()"
assert persistent_target.replace_once(
    source, test_anchor, test_new, test_marker
) == source
assert persistent_target.replace_once(
    typed_source, test_anchor, test_new, test_marker
) == typed_source

broken = source.replace(port.FIGHT_CLOCK_TEST_NEW, "        assert!(true);", 1)
try:
    persistent_target.replace_once(
        broken, method_anchor, method_new, method_marker
    )
except ValueError:
    pass
else:
    raise AssertionError("PERSISTENT_TARGET_PORT_MUST_REJECT_PAID_RECOVERY_DRIFT")



# The base two-world CLI port must preserve the paid-recovery extension at
# each Rust API layer on its second source-port pass.
classes = (
    two_world_cli.CLASSES_ANCHOR + "\n"
    + port.CLASSES_SIGNATURE_NEW + "\n"
    + port.CLASSES_CALL_NEW * 9
)
assert two_world_cli.insert(
    classes, two_world_cli.CLASSES_ANCHOR, two_world_cli.CLASS_MARKER,
    two_world_cli.CLASS_METHOD,
) == classes

prepared = (
    two_world_cli.PREPARED_ANCHOR + "\n"
    + port.PREPARED_SIGNATURE_NEW + "\n"
    + port.PREPARED_COUNT_NEW + port.PREPARED_CALL_NEW
)
assert two_world_cli.insert(
    prepared, two_world_cli.PREPARED_ANCHOR, two_world_cli.PREPARED_MARKER,
    two_world_cli.PREPARED_METHOD,
) == prepared

cli_source = two_world_cli.CLI_ANCHOR + "\n" + port.CLI_NEW
assert two_world_cli.insert(
    cli_source, two_world_cli.CLI_ANCHOR, two_world_cli.CLI_MARKER,
    two_world_cli.CLI_METHOD,
) == cli_source

print("RUST_PERSISTENT_TARGET_PORT_ACCEPTS_EXACT_PAID_RECOVERY_DESCENDANT")


# The full multi-target source-port chain must be idempotent after native
# recovery extends all three call sites, not just the Rust fight method.
import port_native_two_world_cli as two_world
for marker, original, transform in (
    (two_world.CLASS_MARKER, two_world.CLASS_METHOD, port.port_classes),
    (two_world.PREPARED_MARKER, two_world.PREPARED_METHOD, port.port_prepared),
    (two_world.CLI_MARKER, two_world.CLI_METHOD, port.port_main),
):
    anchor = {
        two_world.CLASS_MARKER: two_world.CLASSES_ANCHOR,
        two_world.PREPARED_MARKER: two_world.PREPARED_ANCHOR,
        two_world.CLI_MARKER: two_world.CLI_ANCHOR,
    }[marker]
    # The real source port requires the unchanged downstream insertion anchor.
    transformed = anchor + "\n" + transform(original)
    assert two_world.insert(transformed, {
        two_world.CLASS_MARKER: two_world.CLASSES_ANCHOR,
        two_world.PREPARED_MARKER: two_world.PREPARED_ANCHOR,
        two_world.CLI_MARKER: two_world.CLI_ANCHOR,
    }[marker], marker, original) == transformed
    # Any partial source drift must fail closed, not silently pass as idempotent.
    broken = transformed.replace(
        {two_world.CLASS_MARKER: port.CLASSES_CALL_NEW,
         two_world.PREPARED_MARKER: port.PREPARED_CALL_NEW,
         two_world.CLI_MARKER: '--recovery-ns'}[marker], 'FORGED_PORT_DRIFT', 1)
    try:
        two_world.insert(broken, {
            two_world.CLASS_MARKER: two_world.CLASSES_ANCHOR,
            two_world.PREPARED_MARKER: two_world.PREPARED_ANCHOR,
            two_world.CLI_MARKER: two_world.CLI_ANCHOR,
        }[marker], marker, original)
    except ValueError:
        pass
    else:
        raise AssertionError(f"PAID_RECOVERY_COMPOSITION_DRIFT_NOT_REJECTED: {marker}")
print("RUST_NATIVE_PAID_RECOVERY_MULTI_TARGET_PORT_CHAIN_IDEMPOTENT")

# The selected Rust pin is already typed-RNG, unlike the legacy source-port
# fixtures above. Verify the exact native API composition and reject drift.
for marker, original, transform, anchor in (
    (two_world.CLASS_MARKER, two_world.CLASS_METHOD, port.port_classes,
     two_world.CLASSES_ANCHOR),
    (two_world.PREPARED_MARKER, two_world.PREPARED_METHOD, port.port_prepared,
     two_world.PREPARED_ANCHOR),
    (two_world.CLI_MARKER, two_world.CLI_METHOD, port.port_main,
     two_world.CLI_ANCHOR),
):
    typed = two_world.typed_rng_variant(marker, original)
    base = anchor + "\n" + typed
    assert two_world.insert(base, anchor, marker, original) == base
    paid = transform(base)
    assert paid != base
    assert transform(paid) == paid
    assert two_world.insert(paid, anchor, marker, original) == paid
    assert "rng_mode" in paid or "--rng-mode" in paid
    damaged = paid.replace(
        {two_world.CLASS_MARKER: port.CLASSES_CALL_NEW,
         two_world.PREPARED_MARKER: port.PREPARED_CALL_TYPED_NEW,
         two_world.CLI_MARKER: "--recovery-ns"}[marker],
        "FORGED_TYPED_RECOVERY_DRIFT", 1)
    try:
        two_world.insert(damaged, anchor, marker, original)
    except ValueError:
        pass
    else:
        raise AssertionError(f"RUST_TYPED_RECOVERY_DRIFT_NOT_REJECTED: {marker}")
print("RUST_TYPED_RNG_PAID_RECOVERY_COMPOSITION_PASS")
