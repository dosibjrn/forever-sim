"""Real gsim HP perturbation is source-world input, not a native-only metric.

The paired pinned-Go run separately verifies whether the subsequent native
APL changes. These fast tests only protect actual gsim HP/ACK semantics.
"""
import pytest

from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world
from src.game.runtime.native_step_protocol import snapshot_gsim_world, state_hash
from src.game.runtime.go_native_world_damage_ack import GsimNativeDamageWorldApplier


def test_real_gsim_target_starts_partially_injured_before_first_native_tick():
    runtime = diagnostic_gsim_world(target_health=1000.,
                                    target_initial_health_fraction=0.15)
    world = snapshot_gsim_world(runtime)
    assert world["selected_target_id"] == "m1"
    assert world["enemies"]["m1"]["health"] == pytest.approx(150.)
    assert world["enemies"]["m1"]["alive"] is True
    assert runtime.targets["m1"].max_health == pytest.approx(1000.)


def test_source_native_effect_ack_preserves_actual_injured_world_hp():
    runtime = diagnostic_gsim_world(target_health=1000.,
                                    target_initial_health_fraction=0.15)
    before = snapshot_gsim_world(runtime)
    tick = {"sequence": 0, "clock_ms": 0, "native_clock_ns": 0,
            "selected_target_id": "m1", "world_sha256": state_hash(before)}
    event = {"event_id": "native-effect-1", "native_time_ns": 0,
             "source_action_id": "SpellID:8921", "rank": 2,
             "native_target_index": 0, "native_target_unit_index": 1,
             "native_target_label": "native-enemy", "damage": 75.,
             "landed": True, "crit": False, "periodic": False}
    response = {"sequence": 0, "native_process_id": 123,
                "observed_input_world_sha256": tick["world_sha256"],
                "native_damage_events": [event]}
    ack = GsimNativeDamageWorldApplier(runtime).apply(tick, response)
    assert ack["world_target_health_before"] == pytest.approx(150.)
    assert ack["world_target_health_after"] == pytest.approx(75.)
    assert ack["world_target_max_health"] == pytest.approx(1000.)
    assert runtime.targets["m1"].health == pytest.approx(75.)
    assert ack["world_after_sha256"] == state_hash(snapshot_gsim_world(runtime))


@pytest.mark.parametrize("fraction", [-1., 0., 1.01, float("nan"), float("inf")])
def test_invalid_world_health_fraction_fails_before_native_session(fraction):
    with pytest.raises(ValueError, match="INVALID_SOURCE_WORLD_TARGET_HEALTH"):
        diagnostic_gsim_world(target_initial_health_fraction=fraction)
