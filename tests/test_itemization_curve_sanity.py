from __future__ import annotations

import math
import unittest

from src.rulesets.forever.classes.mage.engine import (
    Talents as MageTalents,
    forever_crafted_gear,
    player_stats,
)
from src.rulesets.forever.classes.druid.talents import Talents as DruidTalents
from src.rulesets.forever.classes.druid.mechanics import (
    _balance_gear,
    _bear,
    _bear_gear,
    _feral_gear,
    experimental_level_score as druid_score,
)
from src.rulesets.forever.classes.paladin.talents import Talents as PaladinTalents
from src.rulesets.forever.classes.paladin.gear import archetypes as paladin_archetypes
from src.rulesets.forever.classes.paladin.mechanics import experimental_level_score as paladin_score

LEVELS = (20, 30, 40, 50, 60)


class ItemizationCurveSanityTests(unittest.TestCase):
    def test_mage_named_item_spell_power_is_live_in_player_stats(self):
        # Real gear can trade SP for Int/Spirit/wand DPS, so the selected SP
        # total is not required to be monotone.  Runtime must mirror the exact
        # selected named-item total at every checkpoint.
        from src.rulesets.forever.classes.mage.real_gear import snapshot
        for level in LEVELS:
            gear = forever_crafted_gear(level)
            stats = player_stats(level, MageTalents())
            named = snapshot(level)
            self.assertAlmostEqual(gear["spell_power_floor"], named["totals"]["spell_power"])
            self.assertAlmostEqual(stats.spell_power, gear["spell_power_floor"])
            self.assertGreaterEqual(stats.spell_power, 0.0)

    def test_druid_role_selection_is_sql_backed_and_role_distinct(self):
        c20, b20, r20 = _feral_gear(20), _balance_gear(20), _bear_gear(20)
        self.assertGreater(c20["agility"], 0.0)
        self.assertEqual(c20["spell_power"], 0.0)
        self.assertGreater(b20["spell_power"], 0.0)
        self.assertGreaterEqual(r20["stamina"], c20["stamina"])
        for gear in (c20, b20, r20, _feral_gear(60), _balance_gear(60), _bear_gear(60)):
            self.assertEqual(gear["provenance"], "sqlite_catalogue")
            self.assertEqual(gear["gear_selection_method"], "canonical_sqlite_runtime_selection_v1")
            self.assertTrue(gear["slots"])
            self.assertTrue(all(row.get("item_id", 0) > 0 for row in gear["slots"].values()))

    def test_paladin_1h_and_2h_curves_remain_separate_and_monotone(self):
        prev_2h_dps = prev_1h_dps = prev_shield = -1.0
        for level in LEVELS:
            rows = {g.name: g for g in paladin_archetypes(level)}
            two = rows["2h_normal"]
            one = rows["1h_shield_normal"]
            self.assertEqual(two.weapon_style, "2h")
            self.assertEqual(one.weapon_style, "1h_shield")
            self.assertGreater(two.weapon_dps, one.weapon_dps)
            self.assertGreaterEqual(two.weapon_dps, prev_2h_dps)
            self.assertGreaterEqual(one.weapon_dps, prev_1h_dps)
            self.assertGreaterEqual(one.shield_armor, prev_shield)
            prev_2h_dps, prev_1h_dps, prev_shield = two.weapon_dps, one.weapon_dps, one.shield_armor

    def test_druid_runtime_profiles_stay_finite_at_curve_checkpoints(self):
        talents = DruidTalents()
        for level in LEVELS:
            for profile in ("feral", "balance"):
                row = druid_score(level, talents, profile)
                self.assertTrue(math.isfinite(row["total_s"]))
                self.assertGreater(row["total_s"], 0.0)
                self.assertIn("gear_stats", row)
            bear = _bear(level, talents)
            self.assertTrue(math.isfinite(bear["total_s"]))
            self.assertGreater(bear["total_s"], 0.0)
            self.assertIn("gear_stats", bear)

    def test_paladin_runtime_profiles_stay_finite_at_curve_checkpoints(self):
        talents = PaladinTalents()
        for level in LEVELS:
            for profile in ("retribution", "protection"):
                row = paladin_score(level, talents, profile)
                self.assertTrue(math.isfinite(row["total_s"]))
                self.assertGreater(row["total_s"], 0.0)
                self.assertIn("gear_stats", row)
                self.assertIn(row["gear"], ("2h_normal", "1h_shield_normal"))


if __name__ == "__main__":
    unittest.main()
