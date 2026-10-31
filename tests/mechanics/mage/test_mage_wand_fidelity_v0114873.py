from __future__ import annotations

from src.rulesets.forever.classes.mage import engine as mage
from src.rulesets.forever.classes.mage import policy as mage_policy


class _FixedRng:
    def __init__(self, value: float):
        self.value = float(value)
    def random(self) -> float:
        return self.value


def test_l20_sizzle_stick_school_and_ranged_hit_are_current_authorities():
    wand = mage.best_wand(20)
    assert wand.item_id == 8071
    assert wand.name == "Sizzle Stick"
    assert wand.school == "fire"
    assert wand.school_origin == "wowhead_current_item_fact"
    assert abs(mage.wand_hit_chance(20, 20) - 0.95) < 1e-12


def test_wand_expected_hit_uses_ranged_hit_not_mage_spell_hit_talents():
    cfg = mage.SimConfig()
    mob = mage.Mob(level=20, hp=500.0, run_speed=cfg.mob_speed, swing=2.0, melee_reach=cfg.melee_reach)
    no_spell_hit = mage.Talents(elemental_precision=0)
    max_spell_hit = mage.Talents(elemental_precision=5)
    a = mage_policy._expected_wand_hit(20, mob, no_spell_hit, cfg)
    b = mage_policy._expected_wand_hit(20, mob, max_spell_hit, cfg)
    assert abs(a - b) < 1e-12
    # Default profile has zero same-level Fire resistance: 39.5 average raw
    # damage times the 95% ranged-weapon hit chance.
    assert abs(a - 39.5 * 0.95) < 1e-9


def test_event_wand_attack_table_can_miss_before_magic_resistance():
    cfg = mage.SimConfig()
    mob = mage.Mob(level=20, hp=500.0, run_speed=cfg.mob_speed, swing=2.0, melee_reach=cfg.melee_reach)
    wand = mage.best_wand(20)
    talents = mage.Talents(elemental_precision=5)
    assert mage_policy._wand_attack_multiplier(20, mob, wand, talents, cfg, _FixedRng(0.99)) == 0.0
