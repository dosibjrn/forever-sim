import pytest

from src.shared.leveling.objective import spell_hit_chance
from src.rulesets.forever.classes.druid import wowhead_facts as dwh


def test_same_level_spell_hit_baseline_is_shared_and_not_guaranteed():
    assert spell_hit_chance(20, 20) == pytest.approx(0.96)
    assert spell_hit_chance(20, 20, bonus_pct=2.0) == pytest.approx(0.98)
    assert spell_hit_chance(20, 20, bonus_pct=10.0) == pytest.approx(0.99)


def test_forever_wrath_raw_tooltip_rows_are_explicit_through_l38_only():
    assert dwh.WRATH_RANKS[:3] == (
        (1, 10, 1.5, 15, 18, 0.429),
        (6, 20, 1.7, 25, 28, 0.486),
        (14, 40, 2.0, 32, 37, 0.571),
    )
    assert (38, 80, 2.0, 56, 63, 0.571) in dwh.WRATH_RANKS
    assert (54, 120, 2.0, 92, 102, 0.571) in dwh.WRATH_RANKS
    assert 46 not in {row[0] for row in dwh.WRATH_RANKS}


def test_l20_balance_uses_shared_spell_hit_and_patch_aware_wrath_tuning():
    from src import game_context
    from src.engine_registry import reset_engine_cache, get_engine
    game_context.configure('forever', 'druid'); reset_engine_cache()
    e = get_engine()
    t = e.Talents(improved_wrath=5, genesis=2, improved_moonfire=2, natures_majesty=2)
    r = e.experimental_level_score(20, t, 'balance')
    assert r['spell_hit_chance'] == pytest.approx(0.96)
    # Raw public tooltip stays 32-37; the September 24 server-build tuning is
    # applied separately to base damage without inventing rounded tooltip ints.
    assert r['wrath_base_damage_multiplier'] == pytest.approx(1.5)
    assert r['wrath_raw_base_damage_avg'] == pytest.approx(34.5)
    assert r['wrath_tuned_base_damage_avg'] == pytest.approx(51.75)
    assert r['kill_s'] / 100.0 < 8.0
    assert 250.0 < 360000.0 / r['total_s'] < 280.0


def test_mage_deterministic_screen_carries_incoming_hp_and_is_damage_sensitive(monkeypatch):
    from src import game_context
    from src.engine_registry import reset_engine_cache, get_engine
    game_context.configure('forever', 'mage'); reset_engine_cache()
    e = get_engine()
    from src.v2.expected_engine import simulate_fight_expected

    t = e.Talents(imp_frostbolt=5)
    p = e.Policy('hp carry probe', 'frostbolt', use_fireblast=False, use_nova=False, use_blink=False)
    cfg = e.SimConfig()
    base = simulate_fight_expected(20, t, p, cfg, recover_after=False)
    assert base.unabsorbed_swings > 0
    assert base.hp_missing > 0

    original = e.normal_world_raw_dps
    monkeypatch.setattr(e, 'normal_world_raw_dps', lambda level: original(level) * 5.0)
    hot = simulate_fight_expected(20, t, p, cfg, recover_after=False)
    assert hot.unabsorbed_swings == pytest.approx(base.unabsorbed_swings)
    assert hot.hp_missing == pytest.approx(base.hp_missing * 5.0)
