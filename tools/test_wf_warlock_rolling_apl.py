import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wf_warlock_rolling_apl import (
    build_rolling_two_target_apl, build_stationary_native_multidot_smoke,
)


class RollingAfflictionAPLTests(unittest.TestCase):
    def setUp(self):
        names = ["Immolate", "Bane of Agony", "Siphon Life",
                 "Corruption", "Drain Life", "Life Tap", "Shoot"]
        self.rust_spells = [{"name": n, "spell_id": i+4000}
                            for i, n in enumerate(names)]

    def test_source_native_dot_order_and_single_50_percent_switch(self):
        apl, meta = build_rolling_two_target_apl(self.rust_spells,
                                                 pull_threshold=50)
        self.assertEqual(meta["native_wand_spell_id"], 4006)
        self.assertEqual(meta["filler"], "shoot")
        self.assertEqual([row["action"]["castSpell"]["spellId"]["spellId"]
                          for row in apl if "castSpell" in row["action"]],
                         [4004, 4000, 4001, 4002, 4003, 4005, 4006])
        switch = apl[1]["action"]
        self.assertEqual(switch["changeTarget"]["newTarget"]["type"],
                         "NextTarget")
        checks = switch["condition"]["and"]["vals"]
        self.assertEqual(checks[0]["cmp"]["lhs"]["currentHealthPercent"]
                         ["sourceUnit"]["type"], "CurrentTarget")
        self.assertEqual(checks[0]["cmp"]["rhs"]["const"]["val"], "50%")
        self.assertEqual(checks[1]["cmp"]["lhs"]["currentHealthPercent"]
                         ["sourceUnit"]["type"], "NextTarget")
        self.assertEqual(checks[1]["cmp"]["rhs"]["const"]["val"], "95%")
        self.assertFalse(meta["multi_target_world_ACK_verified"])

    def test_stationary_native_multidot_does_not_claim_50_percent_policy(self):
        apl, meta = build_stationary_native_multidot_smoke(self.rust_spells)
        self.assertEqual(
            [row["action"]["multidot"]["spellId"]["spellId"]
             for row in apl if "multidot" in row["action"]],
            [4000, 4001, 4002, 4003])
        self.assertFalse(meta["pull_at_50_pct_executed"])
        self.assertFalse(meta["world_2d_ack_executed"])
        self.assertTrue(meta["native_two_target_dots_only"])

    def test_missing_native_spells_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "siphon life"):
            build_rolling_two_target_apl(
                [row for row in self.rust_spells
                 if row["name"] != "Siphon Life"])

    def test_switch_threshold_is_proposal_parameter(self):
        apl, meta = build_rolling_two_target_apl(self.rust_spells,
                                                 pull_threshold=40)
        self.assertEqual(meta["pull_threshold_pct"], 40)
        self.assertEqual(apl[1]["action"]["condition"]["and"]["vals"][0]
                         ["cmp"]["rhs"]["const"]["val"], "40%")

    def test_unsupported_wand_stays_explicit_not_made_up(self):
        apl, meta = build_rolling_two_target_apl(
            [row for row in self.rust_spells if row["name"] != "Shoot"])
        self.assertIsNone(meta["native_wand_spell_id"])
        self.assertEqual(meta["filler"], "drain life")
        self.assertEqual(apl[-1]["action"]["castSpell"]["spellId"]["spellId"],
                         4004)


if __name__ == "__main__":
    unittest.main()
