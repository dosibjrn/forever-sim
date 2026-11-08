"""Eight-mob probe tests: source Rust receipts only, no gameplay model."""
import copy
import random
import unittest

from wf_warlock_chain_surrogate import (
    extract_three_mob_features, extract_eight_mob_features,
)
from wf_warlock_l30_surrogate_probe import diverse_source_candidates
from wf_warlock_surrogate_rank_validation import report_rank_validation


class EightMobProbeTests(unittest.TestCase):
    def setUp(self):
        self.prepared = {"player": {
            "stats": {"Health": 1000.}, "mana": {"max": 500.},
        }}
        self.world = {
            "world_targets_killed": 8,
            "continuous_native_actor": True,
            "actual_2d_ack": True,
            "world_elapsed_seconds": 120.0,
            "native_windows": [
                {"native_kill_ns": (i+1)*15_000_000_000,
                 "actor_health": 950.-i*40., "actor_mana": 480.-i*30.,
                 "native_combat_mana_regen_actual_gain": 30.,
                 "native_health_damage_taken": 40.,
                 "native_mana_spent": 100.,
                 "native_mana_gained": 70.,
                 "native_health_actual_gain": 0.,
                 "native_spell_cast_receipts": [],
                 "native_long_cooldown_states": [{
                     "spell_id": 123, "duration_ns": 180_000_000_000,
                     "ready_in_ns": (180-15*(i+1))*1_000_000_000,
                 }]}
                for i in range(8)],
        }

    def test_eight_real_kills_and_three_prefix(self):
        eight = extract_eight_mob_features(self.prepared, self.world)
        self.assertEqual(len(eight["raw"]["kill_times_s"]), 8)
        self.assertEqual(eight["raw"]["kill_times_s"], [15.]*8)
        self.assertAlmostEqual(eight["features"]["mana_net_drain_per_mob_fraction"], .23/8)
        three_world = copy.deepcopy(self.world)
        three_world["world_targets_killed"] = 3
        three_world["native_windows"] = self.world["native_windows"][:3]
        three_world["world_elapsed_seconds"] = 45.
        three = extract_three_mob_features(self.prepared, three_world)
        self.assertEqual(len(three["raw"]["kill_times_s"]), 3)
        self.assertEqual(set(three["features"]), set(eight["features"]))

    def test_eight_requires_all_eight_lethal_acknowledgments(self):
        truncated = copy.deepcopy(self.world)
        truncated["world_targets_killed"] = 7
        with self.assertRaisesRegex(ValueError, "8 lethal ACKs"):
            extract_eight_mob_features(self.prepared, truncated)
        truncated = copy.deepcopy(self.world)
        truncated["native_windows"] = truncated["native_windows"][:7]
        with self.assertRaisesRegex(ValueError, "every native kill"):
            extract_eight_mob_features(self.prepared, truncated)

    def test_source_candidate_sampler_is_reproducible_and_unique(self):
        talents = [{"talents": f"t{x}", "label": f"tree{x}"} for x in range(8)]
        apls = [(f"apl{x}", [{"action": {"castSpell": {"spellId": {"spellId": x}}}}])
                for x in range(9)]
        x = list(diverse_source_candidates(talents, apls, 40, 123))
        y = list(diverse_source_candidates(talents, apls, 40, 123))
        self.assertEqual(x, y)
        self.assertEqual(len(x), 40)
        ids = [(g,t["talents"],p,a) for g,t,p,a,_ in x]
        self.assertEqual(len(ids), len(set(ids)))

    def test_rank_validation_never_trains_on_same_build_family(self):
        probe = extract_eight_mob_features(self.prepared, self.world)
        rows, cases = [], []
        for i in range(10):
            p = copy.deepcopy(probe)
            p["features"]["mean_kill_s"] += i
            p["features"]["mana_end_fraction"] -= i*.02
            rows.append({"candidate": i, "engine_sha": "rust",
                         "scenario_id": "same", "probe": p,
                         "result": {"status": "COMPLETED", "confirmed_kills": 100,
                                    "elapsed_s": 2400. + 100.*i}})
            cases.append({"result": {"candidate": i,
                                     "gear": "native_dps",
                                     "talents": f"t{i//2}",
                                     "pet": "Succubus"}})
        report = report_rank_validation(
            rows, cases, engine_sha="rust", scenario_id="same")
        holdout = report["validation"]["leave_one_build_family_out"]
        self.assertEqual(holdout["predictions"], 10)
        self.assertEqual({r["train_size"] for r in holdout["rows"]}, {8})
        self.assertEqual(holdout["pairwise_total"], 45)


if __name__ == "__main__":
    unittest.main()
