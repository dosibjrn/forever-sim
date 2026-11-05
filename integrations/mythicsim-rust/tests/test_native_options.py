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

    def test_unverified_source_items_reach_all_structural_slots(self):
        proposals = module.native_equipment_proposals(
            source(), [{"id": 100, "enchant": 17}, {"id": 200},
                       {"id": 0}, {"id": 999}])
        self.assertEqual(proposals, {
            0: [{"id": 101}, {"id": 300}],
            1: [{"id": 300}],
            2: [{"id": 300}],  # even an empty position is Rust's decision
            3: [{"id": 300}],  # no guessed slot or class rules in Python
        })

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
        self.assertEqual(adapter.native_option_candidate_count, 2)
        self.assertEqual(adapter.native_option_unverified_count, 1)
        self.assertEqual(adapter.mutable_indices, (0,))
        self.assertIn({"id": 101}, adapter.variants[0])
        self.assertIn({"id": 300}, adapter.variants[0])
        import random
        candidate, audit = adapter.mutate_one(random.Random(1))
        self.assertIn(candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0],
                      [{"id": 101}, {"id": 300}])
        self.assertIn(audit["to_id"], [101, 300])

    def test_paid_gear_sweep_entrypoint_reuses_real_native_source(self):
        from native_gear_search import native_source_adapter
        from unittest.mock import patch
        ref = {
            "raid": {"parties": [{"players": [{
                "class": "ClassMage", "equipment": {"items": [{"id": 100}]},
                "talentsString": "51",
                "rotation": {"priorityList": [{"action": {"wait": {}}}]},
            }]}]},
            "simOptions": {"iterations": 3, "randomSeed": "47"},
        }
        cache = {}
        binary = Path("/selected/rust/forever-engine")
        with patch("native_gear_search.query_native_options", return_value=source()) as cli:
            first = native_source_adapter("mage", binary, ref, [ref], {}, cache)
            second = native_source_adapter("mage", binary, ref, [ref], {}, cache)
        cli.assert_called_once_with(binary, "mage", 60)
        self.assertEqual(first.native_option_candidate_count, 2)
        self.assertEqual(first.native_option_unverified_count, 1)
        self.assertEqual(second.mutable_indices, (0,))
        self.assertEqual(second.variants[0], [{"id": 100}, {"id": 101}, {"id": 300}])

    def test_unverified_only_class_is_sent_to_native_evaluator(self):
        # No Python equipment proficiency/slot rules, even without native slots.
        from native_gear_search import cold_gear_kernel
        from native_matrix import NativeCandidateRefusal
        import copy
        from unittest.mock import patch
        ref = {
            "raid": {"parties": [{"players": [{
                "class": "ClassWarrior",
                "equipment": {"items": [{"id": 0}, {"id": 200}]},
                "talentsString": "51",
                "rotation": {"priorityList": [{"action": {"wait": {}}}]},
            }]}]},
            "simOptions": {"iterations": 3, "randomSeed": "47"},
        }
        uncertain = copy.deepcopy(source())
        uncertain["class"] = "warrior"
        uncertain["items"] = [uncertain["items"][3]]
        uncertain["coverage"]["item_eligibility_complete"] = False
        uncertain["coverage"]["native_item_status"] = "proficiency_unverified"
        adapter = NativeGearAdapter("warrior", ref, [ref], native_options=uncertain)
        self.assertEqual(adapter.native_option_unverified_count, 2)
        self.assertEqual(adapter.mutable_indices, (0, 1))
        attempted = []
        def rust_refuses(candidate, *, iterations, seed, rng_mode):
            attempted.append(candidate)
            raise NativeCandidateRefusal("INVALID", reason="native Rust equip refusal")
        result, trace = cold_gear_kernel(
            adapter, ref, evaluate=rust_refuses, seconds=0.02,
            iterations=2, seed=47,
        )
        self.assertTrue(attempted, "Unverified must reach paid Rust call boundary")
        self.assertTrue(all(any(item["id"] == 300 for item in
            req["raid"]["parties"][0]["players"][0]["equipment"]["items"])
            for req in attempted))
        self.assertEqual(result["paid_candidates"], 0)
        self.assertGreater(result["native_refusals"], 0)
        self.assertEqual(result["engine_errors"], 0)
        self.assertEqual(trace, [])

    def test_paid_gear_sweep_entrypoint_fails_closed_without_native_source(self):
        from native_gear_search import native_source_adapter
        from unittest.mock import patch
        with patch("native_gear_search.query_native_options",
                   side_effect=module.NativeOptionsError("NATIVE_OPTIONS_INVALID_COVERAGE")):
            with self.assertRaisesRegex(module.NativeOptionsError, "INVALID_COVERAGE"):
                native_source_adapter("mage", Path("/binary"), {}, [], {}, {})

    def test_rejects_incomplete_talent_source(self):
        invalid = source()
        invalid["coverage"]["talent_prerequisites_complete"] = False
        def runner(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(invalid))
        with self.assertRaisesRegex(module.NativeOptionsError, "INVALID_COVERAGE"):
            module.query_native_options("binary", "mage", 60, runner=runner)


if __name__ == "__main__":
    unittest.main()
