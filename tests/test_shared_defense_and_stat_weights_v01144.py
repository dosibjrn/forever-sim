from __future__ import annotations

import math
from pathlib import Path

import pytest

from src.rulesets.forever.shared.defense import (
    armor_constant,
    armor_reduction,
    defense_avoidance,
    defense_block_chance,
    representative_player_hp,
)
from src.rulesets.forever.classes.paladin import mechanics as paladin
from src.rulesets.forever.classes.paladin.talents import Talents as PaladinTalents
from src.rulesets.forever.classes.druid import mechanics as druid
from src.rulesets.forever.classes.druid.talents import Talents as DruidTalents
from src.rulesets.forever.classes.mage import engine as mage
from src.v2.stat_weight_model import compute_for_engine, normalize_objective_gradient


def _shield_gear(level: int = 20):
    return next(g for g in paladin.archetypes(level) if g.has_shield)


def test_shared_defense_contract_has_monotone_armor_hp_and_combat_table_hooks():
    assert armor_reduction(0, 20) == 0.0
    assert 0.0 < armor_reduction(500, 20) < armor_reduction(1000, 20) <= 0.75
    assert armor_constant(59) == pytest.approx(400 + 85 * 59)
    assert armor_constant(60) == pytest.approx(467.5 * 60 - 22167.5)
    assert representative_player_hp(20, 1) - representative_player_hp(20, 0) == 10.0
    assert math.isclose(defense_avoidance(1), 0.0012, rel_tol=1e-12)
    assert math.isclose(defense_block_chance(1, has_shield=True), 0.0004, rel_tol=1e-12)
    assert defense_block_chance(10, has_shield=False) == 0.0


