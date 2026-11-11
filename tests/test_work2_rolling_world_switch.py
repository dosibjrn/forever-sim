"""Source-shaped rolling 2D transport regressions, not a paid native overlap."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import runpy

import pytest

from tools.wf_gsim_go_live_range_probe import diagnostic_gsim_world


ROOT = Path(__file__).resolve().parents[1]
_bridge = runpy.run_path(str(
    ROOT / "integrations/mythicsim-rust/live_two_world_pulls.py"))
admit = _bridge["_source_acked_rolling_switch"]
new_kills = _bridge["_new_source_acked_world_kills"]


def two_live_world():
    world = diagnostic_gsim_world()
    world.engage_target("m1")
    world.select_target("m1")
    world.targets["m1"].health = world.targets["m1"].max_health * 0.45
    assert world.targets["m0"].alive
    return world


def source_switch(world):
    return {
        "from_native_target_index": 0, "to_native_target_index": 1,
        "prior_world_target_id": "m1",
        "prior_world_target_health": world.targets["m1"].health,
        "prior_world_target_max_health": world.targets["m1"].max_health,
        "prior_world_ack_id": "a" * 64,
        "source_ack_sequence": 1,
        "switch_native_clock_ns": 100_000_000,
        "health_fraction_at_most": 0.5,
    }


def accepted(world, source):
    return admit(
        source, world=world, old_id="m1", new_id="m0",
        previous_ack="a" * 64, source_sequence=1,
        last_clock_ns=100_000_000, boundary_clock_ns=200_000_000)


def test_source_acked_45_percent_b_acquisition_retains_two_live_world_ids():
    world = two_live_world()
    switch = source_switch(world)
    assert accepted(world, switch) == switch
    assert world.targets["m1"].alive and world.targets["m0"].alive
    # Source validation does not itself engage, select or move an enemy.
    assert world.selected_target_id == "m1"


@pytest.mark.parametrize("key,value", [
    ("from_native_target_index", 1),
    ("to_native_target_index", 0),
    ("prior_world_target_id", "forged"),
    ("prior_world_ack_id", "b" * 64),
    ("source_ack_sequence", 0),
    ("switch_native_clock_ns", 99_000_000),
    ("switch_native_clock_ns", 201_000_000),
    ("health_fraction_at_most", 0.6),
    ("prior_world_target_health", -1),
    ("prior_world_target_max_health", 0),
])
def test_unacked_early_b_switch_fails_without_mutating_world(key, value):
    world = two_live_world()
    source = source_switch(world)
    source[key] = value
    before = (world.selected_target_id, world.targets["m0"].alive,
              world.targets["m1"].health)
    with pytest.raises(AssertionError, match="RUST_WORLD_OVERLAP_SOURCE_SWITCH_UNACKED"):
        accepted(world, source)
    assert before == (world.selected_target_id, world.targets["m0"].alive,
                      world.targets["m1"].health)


def test_above_half_hp_or_preengaged_b_cannot_be_authorized_by_python():
    world = two_live_world()
    world.targets["m1"].health = world.targets["m1"].max_health * 0.75
    with pytest.raises(AssertionError, match="SOURCE_SWITCH_UNACKED"):
        accepted(world, source_switch(world))
    world = two_live_world()
    world.engage_target("m0")
    with pytest.raises(AssertionError, match="SOURCE_SWITCH_UNACKED"):
        accepted(world, source_switch(world))


def test_selected_b_die_first_then_old_a_dot_kill_tracks_two_real_ids():
    world = two_live_world()
    world.engage_target("m0")
    world.select_target("m0")
    before = {name: world.targets[name].health for name in ("m1", "m0")}
    world.targets["m0"].apply_damage(before["m0"])
    ack_b = {
        "world_after_sha256": "b" * 64,
        "native_target_health_acks": [{
            "native_target_index": 1, "world_target_id": "m0",
            "world_target_health_before": before["m0"],
            "world_target_health_after": 0.0,
        }],
    }
    first = new_kills(world=world, before=before, ack=ack_b,
                      clock_ns=300_000_000, overlap=True)
    assert [row["target_id"] for row in first] == ["m0"]

    before = {name: world.targets[name].health for name in ("m1", "m0")}
    world.targets["m1"].apply_damage(before["m1"])
    ack_a = {
        "world_after_sha256": "c" * 64,
        "native_target_health_acks": [{
            "native_target_index": 0, "world_target_id": "m1",
            "world_target_health_before": before["m1"],
            "world_target_health_after": 0.0,
        }],
    }
    second = new_kills(world=world, before=before, ack=ack_a,
                       clock_ns=400_000_000, overlap=True)
    assert [row["target_id"] for row in first + second] == ["m0", "m1"]
    assert len({row["ack_sha256"] for row in first + second}) == 2


def test_indexless_or_wrong_world_lethal_cannot_be_recorded():
    world = two_live_world()
    before = {name: world.targets[name].health for name in ("m1", "m0")}
    world.targets["m1"].apply_damage(before["m1"])
    ack = {"world_after_sha256": "c" * 64,
           "native_target_health_acks": []}
    with pytest.raises(AssertionError, match="KILL_NOT_INDEX_ACKED"):
        new_kills(world=world, before=before, ack=ack,
                  clock_ns=500_000_000, overlap=True)
    forged = deepcopy(ack)
    forged["native_target_health_acks"] = [{
        "native_target_index": 0,
        "world_target_id": "m0",
        "world_target_health_before": before["m1"],
        "world_target_health_after": 0,
    }]
    with pytest.raises(AssertionError, match="KILL_NOT_INDEX_ACKED"):
        new_kills(world=world, before=before, ack=forged,
                  clock_ns=500_000_000, overlap=True)
