"""Fail-closed, idempotent source-port regressions; not paid recovery acceptance."""
import importlib.util
from pathlib import Path

path = Path(__file__).with_name("port_native_mana_regen_receipts.py")
spec = importlib.util.spec_from_file_location("native_mana_regen_port", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

ORIGINAL = """
pub(crate) fn native_two_world_targets(&mut self, target_count: usize)
        -> Result<serde_json::Value, &'static str>
    {
        let mut previous_health_damage_events = 0;
        for index in 0..target_count {
            let health_damage_events = 0;
            windows.push(serde_json::json!({
                "native_health_damage_events": health_damage_events - previous_health_damage_events,
            }));
            previous_health_damage_events = health_damage_events;
        }
        let report = serde_json::json!({
            "scope": "test",
        });
    }
"""

changed = module.port(ORIGINAL)
assert changed != ORIGINAL
assert module.port(changed) == changed
assert changed.count('"native_combat_mana_regen_actual_gain"') == 1
assert changed.count('"native_combat_mana_regen_events"') == 1
assert "self.resources[self.mana_regen_casting].actual_gain" in changed
assert "self.resources[self.mana_regen_not_casting].actual_gain" in changed
assert "self.resources[self.mana_regen_casting].events" in changed
assert "self.resources[self.mana_regen_not_casting].events" in changed
assert "RUST_WORLD_MANA_REGEN_RECEIPT_NONMONOTONIC" in changed
assert '"scope": "test"' in changed

for bad in (
    ORIGINAL.replace("previous_health_damage_events = 0", "previous_health_damage_events = 1"),
    ORIGINAL.replace('"native_health_damage_events": health_damage_events - previous_health_damage_events,', ""),
    ORIGINAL + ORIGINAL,
    changed.replace('"native_combat_mana_regen_events"', '"forged_mana_regen_events"'),
    changed.replace("previous_mana_regen_events = mana_regen_events;", ""),
):
    try:
        module.port(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("RUST_MANA_REGEN_PORT_MUST_FAIL_CLOSED")

# The older two-world CLI port must remain idempotent after the later
# health and mana receipt ports have composed into its same Rust method.
health_spec = importlib.util.spec_from_file_location(
    "native_health_port",
    Path(__file__).with_name("port_native_health_damage_receipts.py"))
health_module = importlib.util.module_from_spec(health_spec)
health_spec.loader.exec_module(health_module)
world_spec = importlib.util.spec_from_file_location(
    "native_world_port",
    Path(__file__).with_name("port_native_two_world_cli.py"))
world_module = importlib.util.module_from_spec(world_spec)
world_spec.loader.exec_module(world_module)

world_method = world_module.FIGHT_METHOD
health_method = health_module.port(world_method)
mana_method = module.port(health_method)
enriched_source = mana_method + world_module.FIGHT_ANCHOR
assert world_module.insert(
    enriched_source, world_module.FIGHT_ANCHOR,
    world_module.METHOD_MARKER, world_method) == enriched_source
try:
    world_module.insert(
        enriched_source.replace(
            '"native_combat_mana_regen_events"',
            '"forged_mana_regen_events"'),
        world_module.FIGHT_ANCHOR,
        world_module.METHOD_MARKER, world_method)
except ValueError:
    pass
else:
    raise AssertionError("RUST_WORLD_PORT_MUST_REJECT_MANA_RECEIPT_DRIFT")

print("RUST_NATIVE_COMBAT_MANA_REGEN_RECEIPT_PORT_IDEMPOTENT_AND_FAIL_CLOSED")
