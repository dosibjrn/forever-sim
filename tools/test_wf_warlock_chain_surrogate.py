import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from wf_warlock_chain_surrogate import (
    extract_three_mob_features, train_supervised, predict,
    select_native_100_validation,
)


class ThreeMobSurrogateTests(unittest.TestCase):
    def setUp(self):
        self.prepared={"player":{
            "stats":{"Health":1000.},"mana":{"max":500.},
            "spells":[{"action_id":{"spell_id":20554},"cd":{"duration_ns":180_000_000_000}}],
        }}
        self.world={
            "world_targets_killed":3,"continuous_native_actor":True,
            "actual_2d_ack":True,"world_elapsed_seconds":45.,
            "native_windows":[{
                "index":idx,"native_kill_ns":int((idx+1)*15e9),
                "actor_health":950.-50.*idx,"actor_mana":460.-40.*idx,
                "native_combat_mana_regen_actual_gain":30.,
                "native_health_damage_taken":50.,
                "native_health_actual_gain":0.,
                "native_mana_spent":100.,"native_mana_gained":60.,
                "native_spell_cast_receipts":[{
                    "spell_id":20554,"casts":1,
                    "cooldown_ns":180_000_000_000,"is_long_cooldown":True,
                }] if idx==0 else [],
                "native_long_cooldown_states":[{
                    "spell_id":20554,"duration_ns":180_000_000_000,
                    "ready_in_ns":int((180.-15.*(idx+1))*1e9),
                }],
            } for idx in range(3)],
        }

    def test_native_three_kill_resource_and_cd_features(self):
        p=extract_three_mob_features(self.prepared,self.world)
        self.assertEqual(p["raw"]["kill_times_s"],[15.,15.,15.])
        self.assertEqual(p["raw"]["native_mana_spent"],300.)
        self.assertEqual(p["raw"]["native_mana_gained"],180.)
        self.assertEqual(p["features"]["long_cooldown_casts_first3"],1.)
        self.assertAlmostEqual(p["features"]["long_cooldown_remaining_s"],135.)
        self.assertTrue(p["cooldowns"]["long_cooldown_usage_observed"])

    def test_combat_only_resource_features_override_legacy_rest_inclusive(self):
        # An actual retained Rust actor recovers between kills. Food/water is
        # not a Warlock combat mana-gain or healing action in the surrogate.
        for window in self.world["native_windows"]:
            window.update({
                "native_combat_start_ns": window["native_kill_ns"] - int(8e9),
                "native_recovery_mana_regen_actual_gain": 120.,
                "native_combat_mana_spent": 60.,
                "native_combat_mana_gained": 20.,
                "native_combat_health_actual_gain": 15.,
                "native_mana_spent": 99.,
                "native_mana_gained": 140.,
                "native_health_actual_gain": 65.,
            })
        result=extract_three_mob_features(self.prepared,self.world)
        self.assertEqual(result["raw"]["native_mana_spent_source"],
                         "native_combat_mana_spent")
        self.assertEqual(result["raw"]["regeneration_window_source"],
                         "post_recovery_combat_only")
        self.assertAlmostEqual(result["features"]["mana_spent_per_mob_fraction"],
                               60./500.)
        self.assertAlmostEqual(result["features"]["mana_gained_per_mob_fraction"],
                               20./500.)
        self.assertAlmostEqual(result["features"]["health_actual_gain_per_mob_fraction"],
                               15./1000.)
        self.assertEqual(result["raw"]["native_recovery_mana_regen_actual_gain"],
                         [120.,120.,120.])

    def test_reject_mixed_native_resource_window_schema(self):
        self.world["native_windows"][1]["native_combat_mana_gained"]=2.
        with self.assertRaisesRegex(ValueError,"Mixed native combat-only"):
            extract_three_mob_features(self.prepared,self.world)

    def test_reject_mixed_regen_receipt_schema(self):
        self.world["native_windows"][0].update({
            "native_combat_start_ns": 0,
            "native_recovery_mana_regen_actual_gain": 5.,
        })
        with self.assertRaisesRegex(ValueError,"Mixed native combat and recovery"):
            extract_three_mob_features(self.prepared,self.world)

    def test_not_trained_without_real_long_labels(self):
        p=extract_three_mob_features(self.prepared,self.world)
        m=train_supervised([],engine_sha="engine",scenario_id="fixed")
        result=predict(m,p,engine_sha="engine",scenario_id="fixed")
        self.assertFalse(result["prediction_trained"])
        self.assertIsNone(result["estimated_100_mob_elapsed_s"])
        with self.assertRaises(ValueError):
            predict(m,p,engine_sha="other",scenario_id="fixed")

    def test_trains_only_completed_100_mob_labels(self):
        p=extract_three_mob_features(self.prepared,self.world)
        sessions=[]
        for i in range(8):
            q={"features":p["features"].copy()}
            q["features"]["mean_kill_s"]+=i
            q["features"]["mana_end_fraction"]-=i*0.01
            sessions.append({
                "engine_sha":"engine","scenario_id":"fixed","probe":q,
                "result":{"status":"COMPLETED","confirmed_kills":100,
                          "elapsed_s":1700.+i*100.},
            })
        model=train_supervised(sessions,engine_sha="engine",scenario_id="fixed")
        self.assertEqual(model["completed_100_runs"],8)
        result=predict(model,p,engine_sha="engine",scenario_id="fixed")
        self.assertTrue(result["prediction_trained"])
        self.assertTrue(math.isfinite(result["estimated_100_mob_elapsed_s"]))
        self.assertGreater(result["estimated_100_mob_elapsed_s"],0.)
        sessions.append({"engine_sha":"engine","scenario_id":"fixed","probe":p,
                         "result":{"status":"INCOMPLETE","confirmed_kills":13,
                                   "elapsed_s":1.}})
        model2=train_supervised(sessions,engine_sha="engine",scenario_id="fixed")
        self.assertEqual(model2["completed_100_runs"],8)


    def test_true_long_run_budget_uses_prediction_and_exploration(self):
        native={"health_end_fraction":.85,"mana_end_fraction":.65,
                "kill_time_slope":0.,"late_kill_s":14.}
        def case(index, pet, seconds, distance):
            return {"result":{
                "candidate":index,"gear":"native_dps",
                "talents":"t"+str(index),"pet":pet,"filler":"drain life",
                "surrogate":{
                    "estimated_100_mob_elapsed_s":seconds,
                    "probability_100_mob_completed":None,
                    "standardized_training_distance":distance,
                },
            },"probe":{"features":native}}
        fast=case(20,"Succubus",1750.,.3)
        uncertain=case(21,"Imp",2700.,4.5)
        observed=[case(0,"Succubus",3000.,0.)]
        selected,reason=select_native_100_validation(
            [fast,uncertain],observed,iteration=3)
        self.assertEqual(selected["result"]["candidate"],20)
        self.assertEqual(reason,"predicted_100_mob_exploitation")
        selected,reason=select_native_100_validation(
            [fast,uncertain],observed,iteration=2)
        self.assertEqual(selected["result"]["candidate"],21)
        self.assertEqual(reason,"out_of_sample_exploration")

    def test_resource_bootstrap_when_long_labels_are_insufficient(self):
        weak={"result":{"candidate":0,"pet":"Imp"},
              "probe":{"features":{
                  "health_end_fraction":.3,"mana_end_fraction":.2,
                  "kill_time_slope":4.,"late_kill_s":20.}}}
        strong={"result":{"candidate":1,"pet":"Felhunter"},
                "probe":{"features":{
                    "health_end_fraction":.9,"mana_end_fraction":.7,
                    "kill_time_slope":1.,"late_kill_s":26.}}}
        selected,reason=select_native_100_validation(
            [weak,strong],[],iteration=0)
        self.assertEqual(selected["result"]["candidate"],1)
        self.assertEqual(reason,"native_resource_bootstrap")

    def test_native_8mob_fastest_is_paid_real_100_before_calibration(self):
        # Resource-dominated 8-kill champion still gets an actual native
        # 100-kill check, not just the first high-HP/easy-to-survive build.
        a={"result":{"candidate":0,"pet":"Imp","eight_elapsed_s":165.985},
           "probe":{"features":{"health_end_fraction":.754,
                                 "mana_end_fraction":.541,
                                 "kill_time_slope":1.,"late_kill_s":20.}}}
        b={"result":{"candidate":1,"pet":"Felhunter","eight_elapsed_s":230.},
           "probe":{"features":{"health_end_fraction":1.,
                                 "mana_end_fraction":.809,
                                 "kill_time_slope":2.,"late_kill_s":26.}}}
        first,reason=select_native_100_validation([a,b],[],iteration=0)
        self.assertEqual(first["result"]["candidate"],1)
        second,reason=select_native_100_validation([a,b],[],iteration=1)
        self.assertEqual(second["result"]["candidate"],0)
        self.assertEqual(reason,"native_8mob_fastest_bootstrap")

    def test_unverified_timeout_is_not_a_survival_failure_label(self):
        p=extract_three_mob_features(self.prepared,self.world)
        sessions=[{
            "engine_sha":"engine","scenario_id":"fixed","probe":p,
            "result":{"status":"UNVERIFIED_ERROR","confirmed_kills":0},
        }]
        model=train_supervised(sessions,engine_sha="engine",scenario_id="fixed")
        self.assertEqual(model["labeled_100_runs"],0)
        self.assertIsNone(model["survival_model"])



if __name__=="__main__":
    unittest.main()
