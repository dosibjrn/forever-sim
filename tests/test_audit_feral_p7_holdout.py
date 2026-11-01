"""Unit regressions for the original WF613 archived holdout audit."""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from audit_feral_p7_holdout import audit_payload, audit_lineage


class FeralHoldoutAuditTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "workflow": "WF613", "gate": "P7.5", "mode": "stochastic",
            "status": "FAIL", "observed_n": 1000, "target_n": 1000,
            "precommitted_seed_range": [92000001, 92001000],
            "prior_p74_dps": 853.9305465836047,
            "runs": [{"seed": seed, "dps": 848.7643621918036}
                     for seed in range(92000001, 92001001)],
            "mean_dps": 848.7643621918036, "std_dps": 0.0,
        }

    def test_recomputed_mean_uses_99pct_not_old_ci_bound(self):
        result = audit_payload(self.payload)
        self.assertTrue(result["process_v2_10_numeric_pass_if_prior_accepted_compatible"])
        self.assertFalse(result["full_process_gate_certified"])
        self.assertEqual(result["historical_original_verdict"], "FAIL")
        self.assertAlmostEqual(result["provisional_numeric_floor_dps"], 845.3912411177687)

    def test_missing_seed_is_rejected(self):
        p = copy.deepcopy(self.payload)
        p["runs"][42]["seed"] = p["runs"][41]["seed"]
        with self.assertRaisesRegex(ValueError, "seeds"):
            audit_payload(p)

    def test_modified_mean_is_rejected(self):
        p = copy.deepcopy(self.payload)
        p["runs"][0]["dps"] += 100
        with self.assertRaisesRegex(ValueError, "mean"):
            audit_payload(p)

    def test_legacy_status_is_not_rewritten(self):
        p = copy.deepcopy(self.payload)
        p["status"] = "PASS"
        with self.assertRaisesRegex(ValueError, "original verdict"):
            audit_payload(p)

    def test_non_stochastic_and_wrong_prior_rejected(self):
        for field, value in [("mode", "balanced"), ("prior_p74_dps", 845.52)]:
            p = copy.deepcopy(self.payload)
            p[field] = value
            with self.assertRaises(ValueError):
                audit_payload(p)


    def _lineage_fixture(self):
        config = {"gear_ids": [123, 456], "talents": "abc", "policy_spec": {"order": ["cat"]}}
        digest = lambda b: hashlib.sha256(b).hexdigest()
        cfg_hash = digest(json.dumps(config, sort_keys=True, separators=(",", ":")).encode())
        generator = b"# original search source\\n"
        search = {"winner": {"config": config, "config_hash": cfg_hash},
                  "generator_sha256": digest(generator), "binary_sha256": "binary",
                  "reference_sha256": "reference", "db_sha256": "db"}
        precommit = {"independent_from_search": True, "first_seed": 92000001,
                     "last_seed": 92001000, "count": 1000, "comparison_gate": "P7.4",
                     "prior_best_mean_dps": 853.9305465836047}
        search_raw = json.dumps(search).encode()
        precommit_raw = json.dumps(precommit).encode()
        holdout = {"frozen_config": config, "frozen_config_hash": cfg_hash,
                   "search_sha256": digest(search_raw),
                   "precommit_sha256": digest(precommit_raw),
                   "binary_sha256": "binary", "reference_sha256": "reference",
                   "database_sha256": "db", "prior_p74_dps": 853.9305465836047}
        trace = {"candidate_config_hash": cfg_hash, "binary_sha256": "binary",
                 "reference_sha256": "reference", "acks": 2,
                 "world_ack_trace": [{"sequence": 0}, {"sequence": 1}]}
        return [holdout, search, trace, precommit, search_raw, precommit_raw, generator]

    def test_original_archive_lineage_identity_contract(self):
        fixture = self._lineage_fixture()
        result = audit_lineage(*fixture)
        self.assertEqual(result["archive_lineage_checks"], "PASS")
        self.assertEqual(result["causal_trace_acks"], 2)

    def test_reject_archive_search_precommit_source_and_trace_mismatch(self):
        for index, key, value in [
            (0, "search_sha256", "not the original search"),
            (0, "precommit_sha256", "not the original precommit"),
            (0, "frozen_config_hash", "not the frozen config"),
            (1, "generator_sha256", "not the source"),
            (1, "db_sha256", "different database"),
            (1, "winner", {"config_hash": "different", "config": {}}),
            (2, "candidate_config_hash", "different candidate"),
            (2, "acks", 3),
            (3, "prior_best_mean_dps", 845.5219526091071),
            (3, "independent_from_search", False),
        ]:
            with self.subTest(index=index, key=key):
                fixture = self._lineage_fixture()
                fixture[index][key] = value
                with self.assertRaisesRegex(ValueError, "lineage mismatch"):
                    audit_lineage(*fixture)

if __name__ == "__main__":
    unittest.main()
