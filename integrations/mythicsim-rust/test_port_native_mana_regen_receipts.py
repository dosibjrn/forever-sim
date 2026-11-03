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

print("RUST_NATIVE_COMBAT_MANA_REGEN_RECEIPT_PORT_IDEMPOTENT_AND_FAIL_CLOSED")
