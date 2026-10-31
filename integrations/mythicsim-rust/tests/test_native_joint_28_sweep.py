"""Fail-closed 28-profile JOINT breadth/promotion contracts (mock rows only).

No fake metric from this file may be presented as native evidence.
"""
import sys
import subprocess
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_joint_28_sweep import build_matrix, preflight, gap_summary, cold_stage_seed


def inventory():
    names = (["druid/feral_cat", "druid/restoration", "priest/discipline",
              "warrior/protection"] + [f"mage/spec_{i}" for i in range(24)])
    return [({"profile_id": p, "source_sha256": "source-" + p,
              "source_type": "SMOKE_FIXTURE_ONLY",
              "blocker": None}, {"raid": {"parties": []}}) for p in names]


class SweepContracts(unittest.TestCase):
    def test_5_30_300_are_independent_reproducible_cold_seed_streams(self):
        # No stage may silently replay the same RNG stream as the 5s
        # breadth search; profile identities also need separate streams.
        seeds = [cold_stage_seed(731, stage, idx)
                 for stage in (5, 30, 300) for idx in range(28)]
        self.assertEqual(84, len(set(seeds)))
        self.assertTrue(all(0 < seed < (1 << 63) for seed in seeds))
        self.assertEqual(seeds[0], cold_stage_seed(731, 5, 0))
        self.assertNotEqual(seeds[0], cold_stage_seed(732, 5, 0))
        with self.assertRaises(ValueError):
            cold_stage_seed(731, 17, 0)
        with self.assertRaises(ValueError):
            cold_stage_seed(731, 5, -1)

    def test_28_rows_are_kept_in_canonical_order(self):
        calls = []
        def run(profile):
            calls.append(profile)
            return {"status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                    "native_paid": 2, "three_axis_paid": 1,
                    "replay_matches": True,
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

    def test_promotion_requires_exact_prior_stage_profile_and_source_sha(self):
        profile = "druid/feral_cat"
        source = {"profile_id": profile, "source_sha256": "pinned-source-A"}
        provenance = {
            "native_binary_sha256": "bin-sha",
            "native_db_sha256": {
                "items": "item-sha", "enchants": "enchant-sha",
                "spells": "spell-sha",
            },
        }
        prior = {
            "profile_id": profile, "stage_seconds": 5,
            "source_sha256": "pinned-source-A",
            "status": "FULL_SOURCE_NATIVE_JOINT",
            "full_source_legality_certified": True,
            "native_paid": 3, "native_errors": 0, "replay_matches": True,
            **provenance,
        }
        def gate(stage, old=prior, src=source, hashes=provenance):
            return preflight(profile, src, {}, stage, old,
                             current_provenance=hashes)
        self.assertIsNone(gate(30))
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         gate(30, {**prior, "stage_seconds": 30})[0])
        self.assertEqual("BLOCKED_PRIOR_STAGE", gate(300)[0])
        self.assertEqual("BLOCKED_PRIOR_STAGE",
                         gate(30, {**prior, "profile_id": "mage/fire"})[0])
        self.assertEqual("BLOCKED_SOURCE_PROVENANCE",
                         gate(30, {**prior, "source_sha256": "different-source"})[0])
        self.assertEqual("BLOCKED_SOURCE_PROVENANCE",
                         gate(30, prior, {**source, "source_sha256": None})[0])
        self.assertIsNone(gate(300, {**prior, "stage_seconds": 30}))
        self.assertEqual("BLOCKED_ENGINE_PROVENANCE",
                         gate(30, prior, source, None)[0])

    def test_stage_promotion_requires_identical_pinned_rust_binary_and_db(self):
        # Source SHA alone cannot certify a 5s -> 30s -> 300s chain:
        # the prior stage must have run with the SAME pinned Rust engine and DB.
        profile = "druid/feral_cat"
        source = {"profile_id": profile, "source_sha256": "fixture-a"}
        provenance = {
            "native_binary_sha256": "rust-bin-a",
            "native_db_sha256": {
                "items": "items-a", "enchants": "enchants-a",
                "spells": "spells-a",
            },
        }
        prior = {
            "profile_id": profile, "stage_seconds": 5,
            "source_sha256": "fixture-a",
            "status": "FULL_SOURCE_NATIVE_JOINT",
            "full_source_legality_certified": True,
            "native_paid": 3, "native_errors": 0,
            "replay_matches": True, **provenance,
        }
        self.assertIsNone(preflight(
            profile, source, {}, 30, prior,
            current_provenance=provenance))
        self.assertEqual("BLOCKED_ENGINE_PROVENANCE", preflight(
            profile, source, {}, 30,
            {**prior, "native_binary_sha256": "different-bin"},
            current_provenance=provenance)[0])
        self.assertEqual("BLOCKED_ENGINE_PROVENANCE", preflight(
            profile, source, {}, 30,
            {**prior, "native_db_sha256": {
                **provenance["native_db_sha256"], "items": "different-db"}},
            current_provenance=provenance)[0])
        self.assertEqual("BLOCKED_ENGINE_PROVENANCE", preflight(
            profile, source, {}, 30,
            {k: v for k, v in prior.items() if k != "native_binary_sha256"},
            current_provenance=provenance)[0])
        self.assertEqual("BLOCKED_ENGINE_PROVENANCE", preflight(
            profile, source, {}, 30, prior,
            current_provenance={"native_binary_sha256": "rust-bin-a",
                                "native_db_sha256": {}})[0])

    def test_stage_matrix_rejects_engine_mismatch_before_any_native_call(self):
        # Production orchestration must pass current hashes through preflight.
        source = inventory()
        prior = {}
        current = {
            "native_binary_sha256": "binary-current",
            "native_db_sha256": {
                "items": "items-current", "enchants": "enchants-current",
                "spells": "spells-current",
            },
        }
        for inv, _request in source:
            prior[inv["profile_id"]] = {
                "profile_id": inv["profile_id"], "stage_seconds": 5,
                "source_sha256": inv["source_sha256"],
                "status": "FULL_SOURCE_NATIVE_JOINT",
                "full_source_legality_certified": True,
                "native_paid": 1, "native_errors": 0,
                "replay_matches": True,
                "native_binary_sha256": "old-binary",
                "native_db_sha256": current["native_db_sha256"],
            }
        calls = []
        rows = build_matrix(
            source, stage=30, prior_rows=prior,
            native_provenance=current,
            run=lambda profile: calls.append(profile),
        )
        self.assertEqual([], calls)
        self.assertEqual("BLOCKED_ENGINE_PROVENANCE", rows[0]["status"])
        self.assertEqual(0, rows[0]["native_paid"])
        self.assertEqual("RESTORE_EXACT_NATIVE_ENGINE_AND_DB_SHA_FOR_STAGE_CHAIN",
                         next(g["cause"] for g in gap_summary(rows)
                              if g["cause"].startswith("RESTORE_EXACT_NATIVE_ENGINE")))
        self.assertEqual(28, len(rows))

    def test_paid_adapter_cannot_rewrite_canonical_identity_or_source(self):
        # A scored result is untrusted metadata.  A wrong-profile or wrong-
        # fixture row must fail loudly, not poison the stage-chain ledger.
        source = inventory()
        for forged in (
            {"profile_id": "mage/fire"},
            {"source_sha256": "different-source"},
            {"source_type": "PINNED_RANKING_REFERENCE"},
            {"stage_seconds": 300},
        ):
            def run(_profile):
                return {
                    "status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                    "native_paid": 1, "three_axis_paid": 1,
                    "full_source_legality_certified": False,
                    **forged,
                }
            with self.subTest(forged=forged), self.assertRaises(ValueError):
                build_matrix(source, stage=5, run=run)

    def test_paid_adapter_cannot_claim_full_source_or_process_status(self):
        # A source-bounded scorer must not forge a fully legal row by changing
        # only the status string while leaving certification flags false.
        for forged_status in ("FULL_SOURCE_NATIVE_JOINT", "RAN", "P7_PASS"):
            with self.subTest(status=forged_status), self.assertRaises(ValueError):
                build_matrix(inventory(), stage=5, run=lambda _: {
                    "status": forged_status,
                    "native_paid": 1, "three_axis_paid": 1,
                    "replay_matches": True,
                    "full_source_legality_certified": False,
                    "process_gate_pass": False,
                })

    def test_source_bounded_joint_needs_real_paid_three_axis_replay(self):
        # These are deliberately mocked corrupt rows, never real native scores.
        for forged in (
            {"native_paid": 0, "three_axis_paid": 0, "replay_matches": True},
            {"native_paid": 2, "three_axis_paid": 0, "replay_matches": True},
            {"native_paid": 1, "three_axis_paid": 2, "replay_matches": True},
            {"native_paid": 1, "three_axis_paid": 1, "replay_matches": False},
            {"native_paid": 1, "three_axis_paid": 1},
        ):
            with self.subTest(forged=forged), self.assertRaises(ValueError):
                build_matrix(inventory(), stage=5, run=lambda _: {
                    "status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                    "full_source_legality_certified": False,
                    **forged,
                })

    def test_failed_native_source_baseline_cannot_be_reported_as_joint_success(self):
        # A source request rejected by real Rust cannot be a comparable
        # baseline, even when other source-bounded candidates score and replay.
        # Preserve those paid diagnostics but never call the row successful.
        from native_joint_two_class import mark_failed_source_baseline
        measured = {
            "status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
            "baseline_status": "BLOCKED_NATIVE_BASELINE",
            "baseline_error": "Rust rejected frozen source",
            "baseline_native_paid": 0,
            "native_paid": 3, "three_axis_paid": 2,
            "replay_matches": True,
        }
        mark_failed_source_baseline(measured)
        self.assertEqual("BLOCKED_NATIVE_BASELINE", measured["status"])
        self.assertEqual(3, measured["native_paid"])
        self.assertEqual(2, measured["three_axis_paid"])
        self.assertIn("frozen source", measured["blocker"].lower())
        rows = build_matrix(inventory(), stage=5, run=lambda _: measured.copy())
        self.assertEqual("BLOCKED_NATIVE_BASELINE", rows[0]["status"])
        self.assertEqual("REPLAY_FROZEN_NATIVE_SOURCE_BASELINE",
                         next(g["cause"] for g in gap_summary(rows)
                              if g["cause"] == "REPLAY_FROZEN_NATIVE_SOURCE_BASELINE"))
        self.assertFalse(rows[0]["promotable"])
        self.assertEqual("BLOCKED_NATIVE_BASELINE", rows[0]["promotion_blocker"])

    def test_successful_native_baseline_does_not_change_partial_legality(self):
        from native_joint_two_class import mark_failed_source_baseline
        row = {
            "status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
            "baseline_status": "RAN_NATIVE", "baseline_native_paid": 1,
            "baseline_balanced_native": 100.0,
        }
        mark_failed_source_baseline(row)
        self.assertEqual("SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                         row["status"])

    def test_matrix_rejects_adapter_claiming_success_after_failed_baseline(self):
        with self.assertRaisesRegex(ValueError, "failed native source baseline"):
            build_matrix(inventory(), stage=5, run=lambda _: {
                "status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                "baseline_status": "BLOCKED_NATIVE_BASELINE",
                "baseline_native_paid": 0,
                "native_paid": 2, "three_axis_paid": 1,
                "replay_matches": True,
            })
        with self.assertRaisesRegex(ValueError, "without paid native source baseline"):
            build_matrix(inventory(), stage=5, run=lambda _: {
                "status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                "baseline_status": "RAN_NATIVE",
                "baseline_native_paid": 0,
                "native_paid": 2, "three_axis_paid": 1,
                "replay_matches": True,
            })

    def test_source_talent_audit_is_preserved_in_matrix_and_gaps(self):
        source = inventory()
        source[0] = ({
            **source[0][0],
            "source_talent_points": 49,
            "source_talent_points_missing_to_51": 2,
            "source_talent_status": "INCOMPLETE_51",
            "same_class_51_point_donor_builds": 1,
            "source_talent_validation_scope":
                "POINT_TOTAL_ONLY_NOT_RANK_OR_PREREQUISITE_LEGALITY",
        }, source[0][1])
        rows = build_matrix(source, stage=5, run=lambda _: {
            "status": "BLOCKED_SOURCE_LEGALITY",
            "native_paid": 0, "three_axis_paid": 0,
            "blocker": "BLOCKED_TALENTS: missing verified 51-point donors",
        })
        self.assertEqual(49, rows[0]["source_talent_points"])
        self.assertEqual(2, rows[0]["source_talent_points_missing_to_51"])
        self.assertEqual(1, rows[0]["same_class_51_point_donor_builds"])
        gap = next(g for g in gap_summary(rows)
                   if g["cause"] == "SOURCE_TALENT_DONORS_MISSING")
        self.assertEqual(49, gap["rows"][0]["source_talent_points"])
        self.assertEqual(1, gap["rows"][0]["same_class_51_point_donor_builds"])

        with self.assertRaisesRegex(ValueError, "canonical source_talent_points"):
            build_matrix(source, stage=5, run=lambda _: {
                "status": "BLOCKED_SOURCE_LEGALITY",
                "native_paid": 0, "three_axis_paid": 0,
                "source_talent_points": 51,  # forged adapter metadata
            })

    def test_native_process_failures_are_isolated_per_profile(self):
        # A real Rust CLI can time out or fail to launch for one fixture.
        # That row is BLOCKED with no invented score; remaining 28 rows
        # must still be reported and their eligible searches attempted.
        calls = []
        def run(profile):
            calls.append(profile)
            if profile == "druid/feral_cat":
                raise TimeoutError("native scorer exceeded per-request deadline")
            if profile == "mage/spec_0":
                raise subprocess.CalledProcessError(101, ["forever-engine", "--request", profile])
            return {"status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                    "native_paid": 1, "three_axis_paid": 1,
                    "replay_matches": True}
        rows = build_matrix(inventory(), stage=5, run=run)
        by_profile = {r["profile_id"]: r for r in rows}
        self.assertEqual(28, len(rows))
        self.assertEqual(25, len(calls))
        for profile, error in (("druid/feral_cat", "TimeoutError"),
                               ("mage/spec_0", "CalledProcessError")):
            with self.subTest(profile=profile):
                row = by_profile[profile]
                self.assertEqual("BLOCKED_NATIVE_EXECUTION", row["status"])
                self.assertEqual(0, row["native_paid"])
                self.assertEqual(0, row["three_axis_paid"])
                self.assertFalse(row["promotable"])
                self.assertIn(error, row["blocker"])
                self.assertNotIn("best_balanced_screen", row)
        self.assertEqual("SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                         by_profile["mage/spec_1"]["status"])
        self.assertEqual(2, next(g["count"] for g in gap_summary(rows)
                                 if g["cause"] == "REPLAY_FAILED_NATIVE_PROFILE_REQUEST"))

    def test_broken_harness_filesystem_is_not_mislabeled_native_row_blocker(self):
        # A missing executable or failed artifact write is a harness problem,
        # not a spec-specific Rust input rejection.
        with self.assertRaises(OSError):
            build_matrix(inventory(), stage=5,
                         run=lambda _: (_ for _ in ()).throw(
                             OSError("artifact volume unavailable")))

    def test_programming_error_in_runner_is_not_hidden_as_profile_blocker(self):
        # Unexpected harness bugs must still fail CI, not become BLOCKED rows.
        with self.assertRaises(TypeError):
            build_matrix(inventory(), stage=5,
                         run=lambda _: (_ for _ in ()).throw(
                             TypeError("bad runner API")))

    def test_gaps_include_precise_root_cause_and_no_fake_scores(self):
        rows = build_matrix(inventory(), stage=5,
                            run=lambda _: {"status": "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY",
                                           "native_paid": 1, "three_axis_paid": 1,
                                           "replay_matches": True,
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



class SourceTalentInventoryContracts(unittest.TestCase):
    """Mock source requests only: point totals are NOT rank-wise legality."""

    @staticmethod
    def source(profile, talents):
        return ({"profile_id": profile},
                {"raid": {"parties": [{"players": [{"talentsString": talents}]}]}})

    def test_28_source_audit_distinguishes_51_point_donors_from_incomplete(self):
        from native_l60_matrix import annotate_talent_inventory
        rows = [
            self.source("mage/fire", "55555555551-"),    # 51
            self.source("mage/frost", "5555555554-"),     # 49
            self.source("mage/arcane", "55555555533-"),  # 51, distinct donor
            self.source("warlock/affliction", "55555555551-"),
            self.source("warlock/demonology", "not-a-talent"),
            ({"profile_id": "warlock/destruction"}, None),
        ]
        original = [r[1] for r in rows]
        audited = annotate_talent_inventory(rows)
        self.assertEqual(original, [r[1] for r in audited])
        self.assertEqual([r[0]["profile_id"] for r in rows],
                         [r[0]["profile_id"] for r in audited])
        by_id = {r["profile_id"]: r for r, _ in audited}
        self.assertEqual(49, by_id["mage/frost"]["source_talent_points"])
        self.assertEqual(2, by_id["mage/frost"]["source_talent_points_missing_to_51"])
        self.assertEqual("INCOMPLETE_51", by_id["mage/frost"]["source_talent_status"])
        self.assertEqual("POINTS_51_UNVERIFIED_TREE", by_id["mage/fire"]["source_talent_status"])
        self.assertEqual(2, by_id["mage/fire"]["same_class_51_point_donor_builds"])
        self.assertEqual(2, by_id["mage/frost"]["same_class_51_point_donor_builds"])
        self.assertEqual(1, by_id["warlock/affliction"]["same_class_51_point_donor_builds"])
        self.assertEqual("INVALID_ENCODING", by_id["warlock/demonology"]["source_talent_status"])
        self.assertEqual("NO_REQUEST", by_id["warlock/destruction"]["source_talent_status"])
        self.assertIsNone(by_id["warlock/destruction"]["source_talent_points"])
        self.assertTrue(all(r["source_talent_validation_scope"]
                            == "POINT_TOTAL_ONLY_NOT_RANK_OR_PREREQUISITE_LEGALITY"
                            for r, _ in audited))

    def test_source_audit_never_certifies_51_point_tree_or_mutates_source(self):
        from native_l60_matrix import annotate_talent_inventory
        # Even a sum of 51 may violate rank caps/prerequisites. The audit
        # must never call this a fully legal talent allocation.
        rows = [self.source("druid/balance", "999999-")]
        result = annotate_talent_inventory(rows)[0][0]
        self.assertEqual(54, result["source_talent_points"])
        self.assertEqual("OVERALLOCATED_51", result["source_talent_status"])
        self.assertIsNone(result["source_talent_points_missing_to_51"])
        self.assertEqual(0, result["same_class_51_point_donor_builds"])
        self.assertNotIn("full_source_legality_certified", result)


class PinnedTalentAuditEvidenceContracts(unittest.TestCase):
    def test_pinned_28_request_talent_evidence_is_internally_consistent(self):
        # This checks pinned source DATA only, not real Rust scores or
        # prerequisite/rank legality. The native CI run is a separate gate.
        import json
        path = (Path(__file__).resolve().parents[3] / "evidence" /
                "native-l60" / "pinned-source-talent-audit-2026-10-31.json")
        data = json.loads(path.read_text())
        rows = data["rows"]
        self.assertEqual(28, len(rows))
        self.assertEqual(28, len({r["profile_id"] for r in rows}))
        self.assertEqual(9, len({r["profile_id"].split("/")[0] for r in rows}))
        self.assertEqual(26, sum(r["source_talent_points"] == 51 for r in rows))
        self.assertEqual(2, sum(r["source_talent_points"] != 51 for r in rows))
        self.assertEqual("PINNED_SOURCE_TALENT_POINT_AUDIT_NOT_NATIVE_SIMULATION",
                         data["evidence_type"])
        donors = {}
        for r in rows:
            talent = r["source_talent_string"]
            self.assertTrue(set(talent) <= set("0123456789-"))
            self.assertIn(talent.count("-"), (1, 2))
            self.assertEqual(sum(int(c) for c in talent if c != "-"),
                             r["source_talent_points"])
            self.assertEqual(max(0, 51-r["source_talent_points"]),
                             r["points_missing_to_51"])
            self.assertEqual(40, len(r["git_blob_sha1"]))
            if r["source_talent_points"] == 51:
                donors.setdefault(r["profile_id"].split("/")[0], set()).add(talent)
        for r in rows:
            self.assertEqual(
                len(donors.get(r["profile_id"].split("/")[0], ())),
                r["same_class_51_point_donor_builds"])
        self.assertEqual(3, len(donors.get("mage", ())))
        self.assertNotIn("native_paid", data)


    def test_mage_sources_are_pinned_51_point_smoke_requests_not_ranking_refs(self):
        # The original prepared-v2 mage references have only 49/49/46
        # points. Pinned engine mage-census BASE requests are actual distinct
        # 51-point requests, but not independently certified ranking references
        # or validated rank/prerequisite talent trees.
        import json
        from native_l60_matrix import SOURCES
        audit_path = (Path(__file__).resolve().parents[3] / "evidence" /
                      "native-l60" / "pinned-source-talent-audit-2026-10-31.json")
        audit = json.loads(audit_path.read_text())
        rows = {r["profile_id"]: r for r in audit["rows"]}
        expected = {
            "mage/arcane": ("ab408bdb76bb4ec13f8c738bb377c33dcc53a007",
                            "0551205003100301531-230500001-005"),
            "mage/fire": ("4163f0b3d1088f3f0434bbc59be984cacf1f3446",
                          "05012050030000-13550000130135031-004"),
            "mage/frost": ("1a33f4d0341b084d57555e8d03e20edb77cee7ac",
                           "05012050030000-03-0555000301001301251"),
        }
        for profile, (blob, talents) in expected.items():
            spec = profile.split("/")[1]
            path = "validation/2026-10-04-mage-census/bases/" + spec + "-mage.request.json"
            with self.subTest(profile=profile):
                self.assertEqual(("engine", path), SOURCES[profile])
                self.assertEqual(path, rows[profile]["source_path"])
                self.assertEqual(blob, rows[profile]["git_blob_sha1"])
                self.assertEqual(talents, rows[profile]["source_talent_string"])
                self.assertEqual(51, rows[profile]["source_talent_points"])
                self.assertEqual(3, rows[profile]["same_class_51_point_donor_builds"])
                self.assertEqual("POINTS_51_UNVERIFIED_TREE", rows[profile]["point_total_status"])
        self.assertEqual(26, audit["summary"]["point_total_51"])
        self.assertEqual(2, audit["summary"]["incomplete_point_totals"])
        self.assertEqual(3, audit["summary"]["distinct_51_point_donor_builds_by_class"]["mage"])
        self.assertEqual("PINNED_SOURCE_TALENT_POINT_AUDIT_NOT_NATIVE_SIMULATION",
                         audit["evidence_type"])


if __name__ == "__main__":
    unittest.main()
