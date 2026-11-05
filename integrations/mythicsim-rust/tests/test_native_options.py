"""Native get_options transport and optimizer candidate-source contract."""
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "native_options.py"
spec = importlib.util.spec_from_file_location("native_options_tested", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def source():
    return {
        "schema_version": 1, "source_revision": "test-rust-revision",
        "class": "mage", "level": 60,
        "spells": [{"spell_id": 1, "learning_requirement": "unresolved_trainer_talent_or_trigger"}],
        "talents": {"status": "ok", "trees": [{}, {}, {}]},
        "coverage": {"spell_learnability_complete": False,
                     "item_eligibility_complete": True,
                     "talent_prerequisites_complete": True,
                     "native_item_status": "ok"},
        "items": [
            {"item_id": 100, "eligibility": "native_eligible",
             "native": {"item_id": 100, "slot": "head"}, "unverified": None},
            {"item_id": 101, "eligibility": "native_eligible",
             "native": {"item_id": 101, "slot": "head"}, "unverified": None},
            {"item_id": 200, "eligibility": "native_eligible",
             "native": {"item_id": 200, "slot": "finger"}, "unverified": None},
            {"item_id": 300, "eligibility": "proficiency_unverified",
             "native": None, "unverified": {"item_type": "ItemTypeHead"}},
        ],
    }


class NativeOptionsTests(unittest.TestCase):
    def test_queries_only_selected_native_cli(self):
        calls = []
        def runner(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(source()))
        result = module.query_native_options("/tmp/forever-engine", "mage", 60, runner=runner)
        self.assertEqual(result["source_revision"], "test-rust-revision")
        self.assertEqual(calls[0][0], ["/tmp/forever-engine", "options",
                                       "--class", "mage", "--level", "60"])
        self.assertTrue(calls[0][1]["check"] is False)

    def test_eligible_native_slots_only_and_no_empty_slot_guess(self):
        proposals = module.native_equipment_proposals(
            source(), [{"id": 100, "enchant": 17}, {"id": 200},
                       {"id": 0}, {"id": 999}])
        self.assertEqual(proposals, {0: [{"id": 101}]})
        self.assertNotIn({"id": 300}, proposals[0])

    def test_fails_closed_on_fake_native_eligibility(self):
        forged = source()
        forged["items"][3]["native"] = {"item_id": 300, "slot": "head"}
        def runner(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(forged))
        with self.assertRaisesRegex(module.NativeOptionsError, "UNVERIFIED_AS_NATIVE"):
            module.query_native_options("binary", "mage", 60, runner=runner)

    def test_rejects_incomplete_talent_source(self):
        invalid = source()
        invalid["coverage"]["talent_prerequisites_complete"] = False
        def runner(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(invalid))
        with self.assertRaisesRegex(module.NativeOptionsError, "INVALID_COVERAGE"):
            module.query_native_options("binary", "mage", 60, runner=runner)


if __name__ == "__main__":
    unittest.main()
