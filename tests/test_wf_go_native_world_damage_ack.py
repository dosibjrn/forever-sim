"""Real gsim HP mutation / source-native effect ACK contract; not P7."""
from __future__ import annotations
from copy import deepcopy
import math
import pytest

from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world
from src.game.runtime.native_step_protocol import snapshot_gsim_world, state_hash
from src.game.runtime.go_native_world_damage_ack import (
    GsimNativeDamageWorldApplier, NativeDamageWorldApplicationError,
)


def fixture():
    rt = diagnostic_gsim_world()
    world = snapshot_gsim_world(rt)
    tick = {"sequence": 0, "clock_ms": 0, "native_clock_ns": 0,
            "selected_target_id": "m1", "world_sha256": state_hash(world)}
    event = {"event_id": "native-effect-1", "native_time_ns": 0,
             "source_action_id": "SpellID:8921", "rank": 2,
             "native_target_index": 0, "native_target_unit_index": 1,
             "native_target_label": "native-enemy", "damage": 75.0,
             "landed": True, "crit": False, "periodic": False}
    native = {"sequence": 0, "native_process_id": 123,
              "observed_input_world_sha256": tick["world_sha256"],
              "native_damage_events": [event]}
    return rt, tick, native


def test_actual_gsim_health_changes_and_world_ack_is_measured():
    rt, tick, reply = fixture()
    before = rt.targets["m1"].health
    ack = GsimNativeDamageWorldApplier(rt).apply(tick, reply)
    assert rt.targets["m1"].health == before - 75
    assert ack["type"] == "gsim_native_damage_applied_ack"
    assert ack["applied_native_damage"] == 75
    assert ack["applied_event_ids"] == ["native-effect-1"]
    assert ack["world_after_sha256"] == state_hash(snapshot_gsim_world(rt))
    assert ack["world_after_sha256"] != ack["world_before_sha256"]


def test_real_native_lethal_overkill_kills_gsim_target_without_losing_source_damage():
    rt, tick, reply = fixture()
    target = rt.targets["m1"]
    target.health = 10.0
    target.max_health = 10.0
    tick["world_sha256"] = state_hash(snapshot_gsim_world(rt))
    reply["observed_input_world_sha256"] = tick["world_sha256"]
    ack = GsimNativeDamageWorldApplier(rt).apply(tick, reply)
    assert target.health == 0.0 and not target.alive
    assert ack["applied_native_damage"] == 75.0  # raw, not capped to 10
    assert ack["world_target_health_before"] == 10.0
    assert ack["world_target_health_after"] == 0.0
    assert ack["world_after_sha256"] == state_hash(snapshot_gsim_world(rt))


def test_replayed_effect_does_not_double_apply_world_damage():
    rt, tick, reply = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick, reply)
    after = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError):
        applier.apply(tick, reply)
    assert rt.targets["m1"].health == after


@pytest.mark.parametrize("mutate", [
    lambda n: n["native_damage_events"][0].update(native_target_index=1),
    lambda n: n["native_damage_events"][0].update(native_target_label=""),
    lambda n: n["native_damage_events"][0].update(source_action_id=""),
    lambda n: n["native_damage_events"][0].update(rank=-1),
    lambda n: n["native_damage_events"][0].update(rank=True),
    lambda n: n["native_damage_events"][0].update(landed=False),
    lambda n: n["native_damage_events"][0].update(crit="yes"),
    lambda n: n["native_damage_events"][0].update(periodic="false"),
    lambda n: n["native_damage_events"][0].update(damage=math.nan),
    lambda n: n["native_damage_events"][0].update(damage=-1),
    lambda n: n["native_damage_events"][0].update(damage=10**20),
    lambda n: n["native_damage_events"][0].update(native_time_ns=100_000_000),
    lambda n: n["native_damage_events"][0].update(event_id="fake-1"),
    lambda n: n.update(observed_input_world_sha256="forged"),
])
def test_forged_native_effect_rejected_before_health_change(mutate):
    rt, tick, response = fixture()
    original = rt.targets["m1"].health
    mutate(response)
    with pytest.raises(NativeDamageWorldApplicationError):
        GsimNativeDamageWorldApplier(rt).apply(tick, response)
    assert rt.targets["m1"].health == original



@pytest.mark.parametrize("bad_id", ["native-effect-2", "native-effect-999"])
def test_missing_source_native_event_id_rejected_before_world_mutation(bad_id):
    # Go's source journal increments event IDs exactly once per recorded event.
    # Skipping the first ordinal means the gsim world never saw an effect.
    rt, tick, reply = fixture()
    reply["native_damage_events"][0]["event_id"] = bad_id
    original_health = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError, match="EVENT_ID_GAP"):
        GsimNativeDamageWorldApplier(rt).apply(tick, reply)
    assert rt.targets["m1"].health == original_health


