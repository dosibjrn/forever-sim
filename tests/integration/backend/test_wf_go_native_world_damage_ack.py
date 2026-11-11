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


def test_buffered_events_after_world_death_are_consumed_without_postmortem_effects():
    # The native engine emits a complete tick batch before gsim can ACK the
    # first lethal hit. Preserve every source ordinal in the ACK, but do not
    # apply later overkill or control events to the dead world target.
    rt, tick, reply = fixture()
    target = rt.targets["m1"]
    target.health = target.max_health = 10.0
    rt.advance_to(0.1)
    tick.update(clock_ms=100, native_clock_ns=100_000_000,
                world_sha256=state_hash(snapshot_gsim_world(rt)))
    reply["observed_input_world_sha256"] = tick["world_sha256"]
    first = reply["native_damage_events"][0]
    reply["native_damage_events"] = [
        {**first, "native_time_ns": 0},
        {**first, "event_id": "native-effect-2",
         "native_time_ns": 100_000_000},
    ]
    reply["native_control_events"] = [{
        "event_id": "native-effect-3",
        "effect_kind": "control",
        "control_id": "root",
        "duration_ns": 1_000_000_000,
        "break_semantics_status": "unimplemented",
        "native_time_ns": 100_000_000,
        "damage": 0.0,
        "source_action_id": "SpellID: 339",
        "rank": 1,
        "landed": True,
        "crit": False,
        "periodic": False,
        "native_target_index": 0,
        "native_target_unit_index": 1,
        "native_target_label": "native-enemy",
        "native_caster_type": "",
        "native_caster_unit_index": 0,
        "native_caster_label": "",
    }]
    ack = GsimNativeDamageWorldApplier(rt).apply(tick, reply)
    assert target.health == 0.0 and not target.alive
    assert ack["applied_event_ids"] == [
        "native-effect-1", "native-effect-2", "native-effect-3"]
    assert ack["applied_damage_event_ids"] == [
        "native-effect-1", "native-effect-2"]
    assert ack["applied_native_damage"] == 150.0
    assert ack["world_target_health_before"] == 10.0
    assert ack["world_target_health_after"] == 0.0
    assert ack["acknowledged_control_event_ids"] == ["native-effect-3"]
    assert ack["applied_control_event_ids"] == []
    assert ack["acknowledged_control_events"][0]["world_application_status"] == (
        "discarded_after_target_death")
    assert "root" not in target.active_controls
    assert ack["world_after_sha256"] == state_hash(snapshot_gsim_world(rt))
    assert ack["world_after_sha256"] != ack["world_before_sha256"]


def test_simultaneous_lethal_native_hits_remain_atomic_on_gsim_target():
    # Same-timestamp native effects have no observed causal order; they may
    # legitimately overkill in one ACK without post-mortem time travel.
    rt, tick, reply = fixture()
    target = rt.targets["m1"]
    target.health = target.max_health = 10.0
    tick["world_sha256"] = state_hash(snapshot_gsim_world(rt))
    reply["observed_input_world_sha256"] = tick["world_sha256"]
    first = reply["native_damage_events"][0]
    reply["native_damage_events"] = [
        first, {**first, "event_id": "native-effect-2"},
    ]
    ack = GsimNativeDamageWorldApplier(rt).apply(tick, reply)
    assert target.health == 0.0 and not target.alive
    assert ack["applied_event_ids"] == ["native-effect-1", "native-effect-2"]
    assert ack["applied_native_damage"] == 150.0
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
    lambda n: n["native_damage_events"][0].update(damage="100000000000000000000"),
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



