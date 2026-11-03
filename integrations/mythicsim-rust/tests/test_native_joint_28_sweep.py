"""28-profile JOINT diagnostic/reporting contracts (mock rows only).

No fake metric from this file may be presented as native evidence.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_joint_28_sweep import build_matrix, preflight, gap_summary, save_report
from native_joint_two_class import objective_for_profile
from native_l60_matrix import (
    CURRENT_CLIENT_BUILD, CURRENT_ENGINE_PIN, CURRENT_CLIENT_TALENT_OVERRIDES,
    SOURCES, apply_current_client_talent_override,
    CURRENT_CLIENT_TALENT_DONOR_PRESETS, current_client_talent_donor_fixtures,
    fingerprint,
)


def inventory():
    names = (["druid/feral_cat", "druid/restoration", "priest/discipline",
              "warrior/protection"] + [f"mage/spec_{i}" for i in range(24)])
    return [({"profile_id": p, "source_sha256": "source-" + p,
              "source_type": "SMOKE_FIXTURE_ONLY",
              "blocker": None}, {"raid": {"parties": []}}) for p in names]


class SweepContracts(unittest.TestCase):
    def test_28_rows_are_kept_in_canonical_order(self):
        calls = []
        def run(profile):
            calls.append(profile)
            return {"status": "NATIVE_JOINT_PAID",
                    "native_paid": 2, "three_axis_paid": 1,
                    "native_errors": 0, "replay_matches": True}
        rows = build_matrix(inventory(), stage=5, run=run)
        self.assertEqual(28, len(rows))
        self.assertEqual([x[0]["profile_id"] for x in inventory()],
                         [x["profile_id"] for x in rows])
        self.assertEqual(28, len(calls))
        self.assertEqual("DPS", rows[0]["objective"])
        self.assertEqual("HPS", rows[1]["objective"])
        self.assertEqual("HPS", rows[2]["objective"])
        self.assertEqual("TPS", rows[3]["objective"])

    def test_missing_source_is_isolated_without_running_scorer(self):
        rows = inventory()
        rows[0] = ({**rows[0][0], "blocker": "missing exact request"}, None)
        calls = []
        def run(profile):
            calls.append(profile)
            return {"status": "BLOCKED_CANDIDATE_DOMAIN", "native_paid": 0}
        results = build_matrix(rows, stage=5, run=run)
        self.assertEqual("BLOCKED_SOURCE", results[0]["status"])
        self.assertNotIn("druid/feral_cat", calls)

    def test_heal_and_tank_profiles_use_their_native_objectives(self):
        cases = (
            ("druid/restoration", "HPS"),
            ("priest/discipline", "HPS"),
            ("priest/holy", "HPS"),
            ("warrior/protection", "TPS"),
            ("mage/fire", "DPS"),
        )
        for profile, objective in cases:
            with self.subTest(profile=profile):
                self.assertEqual(objective, objective_for_profile(profile))
                self.assertIsNone(preflight(profile, {}, {}, 5))
        self.assertIsNone(preflight("priest/discipline", {}, {}, 5))

    def test_native_paid_replay_is_sufficient_for_30_second_stage(self):
        prior = {"status": "NATIVE_JOINT_PAID", "native_paid": 100,
                 "three_axis_paid": 10, "replay_matches": True, "native_errors": 0,
                 "native_unscored": 3, "native_refusals": 50}
        self.assertIsNone(preflight("druid/feral_cat", {}, {}, 30, prior))

    def test_30_second_stage_rejects_prior_without_native_paid_replay(self):
        prior = {"status": "BLOCKED_NATIVE_REFUSALS", "native_paid": 0,
                 "three_axis_paid": 0, "replay_matches": False, "native_errors": 0,
                 "native_refusals": 100}
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         preflight("druid/feral_cat", {}, {}, 30, prior)[0])

    def test_300_second_stage_requires_native_paid_replay_at_30_seconds(self):
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         preflight("druid/feral_cat", {}, {}, 300, None)[0])
        prior = {"status": "NATIVE_JOINT_PAID", "native_paid": 10,
                 "three_axis_paid": 5, "replay_matches": True, "native_errors": 0,
                 "native_refusals": 4}
        self.assertIsNone(preflight("druid/feral_cat", {}, {}, 300, prior))
        prior["replay_matches"] = False
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         preflight("druid/feral_cat", {}, {}, 300, prior)[0])

    def test_gaps_report_only_unresolved_profiles_not_legality_certificates(self):
        rows = build_matrix(inventory(), stage=5,
                            run=lambda _: {"status": "NATIVE_JOINT_PAID",
                                           "native_paid": 1, "three_axis_paid": 1,
                                           "native_errors": 0, "native_unscored": 2,
                                           "replay_matches": True})
        gaps = gap_summary(rows)
        self.assertEqual([], gaps)
        causes = {g["cause"] for g in gaps}
        self.assertNotIn("VERIFY_DISCIPLINE_FIXTURE_IDENTITY", causes)
        self.assertNotIn("NATIVE_SCORE_UNAVAILABLE", causes)
        self.assertTrue(all("score" not in row for row in rows))

    def test_report_contains_balanced_baseline_best_and_exact_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine_src = root / "engine"
            data = engine_src / "data"
            data.mkdir(parents=True)
            for name in ("items", "enchants", "spells"):
                (data / (name + ".jsonl")).write_text("{}\\n")
            binary = root / "forever-engine"
            binary.write_bytes(b"test-native-binary")
            out = root / "report"
            rows = [{
                "profile_id": "druid/feral_cat",
                "status": "NATIVE_JOINT_PAID",
                "native_paid": 2,
                "baseline_paid": 1,
                "native_paid_total": 3,
                "baseline_balanced_score": 101.25,
                "best_balanced_screen": 111.5,
                "three_axis_paid": 1,
                "native_errors": 0,
                "native_unscored": 2,
                "replay_matches": True,
                "blocker": None,
            }]

            save_report(out, rows, stage=5, binary=binary, engine_src=engine_src)

            provenance = json.loads((out / "provenance.json").read_text())
            self.assertEqual("balanced", provenance["candidate_rng_mode"])
            self.assertEqual("stochastic", provenance["holdout_rng_mode"])
            self.assertEqual("NOT_RUN_STAGE_5", provenance["holdout_status"])
            self.assertEqual("PINNED_NATIVE_CANDIDATE_DOMAIN", provenance["source_scope"])
            self.assertNotIn("process_p7_pass", provenance)
            matrix = (out / "matrix.md").read_text()
            self.assertIn("Objective", matrix)
            self.assertIn("Baseline balanced", matrix)
            self.assertIn("Unscored", matrix)
            self.assertIn("| druid/feral_cat | DPS | NATIVE_JOINT_PAID | 101.25 | 111.5 | 2 | 1 | 1 | 2 |", matrix)
            self.assertIn("101.25", matrix)
            self.assertIn("111.5", matrix)
            self.assertIn("diagnostic", matrix.lower())
            self.assertNotIn("full legal", matrix.lower())
            self.assertNotIn("promotion_blocker", matrix)


class CandidateDomainBlockerClassification(unittest.TestCase):
    def test_candidate_pool_gaps_are_split_by_actionable_root_cause(self):
        rows = [
            {"profile_id": "hunter/survival", "status": "BLOCKED_CANDIDATE_DOMAIN",
             "blocker": "BLOCKED_GEAR_POOL: no source-observed alternate item"},
            {"profile_id": "mage/fire", "status": "BLOCKED_CANDIDATE_DOMAIN",
             "blocker": "BLOCKED_TALENTS: need two distinct source-observed talent proposals"},
            {"profile_id": "rogue/assassination", "status": "BLOCKED_CANDIDATE_DOMAIN",
             "blocker": "No source-observed talent proposal in this candidate domain"},
            {"profile_id": "priest/shadow", "status": "BLOCKED_CANDIDATE_DOMAIN",
             "blocker": "Unexpected source validation error"},
        ]
        categories = {entry["cause"]: entry["count"] for entry in gap_summary(rows)}
        self.assertEqual({
            "SOURCE_GEAR_POOL_MISSING": 1,
            "SOURCE_TALENT_DONORS_MISSING": 1,
            "INVESTIGATE_CANDIDATE_DOMAIN": 2,
        }, categories)



class CurrentClientTalentOverrideContracts(unittest.TestCase):

    def test_alternate_upstream_presets_expand_four_no_three_axis_donor_domains(self):
        baselines = {
            "druid/feral_cat": ("ClassDruid", "050022-35200032123010125011-055"),
            "mage/arcane": ("ClassMage", "050205223101311531-5500003-003"),
            "mage/fire": ("ClassMage", "0502052001001-55500001230133031-003"),
            "mage/frost": ("ClassMage", "0502052011003--053500021100331251"),
        }
        inventory_rows = []
        original_requests = {}
        for profile, (class_name, talents) in baselines.items():
            request = {
                "raid": {"parties": [{"players": [{
                    "class": class_name,
                    "talentsString": talents,
                    "equipment": {"items": [{"id": 123}, {"id": 456}]},
                    "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": 133}}}]},
                }]}]},
                "encounter": {"duration": 60},
                "simOptions": {"iterations": 40, "randomSeed": "731"},
            }
            original_requests[profile] = request
            inventory_rows.append(({"profile_id": profile}, request))

        donors = current_client_talent_donor_fixtures(inventory_rows)
        self.assertEqual(7, len(donors))
        expected = {
            ("druid/feral_cat", "Hybrid"),
            ("mage/arcane", "Arcane Fire"), ("mage/arcane", "FFB"),
            ("mage/fire", "Arcane Fire"), ("mage/fire", "FFB"),
            ("mage/frost", "Arcane Fire"), ("mage/frost", "FFB"),
        }
        self.assertEqual(expected, {
            (donor["composed_over_profile"], donor["talent_preset_name"])
            for donor in donors
        })
        for donor in donors:
            profile = donor["composed_over_profile"]
            original = original_requests[profile]
            donor_player = donor["request"]["raid"]["parties"][0]["players"][0]
            original_player = original["raid"]["parties"][0]["players"][0]
            self.assertEqual(original_player["equipment"], donor_player["equipment"])
            self.assertEqual(original_player["rotation"], donor_player["rotation"])
            self.assertEqual(original["encounter"], donor["request"]["encounter"])
            self.assertEqual(original["simOptions"], donor["request"]["simOptions"])
            self.assertEqual(donor["talent_string"], donor_player["talentsString"])
            self.assertEqual("PINNED_UPSTREAM_CURRENT_CLIENT_TALENT_PRESET_DONOR", donor["source_type"])
            self.assertEqual("wowsims/forever", donor["talent_source_repository"])
            self.assertEqual("43df34d7fb8145fab89199654cc49aba72f04f02",
                             donor["talent_source_commit"])
            self.assertTrue(donor["talent_source_blob_sha"])
            self.assertEqual(fingerprint(donor["request"]), donor["source_sha256"])
            self.assertEqual(CURRENT_CLIENT_BUILD, donor["client_build"])
            self.assertEqual(CURRENT_ENGINE_PIN, donor["engine_pin"])

    def test_nine_stale_smoke_rows_use_pinned_upstream_talent_sources(self):
        expected = {
            "druid/feral_cat": "ClassDruid",
            "druid/feral_bear": "ClassDruid",
            "mage/arcane": "ClassMage",
            "mage/fire": "ClassMage",
            "mage/frost": "ClassMage",
            "paladin/holy": "ClassPaladin",
            "paladin/protection": "ClassPaladin",
            "paladin/retribution": "ClassPaladin",
            "priest/discipline": "ClassPriest",
        }
        self.assertEqual(set(expected), set(CURRENT_CLIENT_TALENT_OVERRIDES))
        for profile, class_name in expected.items():
            with self.subTest(profile=profile):
                request = {
                    "raid": {"parties": [{"players": [{
                        "class": class_name,
                        "talentsString": "legacy-source-string",
                        "equipment": {"items": [{"id": 123}]},
                    }]}]},
                    "encounter": {"duration": 60},
                }
                original = json.loads(json.dumps(request))
                effective, metadata = apply_current_client_talent_override(profile, request)
                player = effective["raid"]["parties"][0]["players"][0]
                override = CURRENT_CLIENT_TALENT_OVERRIDES[profile]
                self.assertEqual(override["talents_string"], player["talentsString"])
                self.assertEqual("legacy-source-string",
                                 request["raid"]["parties"][0]["players"][0]["talentsString"])
                self.assertEqual(original["raid"]["parties"][0]["players"][0]["equipment"],
                                 player["equipment"])
                self.assertEqual(original["encounter"], effective["encounter"])
                self.assertEqual("APPLIED", metadata["status"])
                self.assertEqual(
                    override.get("source_type", "PINNED_UPSTREAM_CURRENT_CLIENT_TALENT_PRESET"),
                    metadata["source_type"],
                )
                self.assertEqual(
                    override.get(
                        "scope",
                        "TALENT_PRESET_ONLY; original smoke-fixture gear, encounter and APL retained",
                    ),
                    metadata["scope"],
                )
                self.assertEqual(override.get("upstream_pr"), metadata["source_pull_request"])
                self.assertEqual(override["source_path"], metadata["source_path"])
                self.assertEqual(override["source_blob_sha"], metadata["source_blob_sha"])
                self.assertEqual(override["preset_name"], metadata["preset_name"])
                self.assertEqual(CURRENT_CLIENT_BUILD, metadata["client_build"])
                self.assertEqual(CURRENT_ENGINE_PIN, metadata["engine_pin"])
                self.assertEqual("wowsims/forever", metadata["source_repo"])
                self.assertTrue(metadata["source_commit"])
                self.assertTrue(metadata["source_blob_sha"])
                self.assertTrue(metadata["source_url"].startswith(
                    "https://github.com/wowsims/forever/blob/"
                ))


    def test_three_invalid_baselines_use_exact_pinned_current_client_talent_sources(self):
        expected = {
            "druid/feral_bear": {
                "talents_string": "050022-2322030212310212501-055",
                "source_commit": "c96ec787be9529a934d19a1d9b8156524a176b5e",
                "source_path": "ui/specs/druid/feralbear/presets.ts",
                "source_blob_sha": "51e09cf57affbdced3a23cce0629ebaab836f8c6",
                "preset_name": "Bear",
            },
            "paladin/holy": {
                "talents_string": "55320015022101251-503020005001",
                "source_commit": "d608072a6db0197d58a073df7e3153c90f20f46c",
                "source_path": "sim/paladin/holy/holy_test.go",
                "source_blob_sha": "bff116c8fe0727c96b51d51c97d637c4f189ba5c",
                "preset_name": "StandardTalents (sim test)",
            },
            "paladin/protection": {
                "talents_string": "050050002-05302102213301531-502",
                "source_commit": "d608072a6db0197d58a073df7e3153c90f20f46c",
                "source_path": "ui/specs/paladin/protection/presets.ts",
                "source_blob_sha": "a59c83c7581d2aafb19f3265bfd10298722782bf",
                "preset_name": "Default",
            },
        }
        for profile, values in expected.items():
            with self.subTest(profile=profile):
                override = CURRENT_CLIENT_TALENT_OVERRIDES[profile]
                for key, value in values.items():
                    self.assertEqual(value, override[key])
                self.assertEqual("ClassDruid" if profile.startswith("druid/") else "ClassPaladin",
                                 override["class_name"])
                if profile == "paladin/holy":
                    self.assertEqual(
                        "PINNED_UPSTREAM_NATIVE_TEST_TALENT_FIXTURE",
                        override["source_type"],
                    )
                    self.assertIn("simulator StandardTalents test build", override["scope"])
                else:
                    self.assertNotIn("source_type", override)


    def test_discipline_profile_uses_upstream_disc_preset_over_healer_source(self):
        self.assertEqual(
            ("engine", "fixtures/healers/holy-priest.request.json"),
            SOURCES["priest/discipline"],
        )
        self.assertEqual(SOURCES["priest/holy"], SOURCES["priest/discipline"])
        self.assertEqual("HPS", objective_for_profile("priest/discipline"))
        self.assertIsNone(preflight("priest/discipline", {}, {"raid": {}}, 5))

        request = {
            "raid": {"parties": [{"players": [{
                "class": "ClassPriest",
                "talentsString": "00520101133-33505003030121531",
                "healerPriest": {"innerFire": True},
                "equipment": {"items": [{"id": 123}]},
                "rotation": {"priorityList": [{
                    "action": {"castSpell": {
                        "spellId": {"spellId": 401859},
                        "target": {"type": "Self"},
                    }},
                }]},
            }]}]},
            "encounter": {"duration": 180},
        }
        effective, metadata = apply_current_client_talent_override(
            "priest/discipline", request
        )
        player = effective["raid"]["parties"][0]["players"][0]
        self.assertEqual(
            "005025021330011531-335001030301", player["talentsString"]
        )
        self.assertIn("healerPriest", player)
        self.assertNotIn("dpsPriest", player)
        self.assertEqual(request["raid"]["parties"][0]["players"][0]["equipment"],
                         player["equipment"])
        self.assertEqual(request["raid"]["parties"][0]["players"][0]["rotation"],
                         player["rotation"])
        self.assertEqual(request["encounter"], effective["encounter"])
        self.assertEqual("Disc", metadata["preset_name"])
        self.assertIsNone(metadata["source_pull_request"])
        self.assertEqual(
            "a0ab835726319b558318cce186c88c4bd3a855dd",
            metadata["source_commit"],
        )
        self.assertEqual(
            "87fe551e2150ead167dbb5c2418f332bed02549c",
            metadata["source_blob_sha"],
        )

    def test_unlisted_profile_is_left_untouched(self):
        request = {"raid": {"parties": [{"players": [{
            "class": "ClassMage", "talentsString": "unchanged",
        }]}]}}
        effective, metadata = apply_current_client_talent_override("mage/shadow", request)
        self.assertIs(request, effective)
        self.assertIsNone(metadata)
        self.assertEqual("unchanged", request["raid"]["parties"][0]["players"][0]["talentsString"])

    def test_profile_class_mismatch_fails_closed(self):
        request = {"raid": {"parties": [{"players": [{
            "class": "ClassPaladin", "talentsString": "legacy",
        }]}]}}
        with self.assertRaisesRegex(ValueError, "class mismatch"):
            apply_current_client_talent_override("mage/fire", request)

    def test_override_source_provenance_survives_matrix_report(self):
        rows = inventory()
        metadata = {
            "source_commit": "43df34d7fb8145fab89199654cc49aba72f04f02",
            "replacement_talents_string": "050205223101311531-5500003-003",
        }
        rows[0][0].update({
            "source_fixture_sha256": "fixture-sha",
            "effective_source_request_fingerprint": "effective-request-sha",
            "talent_override": metadata,
        })
        results = build_matrix(
            rows, stage=5,
            run=lambda _: {"status": "NATIVE_JOINT_PAID",
                           "native_paid": 1, "three_axis_paid": 1,
                           "native_errors": 0, "replay_matches": True},
        )
        self.assertEqual("fixture-sha", results[0]["source_fixture_sha256"])
        self.assertEqual("effective-request-sha",
                         results[0]["effective_source_request_fingerprint"])
        self.assertEqual(metadata, results[0]["talent_override"])



if __name__ == "__main__":
    unittest.main()
