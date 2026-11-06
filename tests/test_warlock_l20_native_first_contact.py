"""Contract regression for the real Rust Warlock L20 first-contact reader."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


PATH = Path(__file__).resolve().parents[1] / "tools" / "warlock_l20_native_first_contact.py"
spec = importlib.util.spec_from_file_location("warlock_l20_native_first_contact", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def source_options(*, ready=False):
    return {
        "schema_version": 1, "source_revision": "pinned-rust-source",
        "class": "warlock", "level": 20,
        "coverage": {
            "item_eligibility_complete": ready,
            "spell_learnability_complete": ready,
            "talent_prerequisites_complete": True,
            "native_item_status": "ok" if ready else "proficiency_unverified",
        },
        "spells": [{"spell_id": 172, "minimum_level": 1}],
        "items": [] if ready else [
            {"item_id": 123, "eligibility": "proficiency_unverified"},
        ],
        "talents": {
            "status": "ok", "points_available": 11,
            "trees": [{"name": "Affliction"}, {"name": "Demonology"}, {"name": "Destruction"}],
        },
    }


def native_items(*, ready=False):
    return {
        "class": "warlock", "level": 20,
        "spec": "unrestricted", "slot": "all",
        "status": "ok" if ready else "refused",
        "required_level_supported": ready,
        "items": [{"item_id": 123}] if ready else [],
        "refusal": None if ready else {
            "code": "NATIVE_ITEM_OPTIONS_UNSUPPORTED_CLASS",
            "reason": "Warlock proficiency not verified",
        },
    }


def runner_for(options, items):
    def runner(argv, **_kwargs):
        payload = options if argv[1] == "options" else items
        return SimpleNamespace(
            returncode=0, stdout=json.dumps(payload), stderr="",
        )
    return runner


class WarlockL20NativeProbeTest(unittest.TestCase):
    def test_real_current_source_gap_is_diagnosed_not_promoted_to_pass(self):
        result = module.diagnose_warlock_l20(
            "rust", runner=runner_for(source_options(), native_items())
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["gate_acceptance"], "NOT_RUN")
        self.assertEqual(result["native_l20_combat"], "NOT_EXECUTED")
        self.assertFalse(result["item_source_ready"])
        self.assertEqual(
            result["native_gear_refusal"]["code"],
            "NATIVE_ITEM_OPTIONS_UNSUPPORTED_CLASS",
        )
        self.assertIn("WARLOCK_L20_NATIVE_ITEM_PROFICIENCY", result["missing"])
        self.assertEqual(result["talent_points"], 11)

    def test_even_complete_native_options_are_not_combat_or_p3_pass(self):
        result = module.diagnose_warlock_l20(
            "rust", runner=runner_for(
                source_options(ready=True), native_items(ready=True))
        )
        self.assertTrue(result["all_source_dimensions_ready"])
        self.assertTrue(result["item_source_ready"])
        self.assertEqual(result["gate_acceptance"], "NOT_RUN")
        self.assertEqual(result["native_l20_combat"], "NOT_EXECUTED")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(
            result["missing"],
            ["WARLOCK_L20_NATIVE_PREPARED_ACTOR_AND_PAID_COMBAT"],
        )

    def test_wrong_level_and_clipped_talent_points_fail_closed(self):
        options = source_options()
        options["level"] = 60
        with self.assertRaisesRegex(module.NativeWarlockProbeError, "WRONG_CLASS_OR_LEVEL"):
            module.diagnose_warlock_l20(
                "rust", runner=runner_for(options, native_items()))
        options["level"] = 20
        options["talents"]["points_available"] = 51
        with self.assertRaisesRegex(module.NativeWarlockProbeError, "L20_TALENTS_INVALID"):
            module.diagnose_warlock_l20(
                "rust", runner=runner_for(options, native_items()))

    def test_item_refusal_without_specific_code_fails_closed(self):
        items = native_items()
        items["refusal"] = {"reason": "missing"}
        with self.assertRaisesRegex(module.NativeWarlockProbeError, "REFUSAL_MALFORMED"):
            module.diagnose_warlock_l20(
                "rust", runner=runner_for(source_options(), items))

    def test_native_response_level_mismatch_fails_closed(self):
        items = native_items()
        items["level"] = 60
        with self.assertRaisesRegex(module.NativeWarlockProbeError, "WRONG_REQUEST"):
            module.diagnose_warlock_l20(
                "rust", runner=runner_for(source_options(), items))


if __name__ == "__main__":
    unittest.main()
