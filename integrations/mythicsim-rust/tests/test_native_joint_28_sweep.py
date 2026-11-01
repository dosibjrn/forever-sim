"""Fail-closed 28-profile JOINT breadth/promotion contracts (mock rows only).

No fake metric from this file may be presented as native evidence.
"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_joint_28_sweep import build_matrix, preflight, gap_summary


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
            return {"status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
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

    def test_source_bounded_paid_rows_are_never_promotable(self):
        rows = build_matrix(inventory(), stage=5,
                            run=lambda _: {"status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                                           "native_paid": 10, "three_axis_paid": 5,
                                           "replay_matches": True,
                                           "full_source_legality_certified": False})
        self.assertFalse(rows[0]["promotable"])
        self.assertFalse(rows[0]["process_gate_pass"])
        self.assertEqual("BLOCKED_FULL_SOURCE_LEGALITY", rows[0]["promotion_blocker"])

    def test_30_second_stage_rejects_partial_paid_prior(self):
        prior = {"status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                 "native_paid": 100, "replay_matches": True,
                 "full_source_legality_certified": False}
        self.assertEqual("BLOCKED_FULL_SOURCE_LEGALITY",
                         preflight("druid/feral_cat", {}, {}, 30, prior)[0])

    def test_300_second_stage_requires_validated_30_second_prior(self):
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         preflight("druid/feral_cat", {}, {}, 300, None)[0])
        prior = {"status": "FULL_SOURCE_NATIVE_JOINT",
                 "native_paid": 10, "replay_matches": False,
                 "full_source_legality_certified": True}
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         preflight("druid/feral_cat", {}, {}, 300, prior)[0])

    def test_gaps_include_precise_root_cause_and_no_fake_scores(self):
        rows = build_matrix(inventory(), stage=5,
                            run=lambda _: {"status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                                           "native_paid": 1, "three_axis_paid": 1,
                                           "full_source_legality_certified": False})
        gaps = gap_summary(rows)
        self.assertEqual(28, sum(g["count"] for g in gaps))
        self.assertTrue(any(g["cause"] == "VERIFY_PER_RANK_TALENTS_AND_FULL_EQUIP_RULES"
                            for g in gaps))
        self.assertTrue(all("score" not in row for row in rows))


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


if __name__ == "__main__":
    unittest.main()