@pytest.mark.parametrize("with_damage", [False, True])
def test_native_process_restart_rejected_before_world_mutation(with_damage):
    # Two real gsim ticks share one retained source-native session. Reusing
    # plausible event ordinals from a different PID must never cross the ACK.
    rt, tick0, reply0 = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick0, reply0)
    rt.advance_to(0.1)
    tick1 = {"sequence": 1, "clock_ms": 100, "native_clock_ns": 100_000_000,
             "selected_target_id": "m1",
             "world_sha256": state_hash(snapshot_gsim_world(rt))}
    events = ([{**reply0["native_damage_events"][0],
                "event_id": "native-effect-2",
                "native_time_ns": 100_000_000}] if with_damage else [])
    restarted = {"sequence": 1, "native_process_id": 124,
                 "observed_input_world_sha256": tick1["world_sha256"],
                 "native_damage_events": events}
    before = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError,
                       match="WORLD_DAMAGE_ACK_NATIVE_PROCESS_RESTARTED"):
        applier.apply(tick1, restarted)
    assert rt.targets["m1"].health == before


def test_same_retained_native_process_can_ack_next_real_gsim_tick():
    rt, tick0, reply0 = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick0, reply0)
    rt.advance_to(0.1)
    tick1 = {"sequence": 1, "clock_ms": 100, "native_clock_ns": 100_000_000,
             "selected_target_id": "m1",
             "world_sha256": state_hash(snapshot_gsim_world(rt))}
    continued = {"sequence": 1, "native_process_id": 123,
                 "observed_input_world_sha256": tick1["world_sha256"],
                 "native_damage_events": [{**reply0["native_damage_events"][0],
                                           "event_id": "native-effect-2",
                                           "native_time_ns": 100_000_000}]}
    before = rt.targets["m1"].health
    ack = applier.apply(tick1, continued)
    assert ack["native_process_id"] == 123
    assert ack["applied_event_ids"] == ["native-effect-2"]
    assert rt.targets["m1"].health == before - 75



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


def test_precombat_negative_native_time_applies_at_first_world_ack():
    # Genuine native pre-pull effects may precede t=0. The first ACK keeps
    # their original source timestamps while applying real gsim world damage.
    rt, tick, reply = fixture()
    reply["native_damage_events"][0]["native_time_ns"] = -1
    original_health = rt.targets["m1"].health
    ack = GsimNativeDamageWorldApplier(rt).apply(tick, reply)
    assert rt.targets["m1"].health == original_health - 75
    assert ack["applied_events"][0]["native_time_ns"] == -1
    assert ack["applied_event_ids"] == ["native-effect-1"]
    assert ack["world_after_sha256"] == state_hash(snapshot_gsim_world(rt))


def test_negative_native_event_time_rejected_after_first_world_ack():
    # Pre-pull effects can only cross the first t=0 boundary. A subsequent
    # ACK must never smuggle a negative-time event into an advanced world.
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
                  "native_time_ns": -1,
              }]}
    original_health = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError, match="SOURCE_EVENT_INVALID"):
        applier.apply(tick1, reply1)
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


def test_real_gsim_world_applies_native_pet_damage_with_source_caster_identity():
    rt, tick, response = fixture()
    event = response["native_damage_events"][0]
    event.update(native_caster_type="pet", native_caster_unit_index=2,
                 native_caster_label="Imp")
    before = rt.targets["m1"].health
    ack = GsimNativeDamageWorldApplier(rt).apply(tick, response)
    assert rt.targets["m1"].health == before - event["damage"]
    assert ack["applied_events"][0]["native_caster_label"] == "Imp"
    assert ack["applied_events"][0]["native_caster_unit_index"] == 2


@pytest.mark.parametrize("bad_fields", [
    {"native_caster_type": "pet", "native_caster_label": ""},
    {"native_caster_type": "pet", "native_caster_unit_index": -1,
     "native_caster_label": "Imp"},
    {"native_caster_type": "pet", "native_caster_unit_index": True,
     "native_caster_label": "Imp"},
    {"native_caster_type": "enemy", "native_caster_label": "Imp"},
    {"native_caster_type": "", "native_caster_label": "Imp"},
])
def test_invalid_native_pet_provenance_cannot_change_gsim_health(bad_fields):
    rt, tick, response = fixture()
    response["native_damage_events"][0].update(bad_fields)
    before = rt.targets["m1"].health
    with pytest.raises(NativeDamageWorldApplicationError, match="SOURCE_EVENT_INVALID"):
        GsimNativeDamageWorldApplier(rt).apply(tick, response)
    assert rt.targets["m1"].health == before


