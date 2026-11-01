"""Integrity regressions for verbatim WF613 raw evidence recovered from ZIP.

SHA256 digests are of original ZIP members, not rewritten representations.
These tests do NOT independently accept the saved P7.4 prior DPS.
"""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "docs/evidence/druid-p7/recovered/raw/WF612"
SHA256 = {
    "wf613_repair.py": "06f0820ccfb4d9cebb9cbdf3c700293a1057677af2ad8ef6d59d3ea0605094d6",
    "test_wf613_repair.py": "d5ca9e1298efa3e45943c0ed2e372017f7f5748c850cf36c33ec3b705eb49479",
    "WF612_P75_HOLDOUT_PRECOMMIT.json": "d5498b97cf095636f8c1ae01a8770f548c3fb8e5d3c0401483c4845f5c771966",
    "WF613_P75_HOLDOUT.log": "c67713b1ba83557d9352123fd0efffab9b2fb00e6e435b9d0bbce662f77f5f15",
}

class RecoveredRawIntegrity(unittest.TestCase):
    def test_original_member_bytes(self):
        for filename, digest in SHA256.items():
            with self.subTest(filename=filename):
                self.assertEqual(hashlib.sha256((RAW / filename).read_bytes()).hexdigest(), digest)

    def test_original_holdout_log_retains_historical_fail(self):
        log = (RAW / "WF613_P75_HOLDOUT.log").read_text()
        self.assertIn("P75_HOLDOUT 1000", log)
        self.assertIn('"status": "FAIL"', log)
        self.assertIn('"observed_n": 1000', log)
        self.assertIn('"mean_dps": 848.7643621918036', log)
        self.assertIn('"prior_p74_dps": 853.9305465836047', log)
        # The original one-sided CI rule is historical provenance, not
        # the current approved PROCESS v2.10 arithmetic-mean gate.
        self.assertIn("noninferiority_margin_0_DPS_independent_1000_vs_1000_one_sided_95_CI", log)

    def test_frozen_precommit_not_acceptance_certificate(self):
        pre = json.loads((RAW / "WF612_P75_HOLDOUT_PRECOMMIT.json").read_text())
        self.assertEqual(pre["gate"], "P7.5")
        self.assertEqual(pre["mode"], "stochastic")
        self.assertEqual((pre["first_seed"], pre["last_seed"], pre["count"]),
                         (92000001, 92001000, 1000))
        self.assertEqual(pre["prior_best_mean_dps"], 853.9305465836047)
        self.assertTrue(pre["independent_from_search"])
        self.assertEqual(pre["comparison_gate"], "P7.4")
        # Precommitting a number cannot independently prove that prior was accepted.
        self.assertNotIn("prior_accepted_evidence_sha256", pre)

if __name__ == "__main__":
    unittest.main()
