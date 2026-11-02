"""Source-backed crit/hit item points must affect the shared real gear evaluator."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3_ratings import source_item_stat_to_combat
from src.game.gear import apply_gear_selection, apply_stat_delta, executable_gear_stats
from src.game.model.ir import DamageEffect
from src.game.runtime.simulator import CombatRuntime, _direct_damage_crit_probability
from src.rulesets.forever.items.runtime_selection import available_items, item_vector


@pytest.mark.parametrize("class_key,level", (("druid", 60), ("mage", 30)))
@pytest.mark.parametrize("stat,raw", (("crit", 14.0), ("hit", 10.0)))
def test_source_chance_points_reach_real_gear_probe_and_named_gear(class_key, level, stat, raw):
    ir = build_game_ir_slice(class_key=class_key, level=level)
    assert ir is not None
    assert stat in executable_gear_stats(ir)
    expected = source_item_stat_to_combat(stat, raw, level=level)
    assert expected["mechanic_status"] == "SOURCE_DISPLAY_MAPPING_AND_EXECUTOR_CHANCE"

    probe = apply_stat_delta(ir, stat, raw)
    equipped, receipt = apply_gear_selection(ir, aggregate_stats={stat: raw})
    assert receipt.applied_stats[stat] == raw
    assert stat not in receipt.unsupported_stats

    for changed in (probe, equipped):
        for channel, chance in expected["channel_deltas"].items():
            assert changed.actor.base_stats[channel] - ir.actor.base_stats.get(channel, 0.0) == pytest.approx(chance)
        evidence = changed.actor.metadata["gear_item_chance_source_evidence"]
        assert any(x["source_stat"] == stat and x["source_urls"] for x in evidence)

    if stat == "crit":
        # Use an actual sourced executable magic damage effect and the production
        # combat resolver, not a P3-only scorer or invented positive stat weight.
        effects = [
            effect for action in ir.actions for effect in action.effects
            if isinstance(effect, DamageEffect)
            and str(effect.school).lower() not in ("physical", "bleed", "")
        ]
        assert effects
        before = _direct_damage_crit_probability(effects[0], ir.actor.base_stats)
        after = _direct_damage_crit_probability(effects[0], equipped.actor.base_stats)
        assert after > before
    else:
        # This is the exact runtime hit-probability operation used for damage
        # and debuffs; 0.80 is a controlled, non-saturated negative control.
        def hit(stats):
            runtime = SimpleNamespace(
                actions={}, actor=SimpleNamespace(stats=stats))
            return CombatRuntime._source_outgoing_hit_components(
                runtime, 0.80, None, weapon_hit=False)[2]

        assert hit(equipped.actor.base_stats) > hit(ir.actor.base_stats)
        # Saturated chance must not be artificially boosted to pass P3.
        assert hit({**equipped.actor.base_stats, "spell_hit_bonus": 0.5}) == 1.0


def test_named_gear_selector_preserves_source_raw_item_chance_points():
    rows = available_items("druid", 60, required_level_policy="observed")
    assert rows
    for item in rows[:10]:
        vector = item_vector(item)
        assert vector["crit"] == pytest.approx(float(item.crit))
        assert vector["hit"] == pytest.approx(float(item.hit))