def test_serial_world_retarget_requires_acknowledged_lethal_gsim_damage():
    rt, tick, reply = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick, reply)
    rt.select_target("m0")
    with pytest.raises(NativeDamageWorldApplicationError, match="NEXT_TARGET_NOT_READY"):
        applier.begin_next_world_target("m0")
    assert rt.targets["m1"].alive

    # Real source-effect overkill kills the first gsim target. Retargeting
    # retains the native process, event ordinals and world clock.
    rt2, tick2, reply2 = fixture()
    rt2.targets["m1"].health = 10.
    rt2.targets["m1"].max_health = 10.
    tick2["world_sha256"] = state_hash(snapshot_gsim_world(rt2))
    reply2["observed_input_world_sha256"] = tick2["world_sha256"]
    second = GsimNativeDamageWorldApplier(rt2)
    second.apply(tick2, reply2)
    rt2.engage_target("m0")
    rt2.select_target("m0")
    second.begin_next_world_target("m0")
    rt2.advance_to(.1)
    world = snapshot_gsim_world(rt2)
    next_tick = {"sequence": 1, "clock_ms": 100, "native_clock_ns": 100_000_000,
                 "selected_target_id": "m0", "world_sha256": state_hash(world)}
    next_reply = {"sequence": 1, "native_process_id": 123,
                  "observed_input_world_sha256": next_tick["world_sha256"],
                  "native_damage_events": [{**reply2["native_damage_events"][0],
                                            "event_id": "native-effect-2",
                                            "native_time_ns": 100_000_000}]}
    old = rt2.targets["m0"].health
    ack = second.apply(next_tick, next_reply)
    assert rt2.targets["m0"].health == old - 75
    assert ack["applied_event_ids"] == ["native-effect-2"]



def test_external_world_death_cannot_authorize_native_target_transfer():
    """RED on the old applier: dead gsim HP was enough without native lethal ACK."""
    rt, tick, reply = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick, reply)  # Real ACK, but native hit was nonlethal.
    assert rt.targets["m1"].alive
    # The world changes HP independently; the native effect did NOT kill it.
    rt.targets["m1"].apply_damage(rt.targets["m1"].health)
    assert not rt.targets["m1"].alive
    rt.engage_target("m0")
    rt.select_target("m0")
    with pytest.raises(NativeDamageWorldApplicationError,
                       match="WORLD_DAMAGE_ACK_NEXT_TARGET_NOT_NATIVE_LETHAL"):
        applier.begin_next_world_target("m0")
    assert rt.targets["m0"].alive
    assert applier._target_id == "m1"




def test_next_world_target_cannot_receive_old_native_damage_from_before_handoff():
    """Native damage at 50 ms cannot hit a world target first engaged at 100 ms."""
    rt, first_tick, first_reply = fixture()
    rt.targets["m1"].health = 10.0
    rt.targets["m1"].max_health = 10.0
    first_tick["world_sha256"] = state_hash(snapshot_gsim_world(rt))
    first_reply["observed_input_world_sha256"] = first_tick["world_sha256"]
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(first_tick, first_reply)
    assert not rt.targets["m1"].alive

    # Paid world time passes before the second distinct gsim target is engaged.
    rt.advance_to(0.1)
    rt.engage_target("m0")
    rt.select_target("m0")
    applier.begin_next_world_target("m0")
    rt.advance_to(0.2)
    second_tick = {
        "sequence": 1, "clock_ms": 200, "native_clock_ns": 200_000_000,
        "selected_target_id": "m0",
        "world_sha256": state_hash(snapshot_gsim_world(rt)),
    }
    second_reply = {
        "sequence": 1, "native_process_id": 123,
        "observed_input_world_sha256": second_tick["world_sha256"],
        "native_damage_events": [{
            **first_reply["native_damage_events"][0],
            "event_id": "native-effect-2",
            "native_time_ns": 50_000_000,  # valid old ACK time, not valid new target time
        }],
    }
    before = rt.targets["m0"].health
    with pytest.raises(NativeDamageWorldApplicationError,
                       match="WORLD_DAMAGE_ACK_EVENT_BEFORE_TARGET_HANDOFF"):
        applier.apply(second_tick, second_reply)
    assert rt.targets["m0"].health == before



