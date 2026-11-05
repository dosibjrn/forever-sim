"""Native get_options transport and optimizer candidate-source contract."""
import importlib.util
import json
import subprocess
import unittest
import sys
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "native_options.py"
spec = importlib.util.spec_from_file_location("native_options_tested", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.path.insert(0, str(MODULE.parent))
from native_gear_adapter import NativeGearAdapter


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

    def test_native_candidates_enter_real_joint_gear_adapter(self):
        ref = {
            "raid": {"parties": [{"players": [{
                "class": "ClassMage", "equipment": {"items": [{"id": 100}]},
                "talentsString": "51",
                "rotation": {"priorityList": [{"action": {"wait": {}}}]},
            }]}]},
            "simOptions": {"iterations": 3, "randomSeed": "47"},
        }
        adapter = NativeGearAdapter("mage", ref, [ref], native_options=source())
        self.assertEqual(adapter.native_option_candidate_count, 1)
        self.assertEqual(adapter.mutable_indices, (0,))
        self.assertIn({"id": 101}, adapter.variants[0])
        self.assertNotIn({"id": 300}, adapter.variants[0])
        import random
        candidate, audit = adapter.mutate_one(random.Random(1))
        self.assertEqual(candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0], {"id": 101})
        self.assertEqual(audit["to_id"], 101)

    def test_rejects_incomplete_talent_source(self):
        invalid = source()
        invalid["coverage"]["talent_prerequisites_complete"] = False
        def runner(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(invalid))
        with self.assertRaisesRegex(module.NativeOptionsError, "INVALID_COVERAGE"):
            module.query_native_options("binary", "mage", 60, runner=runner)


    def test_native_talent_and_spell_moves_are_unverified_request_proposals(self):
        native = source()
        native["talents"]["trees"] = [
            {"talents": [{"max_rank": 5, "row": 0}, {"max_rank": 5, "row": 0}]},
            {"talents": [{"max_rank": 5, "row": 0}]},
            {"talents": []},
        ]
        native["spells"] = [
            {"spell_id": 1, "learning_requirement": "unresolved_trainer_talent_or_trigger"},
            {"spell_id": 200, "learning_requirement": "unresolved_trainer_talent_or_trigger"},
        ]
        reference = {
            "raid": {"parties": [{"players": [{
                "class": "ClassMage", "talentsString": "3-2-",
                "rotation": {"priorityList": [
                    {"action": {"castSpell": {"spellId": {"spellId": 1}}}}
                ]},
            }]}]},
            "simOptions": {"iterations": 40, "randomSeed": "7"},
        }
        requests, counts = module.native_joint_request_proposals(native, reference)
        self.assertEqual(counts, {
            "native_options_talent_proposals": 1,
            "native_options_unverified_spell_apl_proposals": 1,
        })
        self.assertEqual(requests[0]["raid"]["parties"][0]["players"][0]["talentsString"], "21-2-")
        self.assertEqual(requests[1]["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"][-1],
                         {"action": {"castSpell": {"spellId": {"spellId": 200}}}})
        self.assertEqual(requests[1]["raid"]["parties"][0]["players"][0]["talentsString"], "3-2-")
        self.assertEqual(requests[0]["simOptions"], reference["simOptions"])
        self.assertEqual(reference["raid"]["parties"][0]["players"][0]["talentsString"], "3-2-")
        self.assertEqual(len(reference["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]), 1)

    def test_unverified_coverage_does_not_invent_spell_legality(self):
        native = source()
        native["class"] = "warlock"
        native["level"] = 20
        native["coverage"]["item_eligibility_complete"] = False
        native["talents"]["trees"] = [{"talents": []}] * 3
        native["spells"] = [{"spell_id": 999,
                             "learning_requirement": "unresolved_trainer_talent_or_trigger"}]
        reference = {
            "raid": {"parties": [{"players": [{
                "class": "ClassWarlock", "talentsString": "--",
                "rotation": {"priorityList": [{"action": {"wait": {}}}]},
            }]}]},
        }
        requests, counts = module.native_joint_request_proposals(native, reference)
        self.assertEqual(counts["native_options_talent_proposals"], 0)
        self.assertEqual(counts["native_options_unverified_spell_apl_proposals"], 1)
        self.assertEqual(requests[0]["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"][-1]
                         ["action"]["castSpell"]["spellId"]["spellId"], 999)
        # Discovery does not create a VALID verdict or alter the native source.
        self.assertNotIn("status", requests[0])
        self.assertFalse(native["coverage"]["item_eligibility_complete"])



if __name__ == "__main__":
    unittest.main()
