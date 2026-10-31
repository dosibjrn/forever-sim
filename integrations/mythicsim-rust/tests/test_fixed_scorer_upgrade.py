"""RED TDD: fixed native scorer must earn gear evidence on frozen requests."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rng_extreme_probability_fix import verify_fixed_scorer_gear_upgrade, digest


class FixedScorerUpgradeContract(unittest.TestCase):
    def fixture(self, root):
        original, fixed = root / "original", root / "fixed"
        original.mkdir()
        fixed.mkdir()
        binary = root / "fixed-engine"
        binary.write_bytes(b"real-binary-placeholder-for-unit-test")
        original_rows, fixed_rows = [], []
        for profile in ("druid/feral_cat", "rogue/assassination"):
            rel = "profiles/" + profile.replace("/", "__") + "/gear_attempt_000.request.json"
            for folder in (original, fixed):
                path = folder / rel
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"profile": profile, "gear": [1, 2]}))
            old_row = {
                "profile_id": profile, "native_paid": 0,
                "native_failures": [{
                    "category": "RUST_BALANCED_RNG_PROBABILITY",
                    "request_path": rel, "request_sha256": digest(original / rel),
                }],
            }
            new_row = {
                "profile_id": profile, "native_paid": 1,
                "status": "NATIVE_GEAR_PROBE_PAID_PARTIAL_LEGALITY",
                "native_score": 450.0, "request_path": rel,
                "request_sha256": digest(fixed / rel),
            }
            original_rows.append(old_row)
            fixed_rows.append(new_row)
        for n in range(26):
            profile = "other/spec_" + str(n)
            original_rows.append({"profile_id": profile, "native_paid": 0})
            fixed_rows.append({"profile_id": profile, "native_paid": 0})
        (original / "gear_probe.json").write_text(json.dumps({
            "engine_binary_sha256": "old-sha", "rows": original_rows,
        }))
        (fixed / "gear_probe.json").write_text(json.dumps({
            "engine_binary_sha256": digest(binary), "rows": fixed_rows,
        }))
        return original, fixed, binary

    def test_exact_frozen_native_requests_upgrade_two_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, fixed, binary = self.fixture(Path(tmp))
            result = verify_fixed_scorer_gear_upgrade(old, fixed, binary)
            self.assertEqual(2, len(result["upgraded_profiles"]))
            self.assertEqual(digest(binary), result["fixed_binary_sha256"])
            self.assertIn("NOT_JOINT", result["scope"])
            self.assertTrue((fixed / "fixed_scorer_gear_upgrade.json").is_file())

    def test_rejects_changed_request_or_unpaid_or_unpinned_scorer(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, fixed, binary = self.fixture(Path(tmp))
            rows = json.loads((fixed / "gear_probe.json").read_text())
            rows["rows"][0]["native_paid"] = 0
            (fixed / "gear_probe.json").write_text(json.dumps(rows))
            with self.assertRaises(AssertionError):
                verify_fixed_scorer_gear_upgrade(old, fixed, binary)
            rows["rows"][0]["native_paid"] = 1
            rows["rows"][0]["request_sha256"] = "different-request"
            (fixed / "gear_probe.json").write_text(json.dumps(rows))
            with self.assertRaises(AssertionError):
                verify_fixed_scorer_gear_upgrade(old, fixed, binary)
            rows["rows"][0]["request_sha256"] = digest(fixed / rows["rows"][0]["request_path"])
            rows["engine_binary_sha256"] = "unverified-binary"
            (fixed / "gear_probe.json").write_text(json.dumps(rows))
            with self.assertRaises(AssertionError):
                verify_fixed_scorer_gear_upgrade(old, fixed, binary)


if __name__ == "__main__":
    unittest.main()