def test_source_native_damage_cannot_apply_to_unselected_real_gsim_target():
    # The native target slot belongs to the actual gsim selected target.
    # A forged tick may carry the correct world hash, PID, event and time,
    # but must not redirect source-native damage to a different live mob.
    rt, tick, reply = fixture()
    assert snapshot_gsim_world(rt)["selected_target_id"] == "m1"
    assert rt.targets["m0"].alive and rt.targets["m1"].alive
    tick["selected_target_id"] = "m0"
    before = {key: target.health for key, target in rt.targets.items()}
    with pytest.raises(NativeDamageWorldApplicationError,
                       match="WORLD_DAMAGE_ACK_TARGET_NOT_SELECTED"):
        GsimNativeDamageWorldApplier(rt).apply(tick, reply)
    assert {key: target.health for key, target in rt.targets.items()} == before


def _native_second_tick(rt, previous, *, sequence, native_events):
    rt.advance_to(sequence * 0.1)
    snap = snapshot_gsim_world(rt)
    tick = {
        "sequence": sequence, "clock_ms": sequence * 100,
        "native_clock_ns": sequence * 100_000_000,
        "selected_target_id": snap["selected_target_id"],
        "world_sha256": state_hash(snap),
    }
    return tick, {
        "sequence": sequence, "native_process_id": 123,
        "observed_input_world_sha256": tick["world_sha256"],
        "native_damage_events": native_events,
    }


def test_two_live_gsim_targets_keep_old_native_dot_and_distinct_lethal_acks():
    rt, tick, first = fixture()
    rt.targets["m1"].health = rt.targets["m1"].max_health = 100.0
    tick["world_sha256"] = state_hash(snapshot_gsim_world(rt))
    first["observed_input_world_sha256"] = tick["world_sha256"]
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick, first)  # First mob remains alive at 25 HP.
    assert rt.targets["m1"].alive

    rt.engage_target("m0")
    rt.select_target("m0")
    applier.begin_overlapping_world_target("m0", native_target_index=1)
    assert rt.targets["m0"].alive and rt.targets["m1"].alive

    original = first["native_damage_events"][0]
    tick1, response1 = _native_second_tick(rt, first, sequence=1, native_events=[
        {**original, "event_id": "native-effect-2",
         "native_time_ns": 100_000_000, "periodic": True,
         "damage": 30.0},  # Original target dies from its continuing DoT.
        {**original, "event_id": "native-effect-3",
         "native_time_ns": 100_000_000, "native_target_index": 1,
         "native_target_unit_index": 2, "native_target_label": "second-mob",
         "damage": 40.0},
    ])
    ack1 = applier.apply(tick1, response1)
    assert not rt.targets["m1"].alive and rt.targets["m0"].alive
    assert ack1["selected_native_target_index"] == 1
    assert [row["world_target_id"] for row in ack1["native_target_health_acks"]] == [
        "m1", "m0"]
    assert ack1["native_target_health_acks"][0]["world_target_health_after"] == 0
    assert ack1["native_target_health_acks"][1]["world_target_health_after"] > 0
    assert ack1["applied_event_ids"] == ["native-effect-2", "native-effect-3"]

    tick2, response2 = _native_second_tick(rt, first, sequence=2, native_events=[
        {**original, "event_id": "native-effect-4",
         "native_time_ns": 200_000_000, "native_target_index": 1,
         "native_target_unit_index": 2, "native_target_label": "second-mob",
         "damage": rt.targets["m0"].health + 10.0},
    ])
    ack2 = applier.apply(tick2, response2)
    assert not rt.targets["m0"].alive and not rt.targets["m1"].alive
    assert ack2["native_target_health_acks"][0]["world_target_id"] == "m0"
    assert ack2["native_target_health_acks"][0]["world_target_health_after"] == 0
    assert ack2["world_after_sha256"] == state_hash(snapshot_gsim_world(rt))


