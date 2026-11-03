"""Bounded fail-closed tests for the source-Rust damage-receipt patch."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "native_health_port",
    Path(__file__).with_name("port_native_health_damage_receipts.py"))
port_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(port_module)

ORIGINAL = """
pub(crate) fn native_two_world_targets(&mut self, target_count: usize)
        -> Result<serde_json::Value, &'static str>
    {
        let mut previous_damage = 0.0;
        for index in 0..target_count {
            let total_damage = self.encounter_damage_taken;
            windows.push(serde_json::json!({
                "index": index,
                "actor_health": self.player.health,
            }));
            previous_damage = total_damage;
        }
        let report = serde_json::json!({
            "scope": "test",
        });
    }
"""

modified = port_module.port(ORIGINAL)
assert port_module.port(modified) == modified
assert modified.count('"native_health_damage_taken"') == 1
assert modified.count('"native_health_damage_events"') == 1
assert "self.resources[self.damage_taken_health].gain" in modified
assert "self.resources[self.damage_taken_health].events" in modified
assert "RUST_WORLD_HEALTH_DAMAGE_RECEIPT_NONMONOTONIC" in modified
assert '"scope": "test"' in modified
assert modified.replace('        let report = serde_json::json!({', '').endswith('    }\n')
for broken in (ORIGINAL.replace('previous_damage = 0.0', 'previous_damage = 1.0'),
               ORIGINAL.replace('"actor_health": self.player.health,', ''),
               ORIGINAL + ORIGINAL):
    try:
        port_module.port(broken)
    except ValueError:
        pass
    else:
        raise AssertionError("RUST_NATIVE_HEALTH_RECEIPT_MUST_FAIL_CLOSED")
print("RUST_NATIVE_HEALTH_DAMAGE_PORT_IDEMPOTENT_AND_FAIL_CLOSED")
