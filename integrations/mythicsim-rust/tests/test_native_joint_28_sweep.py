"""Fail-closed 28-profile JOINT breadth/promotion contracts (mock rows only).

No fake metric from this file may be presented as native evidence.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_joint_28_sweep import build_matrix, preflight, gap_summary, save_report
from native_l60_matrix import (
    CURRENT_CLIENT_BUILD, CURRENT_ENGINE_PIN, CURRENT_CLIENT_TALENT_OVERRIDES,
    apply_current_client_talent_override,
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
            return {"status": "NATIVE_JOINT_SOURCE_BOUNDED_SCREEN",
                    "native_paid": 2, "three_axis_paid": 1,
                    "full_source_legality_certified": False}
        rows = build_matrix(inventory(), stage=5, run=run)
        self.assertEqual(28, len(rows))
        self.assertEqual([x[0]["profile_id"] for x in inventory()],
                         [x["profile_id"] for x in rows])
        self.assertEqual(25, len(calls))

    def test_missing_source_is_isolated_without_running_scorer(self):
        rows = inventory()
        rows[0] = ({**rows[0][0], "blocker": "missing exact request"}, None)
        calls = []
        def run(profile):
            calls.append(profile)
            return {"status": "BLOCKED_SOURCE_LEGALITY", "native_paid": 0,
                    "full_source_legality_certified": False}
        results = build_matrix(rows, stage=5, run=run)
        self.assertEqual("BLOCKED_SOURCE", results[0]["status"])
        self.assertNotIn("druid/feral_cat", calls)

    def test_non_dps_objectives_are_not_silently_scored_as_dps(self):
        for profile, status in (("druid/restoration", "BLOCKED_OBJECTIVE"),
                                ("warrior/protection", "BLOCKED_OBJECTIVE"),
                                ("priest/discipline", "BLOCKED_SPEC_IDENTITY")):
            self.assertEqual(status, preflight(profile, {}, {}, 5)[0])

    def test_native_paid_rows_are_not_p7_promotable_but_can_advance_screen(self):
        rows = build_matrix(inventory(), stage=5,
                            run=lambda _: {"status": "NATIVE_JOINT_SOURCE_BOUNDED_SCREEN",
                                           "native_paid": 10, "three_axis_paid": 5,
                                           "native_errors": 0, "replay_matches": True})
        self.assertFalse(rows[0]["promotable"])
        self.assertFalse(rows[0]["process_gate_pass"])
        self.assertTrue(rows[0]["next_stage_eligible"])
        self.assertIsNone(rows[0]["promotion_blocker"])

    def test_30_second_stage_accepts_native_paid_three_axis_replay_without_python_proof(self):
        prior = {"status": "NATIVE_JOINT_SOURCE_BOUNDED_SCREEN",
                 "native_paid": 100, "three_axis_paid": 25,
                 "native_errors": 0, "replay_matches": True,
                 "full_source_legality_certified": False}
        self.assertIsNone(preflight("druid/feral_cat", {}, {}, 30, prior))

    def test_30_second_stage_rejects_missing_native_three_axis_or_replay(self):
        prior = {"status": "NATIVE_JOINT_SOURCE_BOUNDED_SCREEN",
                 "native_paid": 100, "three_axis_paid": 0,
                 "native_errors": 0, "replay_matches": True}
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         preflight("druid/feral_cat", {}, {}, 30, prior)[0])
        prior["three_axis_paid"] = 1
        prior["native_errors"] = 1
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         preflight("druid/feral_cat", {}, {}, 30, prior)[0])

    def test_300_second_stage_requires_exact_30_second_replay(self):
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         preflight("druid/feral_cat", {}, {}, 300, None)[0])
        prior = {"status": "NATIVE_JOINT_SOURCE_BOUNDED_SCREEN",
                 "native_paid": 10, "three_axis_paid": 1,
                 "native_errors": 0, "replay_matches": False}
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         preflight("druid/feral_cat", {}, {}, 300, prior)[0])
        prior["replay_matches"] = True
        self.assertIsNone(preflight("druid/feral_cat", {}, {}, 300, prior))

    def test_gaps_include_precise_root_cause_and_no_fake_scores(self):
        rows = build_matrix(inventory(), stage=5,
                            run=lambda _: {"status": "NATIVE_JOINT_SOURCE_BOUNDED_SCREEN",
                                           "native_paid": 1, "three_axis_paid": 1,
                                           "native_errors": 0, "replay_matches": True})
        gaps = gap_summary(rows)
        self.assertEqual(28, sum(g["count"] for g in gaps))
        self.assertTrue(any(g["cause"] == "NATIVE_JOINT_PAID_SCREEN_ONLY"
                            for g in gaps))
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
                "status": "NATIVE_JOINT_SOURCE_BOUNDED_SCREEN",
                "native_paid": 2,
                "baseline_paid": 1,
                "native_paid_total": 3,
                "baseline_balanced_score": 101.25,
                "best_balanced_screen": 111.5,
                "three_axis_paid": 1,
                "native_errors": 0,
                "replay_matches": True,
                "blocker": None,
                "promotion_blocker": None,
            }]

            save_report(out, rows, stage=5, binary=binary, engine_src=engine_src)

            provenance = json.loads((out / "provenance.json").read_text())
            self.assertEqual("balanced", provenance["candidate_rng_mode"])
            self.assertEqual("stochastic", provenance["holdout_rng_mode"])
            self.assertEqual("NOT_RUN_STAGE_5", provenance["holdout_status"])
            self.assertFalse(provenance["process_p7_pass"])
            matrix = (out / "matrix.md").read_text()
            self.assertIn("Baseline balanced", matrix)
            self.assertIn("101.25", matrix)
            self.assertIn("111.5", matrix)


class SourceBlockerClassification(unittest.TestCase):
    def test_source_legal_gaps_are_split_by_actionable_root_cause(self):
        rows = [
            {"profile_id": "hunter/survival", "status": "BLOCKED_SOURCE_LEGALITY",
             "blocker": "BLOCKED_GEAR_POOL: no source-bounded legal alternate item"},
            {"profile_id": "mage/fire", "status": "BLOCKED_SOURCE_LEGALITY",
             "blocker": "BLOCKED_TALENTS: need two independent full 51-point same-class source builds"},
            {"profile_id": "rogue/assassination", "status": "BLOCKED_SOURCE_LEGALITY",
             "blocker": "Not a two- or three-tree source talent allocation"},
            {"profile_id": "priest/shadow", "status": "BLOCKED_SOURCE_LEGALITY",
             "blocker": "Unexpected source validation error"},
        ]
        categories = {entry["cause"]: entry["count"] for entry in gap_summary(rows)}
        self.assertEqual({
            "SOURCE_GEAR_POOL_MISSING": 1,
            "SOURCE_TALENT_DONORS_MISSING": 1,
            "SOURCE_TALENT_ENCODING_INVALID": 1,
            "INVESTIGATE_SOURCE_LEGALITY": 1,
        }, categories)



class CurrentClientTalentOverrideContracts(unittest.TestCase):
    def test_five_stale_smoke_rows_use_pinned_upstream_presets(self):
        expected = {
            "druid/feral_cat": "ClassDruid",
            "mage/arcane": "ClassMage",
            "mage/fire": "ClassMage",
            "mage/frost": "ClassMage",
            "paladin/retribution": "ClassPaladin",
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
                self.assertEqual(CURRENT_CLIENT_BUILD, metadata["client_build"])
                self.assertEqual(CURRENT_ENGINE_PIN, metadata["engine_pin"])
                self.assertEqual("wowsims/forever", metadata["source_repo"])
                self.assertTrue(metadata["source_commit"])
                self.assertTrue(metadata["source_blob_sha"])
                self.assertTrue(metadata["source_url"].startswith(
                    "https://github.com/wowsims/forever/blob/"
                ))

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
            run=lambda _: {"status": "NATIVE_JOINT_SOURCE_BOUNDED_SCREEN",
                           "native_paid": 1, "three_axis_paid": 0,
                           "full_source_legality_certified": False},
        )
        self.assertEqual("fixture-sha", results[0]["source_fixture_sha256"])
        self.assertEqual("effective-request-sha",
                         results[0]["effective_source_request_fingerprint"])
        self.assertEqual(metadata, results[0]["talent_override"])



if __name__ == "__main__":
    unittest.main()
