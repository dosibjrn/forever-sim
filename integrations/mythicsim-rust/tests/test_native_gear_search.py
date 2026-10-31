"""Fake-only cold gear kernel tests; never publish mock scores as Rust evidence."""
import copy
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from native_gear_adapter import NativeGearAdapter
from native_gear_search import cold_gear_kernel, sweep


def request(cls, ids):
    return {"simOptions": {"randomSeed": "2710", "iterations": 10},
            "raid": {"parties": [{"players": [{
                "class": "Class" + cls,
                "equipment": {"items": [{"id": i} for i in ids]},
                "talentsString": "frozen-talents",
                "rotation": {"priorityList": [{"action": {"wait": {}}}]},
            }]}]}}


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        self.now += 0.001
        return self.now


class NativeGearColdContracts(unittest.TestCase):
    def setUp(self):
        self.items = {
            10: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
            11: {"type": "ItemTypeHead", "armor_type": "ArmorTypeCloth"},
            20: {"type": "ItemTypeChest", "armor_type": "ArmorTypeCloth"},
            21: {"type": "ItemTypeChest", "armor_type": "ArmorTypeCloth"},
            30: {"type": "ItemTypeWeapon", "hand_type": "HandTypeTwoHand"},
        }
        self.base = request("Mage", [10, 20, 30])
        self.donor = request("Mage", [11, 21, 30])

    def test_cold_search_pays_only_native_callback_and_freezes_non_gear(self):
        original = copy.deepcopy(self.base)
        adapter = NativeGearAdapter("mage", self.base,
                                    [self.base, self.donor], self.items)
        observed = []

        def mock_only(candidate, *, iterations, seed, rng_mode):
            adapter.validate(candidate)
            self.assertEqual("balanced", rng_mode)
            self.assertEqual(2, iterations)
            self.assertEqual(55, seed)
            self.assertNotEqual(original, candidate)
            observed.append(copy.deepcopy(candidate))
            return 100.0 + len(observed), "mock-only-payload"

        result, trace = cold_gear_kernel(
            adapter, self.base, evaluate=mock_only, seconds=0.04,
            iterations=2, seed=55, clock=FakeClock())
        self.assertEqual("RAN", result["status"])
        self.assertEqual(len(observed), result["paid_candidates"])
        self.assertEqual(len(trace), result["paid_candidates"])
        self.assertTrue(all(t["native_payload_sha256"] == "mock-only-payload"
                            for t in trace))
        adapter.validate(result["best_candidate"])
        self.assertEqual(original, self.base)

    def test_no_legal_source_alternative_never_invokes_evaluator(self):
        adapter = NativeGearAdapter("mage", self.base, [self.base], self.items)
        def fail(*args, **kwargs):
            self.fail("No fake or native evaluator call without a legal gear pool")
        result, trace = cold_gear_kernel(
            adapter, self.base, evaluate=fail, seconds=0.01,
            iterations=1, seed=55, clock=FakeClock())
        self.assertEqual("BLOCKED_NO_LEGAL_CANDIDATE", result["status"])
        self.assertEqual(0, result["paid_candidates"])
        self.assertEqual([], trace)

    def test_nonfinite_metric_is_not_paid(self):
        adapter = NativeGearAdapter("mage", self.base,
                                    [self.base, self.donor], self.items)
        result, trace = cold_gear_kernel(
            adapter, self.base,
            evaluate=lambda *args, **kwargs: (float("nan"), "mock"),
            seconds=0.01, iterations=1, seed=55, clock=FakeClock())
        self.assertEqual("BLOCKED_ENGINE_ERROR", result["status"])
        self.assertEqual(0, result["paid_candidates"])
        self.assertEqual([], trace)

    def test_real_sweep_requires_native_binary(self):
        with self.assertRaisesRegex(ValueError, "real native Rust binary"):
            sweep(engine_src=Path("/missing-rust-source"),
                  binary=Path("/missing-rust-binary"),
                  outdir=Path("/unused"), seconds=5, iterations=10, seed=55)


    def test_native_failure_keeps_exact_candidate_and_category_without_paid_score(self):
        adapter = NativeGearAdapter("mage", self.base,
                                    [self.base, self.donor], self.items)
        source = copy.deepcopy(self.base)

        def failing_native(candidate, *, iterations, seed, rng_mode):
            adapter.validate(candidate)
            raise RuntimeError("native Rust failed: unsupported request")

        result, trace = cold_gear_kernel(
            adapter, self.base, evaluate=failing_native, seconds=0.04,
            iterations=2, seed=55, clock=FakeClock())
        self.assertEqual(0, result["paid_candidates"])
        self.assertEqual([], trace)
        self.assertGreaterEqual(result["engine_errors"], 1)
        self.assertGreaterEqual(len(result["native_failures"]), 1)
        self.assertLessEqual(len(result["native_failures"]), 3)
        failure = result["native_failures"][0]
        self.assertEqual("RUST_NATIVE_EXECUTION", failure["category"])
        self.assertEqual("balanced", failure["rng_mode"])
        self.assertEqual(55, failure["seed"])
        self.assertIn("candidate", failure)
        # This is the exact effective Rust payload, including evaluator
        # overrides, rather than the unmodified optimizer proposal.
        self.assertEqual(2, failure["candidate"]["simOptions"]["iterations"])
        self.assertEqual("55", failure["candidate"]["simOptions"]["randomSeed"])
        from native_l60_matrix import fingerprint
        self.assertEqual(fingerprint(failure["candidate"]), failure["candidate_sha256"])
        gear_candidate = copy.deepcopy(failure["candidate"])
        gear_candidate["simOptions"] = copy.deepcopy(source["simOptions"])
        adapter.validate(gear_candidate)
        self.assertNotEqual(source, gear_candidate)
        self.assertNotIn("score", failure)
        self.assertEqual(source, self.base)

    def test_native_deadline_does_not_create_false_engine_failure_evidence(self):
        adapter = NativeGearAdapter("mage", self.base,
                                    [self.base, self.donor], self.items)

        def deadline_native(candidate, *, iterations, seed, rng_mode):
            raise TimeoutError("strict native budget expired")

        result, trace = cold_gear_kernel(
            adapter, self.base, evaluate=deadline_native, seconds=0.04,
            iterations=2, seed=55, clock=FakeClock())
        self.assertEqual(0, result["paid_candidates"])
        self.assertEqual(0, result["engine_errors"])
        self.assertEqual([], result["native_failures"])
        self.assertEqual([], trace)


    def test_best_paid_native_request_records_exact_effective_payload(self):
        """The paid winner must be replayable with the Rust seed/iterations."""
        from native_l60_matrix import fingerprint
        adapter = NativeGearAdapter("mage", self.base,
                                    [self.base, self.donor], self.items)

        def fake_only(candidate, *, iterations, seed, rng_mode):
            effective = copy.deepcopy(candidate)
            effective["simOptions"]["iterations"] = iterations
            effective["simOptions"]["randomSeed"] = str(seed)
            # Fake scores are used only by this contract, never in CI artifacts.
            score = float(sum(x["id"] for x in
                              effective["raid"]["parties"][0]["players"][0]
                              ["equipment"]["items"]))
            return score, fingerprint(effective)

        result, trace = cold_gear_kernel(
            adapter, self.base, evaluate=fake_only, seconds=0.04,
            iterations=2, seed=55, clock=FakeClock())
        self.assertGreater(result["paid_candidates"], 0)
        best = result["best_native_request"]
        self.assertEqual(2, best["simOptions"]["iterations"])
        self.assertEqual("55", best["simOptions"]["randomSeed"])
        self.assertEqual(fingerprint(best), result["best_native_payload_sha256"])
        winner = max(trace, key=lambda t: t["score"])
        self.assertEqual(winner["native_payload_sha256"],
                         result["best_native_payload_sha256"])
        self.assertEqual(winner["score"], result["best_score"])
        # The scored effective request differs from the frozen source options.
        self.assertEqual("2710", self.base["simOptions"]["randomSeed"])


if __name__ == "__main__":
    unittest.main()
