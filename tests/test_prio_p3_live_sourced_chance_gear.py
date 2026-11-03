"""P3 source raw chance stats map into the active gear candidate path."""
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3_ratings import (
    source_item_stat_to_combat,
)
from src.game.gear import apply_stat_delta, apply_gear_selection
from src.game.runtime import ActorState
from src.rulesets.forever.items.runtime_selection import available_items, item_vector


def _actual_druid():
    ir = build_game_ir_slice(class_key="druid", level=60)
    assert ir is not None
    return ir


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


