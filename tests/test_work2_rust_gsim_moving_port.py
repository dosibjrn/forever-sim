"""Guard the exact selected-Rust gsim movement ingress port (not gate PASS)."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _port():
    script = Path(__file__).resolve().parents[1] / "integrations/mythicsim-rust/port_native_gsim_moving.py"
    spec = spec_from_file_location("work2_rust_gsim_moving", script)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BRIDGE = '''pub(crate) fn exchange(clock_ns: i64, duration_ns: i64, cumulative_damage: f64) -> (f64, bool) {
    let front = tick["in_front_of_target"].as_bool()
        .expect("RUST_WORLD_FACING_NOT_PROVIDED");
        "facing_applied": true, "in_front_of_target": front
    (distance, front)
}
'''

FIGHT = '''                let (distance, front) = world_bridge::exchange(
                    boundary, self.duration, self.encounter_damage_taken);
                if self.config.melee.in_front_of_target != front {
                    self.config.melee.in_front_of_target = front;
                    self.changed(reads::CASTS);
                }
                return true;
'''


def test_moving_port_rewrites_both_source_runtime_boundaries_once():
    port = _port()
    bridge = port.port_bridge(BRIDGE)
    fight = port.port_fight(FIGHT)
    assert 'tick["gsim_player_moving"].as_bool()' in bridge
    assert '"gsim_player_moving": moving' in bridge
    assert "(distance, front, moving)" in bridge
    assert "self.player.moving = moving;" in fight
    assert "self.changed(reads::CASTS);" in fight
    assert port.port_bridge(bridge) == bridge
    assert port.port_fight(fight) == fight


def test_moving_port_fails_closed_when_selected_source_drifted():
    with pytest.raises(ValueError, match="RUST_WORLD_MOVING_SIGNATURE_ANCHOR_DRIFT"):
        _port().port_bridge(BRIDGE.replace("-> (f64, bool)", "-> f64"))