def test_overlapping_world_handoff_refuses_unacked_or_unengaged_second_mob():
    rt, tick, reply = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    rt.select_target("m0")
    with pytest.raises(NativeDamageWorldApplicationError, match="OVERLAP_SLOT_INVALID"):
        applier.begin_overlapping_world_target("m0")
    rt.select_target("m1")
    applier.apply(tick, reply)
    # The legacy diagnostic world starts BOTH mobs engaged, so explicitly
    # remove the second mob's engagement for this negative world-state test.
    rt._engaged_targets.discard("m0")
    rt.select_target("m0")
    with pytest.raises(NativeDamageWorldApplicationError, match="OVERLAP_NOT_TWO_LIVE"):
        applier.begin_overlapping_world_target("m0")
    assert rt.targets["m0"].alive and rt.targets["m1"].alive


def test_unbound_native_second_target_rejected_atomically_before_old_dot_applies():
    rt, tick, response = fixture()
    original = response["native_damage_events"][0]
    response["native_damage_events"] = [
        original,
        {**original, "event_id": "native-effect-2",
         "native_target_index": 1, "native_target_unit_index": 2,
         "native_target_label": "second-mob"},
    ]
    before = {key: mob.health for key, mob in rt.targets.items()}
    with pytest.raises(NativeDamageWorldApplicationError, match="SOURCE_EVENT_INVALID"):
        GsimNativeDamageWorldApplier(rt).apply(tick, response)
    assert {key: mob.health for key, mob in rt.targets.items()} == before



def test_serial_handoff_cannot_erase_still_live_old_dot_target():
    rt, tick0, reply0 = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick0, reply0)  # m1 remains alive.
    rt.engage_target("m0")
    rt.select_target("m0")
    applier.begin_overlapping_world_target("m0")
    # The selected new target dies, while the original target still has
    # its own native DoTs and distinct world identity.
    source_event = reply0["native_damage_events"][0]
    tick1, reply1 = _native_second_tick(rt, reply0, sequence=1, native_events=[
        {**source_event, "event_id": "native-effect-2",
         "native_time_ns": 100_000_000, "native_target_index": 1,
         "native_target_unit_index": 2, "native_target_label": "second-mob",
         "damage": rt.targets["m0"].health + 1.0},
    ])
    ack = applier.apply(tick1, reply1)
    assert not rt.targets["m0"].alive and rt.targets["m1"].alive
    assert ack["native_target_health_acks"][0]["world_target_id"] == "m0"
    rt.select_target("m1")
    with pytest.raises(NativeDamageWorldApplicationError,
                       match="PREVIOUS_NATIVE_TARGET_STILL_LIVE"):
        applier.begin_next_world_target("m1")
    assert applier._native_target_ids == {0: "m1", 1: "m0"}