def test_paladin_item_defense_changes_real_incoming_damage_and_mutation_severing_link_is_detected(monkeypatch):
    level, talents, gear = 20, PaladinTalents(), _shield_gear()
    focus = paladin._base_damage(level, talents, gear, "protection")
    base = paladin._incoming(level, talents, gear, 3, "devotion", focus)
    more = paladin._incoming(level, talents, gear.with_delta("defense", 10), 3, "devotion", focus)

    assert more["defense_skill_bonus"] == pytest.approx(base["defense_skill_bonus"] + 10)
    assert more["avoidance"] > base["avoidance"]
    assert more["block_chance"] > base["block_chance"]
    assert more["damage_per_mob"] < base["damage_per_mob"]

    # Deliberate M44 mutation: cut both +Defense combat-table hooks.  The same
    # item delta must then lose all incoming-damage sensitivity.  If production
    # ever regresses to this state, the assertions above fail the release gate.
    monkeypatch.setattr(paladin, "defense_avoidance", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(paladin, "defense_block_chance", lambda *_a, **_k: 0.0)
    broken_base = paladin._incoming(level, talents, gear, 3, "devotion", focus)
    broken_more = paladin._incoming(level, talents, gear.with_delta("defense", 10), 3, "devotion", focus)
    assert broken_more["damage_per_mob"] == pytest.approx(broken_base["damage_per_mob"])


def test_paladin_armor_changes_real_incoming_damage_and_mutation_severing_link_is_detected(monkeypatch):
    level, talents, gear = 20, PaladinTalents(), _shield_gear()
    focus = paladin._base_damage(level, talents, gear, "protection")
    base = paladin._incoming(level, talents, gear, 3, "devotion", focus)
    more = paladin._incoming(level, talents, gear.with_delta("armor", 100), 3, "devotion", focus)
    assert more["armor_reduction"] > base["armor_reduction"]
    assert more["damage_per_mob"] < base["damage_per_mob"]

    monkeypatch.setattr(paladin, "armor_reduction", lambda *_a, **_k: 0.0)
    broken_base = paladin._incoming(level, talents, gear, 3, "devotion", focus)
    broken_more = paladin._incoming(level, talents, gear.with_delta("armor", 100), 3, "devotion", focus)
    assert broken_more["damage_per_mob"] == pytest.approx(broken_base["damage_per_mob"])



def test_fast_and_event_backends_move_same_direction_for_defense_and_armor():
    from src.rulesets.forever.classes.paladin.event_replay import replay_pack
    from src.rulesets.forever.classes.paladin.policy import POLICIES, MANA_PLANS

    level, talents, gear = 20, PaladinTalents(), _shield_gear()
    policy = next(x for x in POLICIES if x.name == "aggressive")
    plan = next(x for x in MANA_PLANS if x.name == "full")

    def pair(g):
        focus = paladin._base_damage(level, talents, g, "protection")
        incoming = paladin._incoming(level, talents, g, 3, "devotion", focus)
        event = replay_pack(level, talents, "protection", g, 3, policy, "devotion", plan)
        assert event["complete"] is True
        return incoming, event

    base_fast, base_event = pair(gear)
    defense_fast, defense_event = pair(gear.with_delta("defense", 10))
    armor_fast, armor_event = pair(gear.with_delta("armor", 100))

    assert defense_fast["damage_per_mob"] < base_fast["damage_per_mob"]
    assert defense_event["player_hp_end"] > base_event["player_hp_end"]
    assert armor_fast["damage_per_mob"] < base_fast["damage_per_mob"]
    assert armor_event["player_hp_end"] > base_event["player_hp_end"]

def test_stat_weight_schema_distinguishes_measured_zero_from_unavailable():
    out = normalize_objective_gradient(
        baseline_s_per_100=1000,
        objective_gradient={"strength": 0.0, "spell_power": -2.0},
        method="m44_status_test",
        declared_stats=("strength", "spell_power", "defense", "armor"),
        stat_status={
            "defense": {"status": "not_modeled", "reason": "test"},
            "armor": {"status": "not_probeable", "reason": "test"},
        },
    )
    assert out["schema_version"] == 3
    assert out["stats"]["strength"]["status"] == "measured"
    assert out["stats"]["strength"]["seconds_saved_per_100_per_point"] == 0.0
    assert out["stats"]["defense"]["status"] == "not_modeled"
    assert "seconds_saved_per_100_per_point" not in out["stats"]["defense"]
    assert out["stats"]["armor"]["status"] == "not_probeable"
    assert "seconds_saved_per_100_per_point" not in out["stats"]["armor"]


def test_paladin_unified_weights_publish_defensive_stats_with_explicit_statuses():
    talents = PaladinTalents()
    base = paladin.experimental_level_score(20, talents, "protection")
    out = compute_for_engine(paladin, 20, talents, baseline=base, profile="protection")
    assert out is not None
    for stat in ("stamina", "armor", "defense", "healing", "shield_armor", "block_value"):
        assert out["stats"][stat]["status"] == "measured"
        assert "seconds_saved_per_100_per_point" in out["stats"][stat]
    # M44 does not require every defensive stat to be positive in every local
    # route. It requires the actual scorer linkage to be measured and visible.
    assert math.isfinite(out["stats"]["defense"]["seconds_saved_per_100_per_point"])


def test_druid_and_mage_publish_honest_defensive_availability():
    dt = DruidTalents()
    dbase = druid.experimental_level_score(20, dt, "feral")
    dout = druid.marginal_stat_weights(20, dt, "feral", dbase)
    assert dout["stats"]["stamina"]["status"] == "measured"
    assert dout["stats"]["armor"]["status"] == "measured"
    assert dout["stats"]["defense"]["status"] == "not_modeled"
    assert "seconds_saved_per_100_per_point" not in dout["stats"]["defense"]

    mt = mage.Talents()
    cfg = mage.SimConfig(use_best_water=True)
    policy = mage.Policy("m44", "frostbolt", use_fireblast=False, use_nova=False, use_blink=False)
    mbase = {
        "total_s": 1200.0,
        "kill_s": 900.0,
        "recovery_s": 300.0,
        "casts_frostbolt": 350.0,
        "casts_wand_expected_s": 40.0,
    }
    mout = compute_for_engine(mage, 34, mt, baseline=mbase, policy=policy, cfg=cfg)
    assert mout["stats"]["stamina"]["status"] == "not_probeable"
    assert mout["stats"]["armor"]["status"] == "not_probeable"
    assert mout["stats"]["defense"]["status"] == "not_modeled"
    assert "seconds_saved_per_100_per_point" not in mout["stats"]["stamina"]


def test_listener_exposes_weight_availability_and_only_values_measured_rows():
    source = Path("src/listener.py").read_text(encoding="utf-8")
    assert "function statWeightAvailability(row)" in source
    assert "not probeable:" in source
    assert "not modeled:" in source
    assert "st[k].status!=='measured'?NaN" in source
    assert "Availability · ${esc(statWeightAvailability(row))}" in source
