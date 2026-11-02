"""P3 source raw chance stats really change paid gear and CombatRuntime.

No mock combat, artificial weights, or invented stat conversion constants.
The old source-backed item rating adapter owns chance meanings.
"""
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3_ratings import (
    source_item_stat_to_combat,
)
from src.game.gear import apply_stat_delta, apply_gear_selection
from src.game.runtime import ActorState
from src.game.model.ir import DamageEffect
from src.rulesets.forever.items.runtime_selection import available_items, item_vector
from tools.wf_gate_p2_live import _action_runtime_probe


def _actual_druid():
    ir = build_game_ir_slice(class_key="druid", level=60)
    assert ir is not None
    return ir


def _offensive_cast(ir):
    # Real canonical source action, no synthetic damage effect constructed.
    for action in ir.actions:
        if any(isinstance(e, DamageEffect) and
               str(e.school).lower() != "physical"
               and e.crit_multiplier > 1 for e in action.effects):
            probe = _action_runtime_probe(
                ir, action, target_spell_hit=.5, capture_source_hit=True)
            if probe and probe["direct_damage"] > 0:
                return action, probe
    raise AssertionError("NO_EXECUTABLE_SOURCED_MAGIC_DAMAGE_ACTION")


def test_crit_and_hit_raw_gear_axes_exist_on_actual_source_items():
    rows = available_items("druid", 60, required_level_policy="catalogue")
    for axis in ("crit", "hit", "dodge"):
        row = next((item for item in rows if getattr(item, axis, 0) > 0), None)
        assert row is not None, f"NO_SOURCED_ITEM_WITH_{axis}"
        assert item_vector(row)[axis] == pytest.approx(float(getattr(row, axis)))


def test_real_source_gear_application_feeds_live_hit_and_crit_channels():
    ir = _actual_druid()
    for key, amount, dest in (("crit", 14., ("spell_crit_chance", "melee_crit_chance")),
                              ("hit", 10., ("spell_hit_bonus", "melee_hit_bonus")),
                              ("dodge", 12., ("dodge_chance",))):
        source = source_item_stat_to_combat(key, amount, level=60)
        assert source["mechanic_status"] == "SOURCE_DISPLAY_MAPPING_AND_EXECUTOR_CHANCE"
        via_probe = apply_stat_delta(ir, key, amount)
        via_gear, receipt = apply_gear_selection(ir, aggregate_stats={key: amount})
        for actual in (via_probe, via_gear):
            actor = ActorState.from_ir(actual.actor, actual.resources, actual.modes)
            baseline = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
            for channel in dest:
                assert actor.stats[channel] - baseline.stats.get(channel, 0.) == pytest.approx(.01)
        assert receipt.applied_stats[key] == amount


def test_actual_combat_cast_damage_improves_with_sourced_item_crit():
    ir = _actual_druid()
    action, baseline = _offensive_cast(ir)
    improved = apply_stat_delta(ir, "crit", 14.)
    same_action = next(a for a in improved.actions if a.id == action.id)
    actual = _action_runtime_probe(
        improved, same_action, target_spell_hit=.5, capture_source_hit=True)
    assert actual is not None
    assert actual["direct_damage"] > baseline["direct_damage"]


def test_actual_combat_hit_chance_improves_with_sourced_item_hit():
    ir = _actual_druid()
    action, baseline = _offensive_cast(ir)
    improved = apply_stat_delta(ir, "hit", 10.)
    same_action = next(a for a in improved.actions if a.id == action.id)
    actual = _action_runtime_probe(
        improved, same_action, target_spell_hit=.5, capture_source_hit=True)
    assert actual is not None
    assert actual["direct_damage"] > baseline["direct_damage"]