def test_missing_source_native_event_between_ticks_rejected_before_world_mutation():
    rt, tick0, reply0 = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick0, reply0)
    rt.advance_to(0.1)
    tick1 = {"sequence": 1, "clock_ms": 100, "native_clock_ns": 100_000_000,
             "selected_target_id": "m1",
             "world_sha256": state_hash(snapshot_gsim_world(rt))}
    reply1 = {"sequence": 1, "native_process_id": 123,
              "observed_input_world_sha256": tick1["world_sha256"],
              "native_damage_events": [{
                  **reply0["native_damage_events"][0],
                  "event_id": "native-effect-3",
                  "native_time_ns": 100_000_000,
              }]}
    original_health = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError, match="EVENT_ID_GAP"):
        applier.apply(tick1, reply1)
    assert rt.targets["m1"].health == original_health


def test_no_native_effect_does_not_claim_world_mutation():
    rt, tick, response = fixture()
    response["native_damage_events"] = []
    ack = GsimNativeDamageWorldApplier(rt).apply(tick, response)
    assert ack["applied_event_ids"] == []
    assert ack["world_before_sha256"] == ack["world_after_sha256"]
    assert ack["applied_native_damage"] == 0


def test_native_target_identity_change_rejected_before_gsim_mutation():
    rt, tick0, reply0 = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick0, reply0)
    rt.advance_to(0.1)
    tick1 = {"sequence": 1, "clock_ms": 100, "native_clock_ns": 100_000_000,
             "selected_target_id": "m1",
             "world_sha256": state_hash(snapshot_gsim_world(rt))}
    reply1 = {"sequence": 1, "native_process_id": 123,
              "observed_input_world_sha256": tick1["world_sha256"],
              "native_damage_events": [{
                  **reply0["native_damage_events"][0],
                  "event_id": "native-effect-2",
                  "native_time_ns": 100_000_000,
                  "native_target_label": "a-different-native-enemy",
              }]}
    previous_health = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError, match="SOURCE_EVENT_INVALID"):
        applier.apply(tick1, reply1)
    assert rt.targets["m1"].health == previous_health


def test_negative_native_event_time_rejected_before_world_mutation():
    # Go's source journal cannot emit a negative-time combat event.  The
    # first gsim tick is at t=0, so -1 must not pass an uninitialized clock.
    rt, tick, reply = fixture()
    reply["native_damage_events"][0]["native_time_ns"] = -1
    original_health = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError, match="SOURCE_EVENT_INVALID"):
        GsimNativeDamageWorldApplier(rt).apply(tick, reply)
    assert rt.targets["m1"].health == original_health


def test_native_event_older_than_last_acked_world_tick_rejected():
    # An empty ACK at t=100ms is a causal barrier. A subsequently reported
    # event at 50ms must not be applied retroactively at t=200ms, even when
    # its timestamp is >= the last event time (0ms).
    rt, tick0, reply0 = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick0, reply0)
    rt.advance_to(0.1)
    tick1 = {"sequence": 1, "clock_ms": 100, "native_clock_ns": 100_000_000,
             "selected_target_id": "m1",
             "world_sha256": state_hash(snapshot_gsim_world(rt))}
    reply1 = {"sequence": 1, "native_process_id": 123,
              "observed_input_world_sha256": tick1["world_sha256"],
              "native_damage_events": []}
    applier.apply(tick1, reply1)
    rt.advance_to(0.2)
    tick2 = {"sequence": 2, "clock_ms": 200, "native_clock_ns": 200_000_000,
             "selected_target_id": "m1",
             "world_sha256": state_hash(snapshot_gsim_world(rt))}
    reply2 = {"sequence": 2, "native_process_id": 123,
              "observed_input_world_sha256": tick2["world_sha256"],
              "native_damage_events": [{
                  **reply0["native_damage_events"][0],
                  "event_id": "native-effect-2",
                  "native_time_ns": 50_000_000,
              }]}
    original_health = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError, match="SOURCE_EVENT_INVALID"):
        applier.apply(tick2, reply2)
    assert rt.targets["m1"].health == original_health


@pytest.mark.parametrize("clock_ms,native_clock_ns,event_ns", [
    (100, 100_000_000, 50_000_000),  # Forged future tick accepts a future native event.
    (0, 100_000_000, 0),           # Go clock disagrees with actual gsim clock.
    (100, 0, 0),                   # Claimed world tick disagrees with actual gsim clock.
])
def test_native_tick_clock_must_match_live_gsim_before_damage(
        clock_ms, native_clock_ns, event_ns):
    rt, tick, reply = fixture()
    tick["clock_ms"] = clock_ms
    tick["native_clock_ns"] = native_clock_ns
    reply["native_damage_events"][0]["native_time_ns"] = event_ns
    before = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError,
                       match="WORLD_DAMAGE_ACK_WORLD_CLOCK_MISMATCH"):
        GsimNativeDamageWorldApplier(rt).apply(tick, reply)
    assert rt.targets["m1"].health == before


def test_empty_native_effect_cannot_ack_future_world_clock():
    rt, tick, reply = fixture()
    tick["clock_ms"] = 100
    tick["native_clock_ns"] = 100_000_000
    reply["native_damage_events"] = []
    before = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError,
                       match="WORLD_DAMAGE_ACK_WORLD_CLOCK_MISMATCH"):
        GsimNativeDamageWorldApplier(rt).apply(tick, reply)
    assert rt.targets["m1"].health == before