def test_acknowledged_dead_selected_b_does_not_block_old_a_dot_continuation():
    """A native-selected dead B is not a reason to discard live A's effects."""
    rt, tick0, reply0 = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick0, reply0)  # A is still alive after its first hit.
    assert rt.targets["m1"].alive

    rt.engage_target("m0")
    rt.select_target("m0")
    applier.begin_overlapping_world_target("m0")
    source = reply0["native_damage_events"][0]
    tick1, reply1 = _native_second_tick(rt, reply0, sequence=1, native_events=[
        {**source, "event_id": "native-effect-2",
         "native_time_ns": 100_000_000, "native_target_index": 1,
         "native_target_unit_index": 2, "native_target_label": "second-mob",
         "damage": rt.targets["m0"].health + 1.0},
    ])
    first_ack = applier.apply(tick1, reply1)
    assert first_ack["native_target_health_acks"][0]["world_target_id"] == "m0"
    assert rt.targets["m0"].health == 0
    assert rt.targets["m1"].alive

    # Real B lethal ACK authorizes the next source-world range tick while
    # selected B is dead. Both tick and pending receipt recheck must use
    # the same native slot -> real 2D target ancestry; old A remains alive.
    from src.game.runtime.go_world_range_feed import GsimGoRangeFeed
    feed = GsimGoRangeFeed(rt, native_player_index=0)
    rt.advance_to(0.2)
    assert applier.is_native_acked_dead_selected_overlap("m0")
    range_tick = feed.next_tick(native_world_applier=applier)
    assert range_tick["selected_target_id"] == "m0"
    assert range_tick["world_target_health_before"] == 0
    assert range_tick["world_target_max_health"] == rt.targets["m0"].max_health
    range_receipt = {
        "sequence": range_tick["sequence"],
        "native_clock_ns": range_tick["native_clock_ns"],
        "player_index": range_tick["native_player_index"],
        "applied_yards": range_tick["distance_yards"],
        "native_encounter_damage": 0.,
        "facing_applied": range_tick["facing_applied"],
        "in_front_of_target": range_tick.get("in_front_of_target", False),
    }
    assert feed.accept_range_receipt(range_receipt)["checkpoint_certified"] is False

    # Rust still selects B, but the authentic source DoT is bound to A/slot 0.
    remaining = rt.targets["m1"].health
    tick2, reply2 = _native_second_tick(rt, reply0, sequence=2, native_events=[
        {**source, "event_id": "native-effect-3",
         "native_time_ns": 200_000_000, "periodic": True,
         "damage": min(10.0, remaining / 2)},
    ])
    second_ack = applier.apply(tick2, reply2)
    assert second_ack["selected_native_target_index"] == 1
    assert second_ack["world_target_health_before"] == 0
    assert second_ack["world_target_health_after"] == 0
    assert second_ack["native_target_health_acks"][0]["world_target_id"] == "m1"
    assert rt.targets["m1"].health < remaining
    assert rt.targets["m0"].health == 0

    tick3, reply3 = _native_second_tick(rt, reply0, sequence=3, native_events=[
        {**source, "event_id": "native-effect-4",
         "native_time_ns": 300_000_000, "periodic": True,
         "damage": rt.targets["m1"].health + 1.0},
    ])
    third_ack = applier.apply(tick3, reply3)
    assert third_ack["native_target_health_acks"][0]["world_target_id"] == "m1"
    assert third_ack["native_target_health_acks"][0]["world_target_health_after"] == 0
    assert not rt.targets["m1"].alive and not rt.targets["m0"].alive
    assert applier._last_native_lethal_target_id == "m0"


def test_predead_selected_b_cannot_admit_old_a_dot_without_native_b_ack():
    rt, tick0, reply0 = fixture()
    applier = GsimNativeDamageWorldApplier(rt)
    applier.apply(tick0, reply0)
    rt.engage_target("m0")
    rt.select_target("m0")
    applier.begin_overlapping_world_target("m0")
    # gsim reports dead B, but *no native event* ever killed it.
    rt.targets["m0"].apply_damage(rt.targets["m0"].health + 1)
    tick1, reply1 = _native_second_tick(rt, reply0, sequence=1, native_events=[
        {**reply0["native_damage_events"][0],
         "event_id": "native-effect-2", "native_time_ns": 100_000_000,
         "periodic": True},
    ])
    before = rt.targets["m1"].health
    from src.game.runtime.go_world_range_feed import GsimGoRangeFeed, GoWorldRangeError
    feed = GsimGoRangeFeed(rt, native_player_index=0)
    assert not applier.is_native_acked_dead_selected_overlap("m0")
    with pytest.raises(GoWorldRangeError, match="WORLD_SELECTED_TARGET_NOT_ALIVE"):
        feed.next_tick(native_world_applier=applier)
    with pytest.raises(NativeDamageWorldApplicationError,
                       match="WORLD_DAMAGE_ACK_TARGET_ALREADY_DEAD"):
        applier.apply(tick1, reply1)
    assert rt.targets["m1"].health == before
