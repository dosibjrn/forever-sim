"""Mock-fixture admission tests; NO fake scores may enter native reports."""
import copy
import random
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from native_gear_adapter import NativeGearAdapter, GearRejected


def req(cls, ids):
    return {"raid": {"parties": [{"players": [{"class": "Class" + cls,
        "equipment": {"items": [{"id": x} for x in ids]},
        "talentsString": "51", "rotation": {"priorityList": [{"action": {"wait": {}}}]}}]}]}}


class NativeGearAdapterTests(unittest.TestCase):
    def setUp(self):
        self.items = {
            10: {"type": "ItemTypeHead"}, 11: {"type": "ItemTypeHead", "class_allowlist": ["ClassMage"]},
            12: {"type": "ItemTypeHead", "class_allowlist": ["ClassWarrior"]},
            20: {"type": "ItemTypeChest"}, 21: {"type": "ItemTypeChest"},
            22: {"type": "ItemTypeChest"},
            30: {"type": "ItemTypeWeapon", "hand_type": "HandTypeTwoHand"},
            31: {"type": "ItemTypeWeapon", "hand_type": "HandTypeOneHand"},
            32: {"type": "ItemTypeWeapon"},
        }
        self.fire = req("Mage", [10, 20, 30])
        self.frost = req("Mage", [11, 21, 31])
        self.warrior = req("Warrior", [12, 22, 32])

    def test_same_class_and_position_only(self):
        adapter = NativeGearAdapter("mage", self.fire,
            [self.fire, self.frost, self.warrior], self.items)
        self.assertEqual((0, 1), adapter.mutable_indices)
        self.assertEqual({10, 11}, set(adapter.pools[0]))
        self.assertEqual({20, 21}, set(adapter.pools[1]))
        self.assertNotIn(2, adapter.pools)  # no weapon/offhand guesswork

    def test_native_mutation_preserves_reference_talents_apl_and_weapon(self):
        original = copy.deepcopy(self.fire)
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], self.items)
        candidate, audit = adapter.mutate_one(random.Random(10))
        self.assertEqual(original, self.fire)
        self.assertEqual(original["raid"]["parties"][0]["players"][0]["equipment"]["items"][2],
                         candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][2])
        self.assertIn(audit["source_slot_index"], (0, 1))
        adapter.validate(candidate)

    def test_class_allowlist_filters_cross_class_source(self):
        items = copy.deepcopy(self.items)
        items[11]["class_allowlist"] = ["ClassWarrior"]
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], items)
        self.assertNotIn(11, adapter.pools.get(0, {}))

    def test_no_alternatives_blocks_explicitly(self):
        adapter = NativeGearAdapter("mage", self.fire, [self.fire], self.items)
        with self.assertRaisesRegex(GearRejected, "NO_SOURCE_BOUNDED_ALTERNATIVE"):
            adapter.mutate_one(random.Random(1))

    def test_unique_limit_category_rejected(self):
        items = copy.deepcopy(self.items)
        items[11]["limit_category"] = 55
        items[20]["limit_category"] = 55
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], items)
        candidate = copy.deepcopy(self.fire)
        candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {"id": 11}
        with self.assertRaisesRegex(GearRejected, "UNIQUE_CATEGORY"):
            adapter.validate(candidate)

    def test_unverified_position_and_talent_change_rejected(self):
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], self.items)
        candidate = copy.deepcopy(self.fire)
        p = candidate["raid"]["parties"][0]["players"][0]
        p["equipment"]["items"][0] = {"id": 21}
        with self.assertRaisesRegex(GearRejected, "SOURCE_SLOT"):
            adapter.validate(candidate)
        p["equipment"]["items"][0] = {"id": 10}
        p["talentsString"] = "other"
        with self.assertRaisesRegex(GearRejected, "TALENTS_CHANGED"):
            adapter.validate(candidate)

    def test_variable_gear_length_and_different_class(self):
        warrior = req("Warrior", [12, 22, 32, 20, 10])
        warrior2 = req("Warrior", [12, 21, 32, 20, 10])
        adapter = NativeGearAdapter("warrior", warrior, [warrior, warrior2, self.fire], self.items)
        self.assertEqual((1,), adapter.mutable_indices)
        candidate, _ = adapter.mutate_one(random.Random(2))
        adapter.validate(candidate)
        self.assertEqual(5, len(candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"]))

    def test_nonunique_repeated_native_item_is_not_blanket_rejected(self):
        # Two non-unique rings/trinkets can legitimately share an item ID.
        # The native 'unique' and 'limit_category' fields, not blanket ID
        # deduplication, control this constraint.
        source = req("Mage", [10, 20, 30, 40, 40])
        items = {**self.items, 40: {"type": "ItemTypeFinger", "unique": False}}
        adapter = NativeGearAdapter("mage", source, [source], items)
        adapter.validate(copy.deepcopy(source))
        items[40]["unique"] = True
        unique_adapter = NativeGearAdapter("mage", source, [source], items)
        with self.assertRaisesRegex(GearRejected, "UNIQUE_ITEM"):
            unique_adapter.validate(copy.deepcopy(source))

    def test_candidate_cannot_mutate_encounter_or_buffs_during_gear_probe(self):
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], self.items)
        candidate = copy.deepcopy(self.fire)
        candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {"id": 11}
        candidate["simOptions"] = {"iterations": 1}
        with self.assertRaisesRegex(GearRejected, "NON_GEAR_CHANGED"):
            adapter.validate(candidate)

    def test_source_pool_never_crosses_unverified_armor_subtype(self):
        items = copy.deepcopy(self.items)
        items[10]["armor_type"] = "ArmorTypeCloth"
        items[11]["armor_type"] = "ArmorTypePlate"
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], items)
        self.assertNotIn(11, adapter.pools.get(0, {}))

    def test_distinct_source_bounded_swaps_can_be_retried_after_native_failure(self):
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], self.items)
        first, first_audit = adapter.mutate_one(random.Random(11))
        rejected = {(first_audit["source_slot_index"], first_audit["to_id"])}
        second, second_audit = adapter.mutate_one(
            random.Random(11), excluded_swaps=rejected)
        self.assertNotEqual(
            (first_audit["source_slot_index"], first_audit["to_id"]),
            (second_audit["source_slot_index"], second_audit["to_id"]))
        adapter.validate(first)
        adapter.validate(second)
        rejected.add((second_audit["source_slot_index"], second_audit["to_id"]))
        with self.assertRaisesRegex(GearRejected, "NO_LEGAL_SOURCE_SWAP"):
            adapter.mutate_one(random.Random(11), excluded_swaps=rejected)

    def test_native_rng_panic_is_classified_not_paid(self):
        from native_gear_probe import classify_native_failure
        self.assertEqual("RUST_BALANCED_RNG_PROBABILITY",
            classify_native_failure("thread 'main' panicked at src/core/rng.rs:41:9: balanced RNG: probability must be finite and in [0,1]"))
        self.assertEqual("MISSING_NATIVE_DPS_METRIC",
            classify_native_failure("KeyError: result.raidMetrics.dps.avg"))
        self.assertEqual("RUST_NATIVE_EXECUTION",
            classify_native_failure("native Rust failed: unsupported request"))


    def test_rng_panic_replay_records_balanced_and_stochastic_without_fake_paid_score(self):
        from native_gear_probe import replay_rng_modes
        calls = []
        request = copy.deepcopy(self.fire)

        def fake_native(binary, candidate, iterations, seed, mode, deadline):
            self.assertEqual(request, candidate)
            self.assertEqual(10, iterations)
            self.assertEqual(2710, seed)
            calls.append(mode)
            if mode == "balanced":
                raise RuntimeError("src/core/rng.rs:41 balanced RNG: probability must be finite and in [0,1]")
            return 123.5, {"diagnostic": True}, 0.02, "payload-sha"

        replay = replay_rng_modes(
            "binary-placeholder", request, iterations=10, seed=2710,
            evaluator=fake_native,
        )
        self.assertEqual(["balanced", "stochastic"], calls)
        self.assertEqual("RUST_BALANCED_RNG_PROBABILITY", replay["balanced"]["category"])
        self.assertFalse(replay["balanced"]["success"])
        self.assertTrue(replay["stochastic"]["success"])
        self.assertEqual(123.5, replay["stochastic"]["diagnostic_score"])
        self.assertEqual("NOT_PAID_NOT_PROMOTABLE", replay["accounting"])
        self.assertEqual(request, self.fire)

    def test_rng_panic_replay_never_promotes_nonfinite_stochastic_score(self):
        from native_gear_probe import replay_rng_modes
        def fake_native(_binary, _candidate, _iterations, _seed, mode, _deadline):
            if mode == "balanced":
                raise RuntimeError("balanced RNG: probability must be finite and in [0,1]")
            return float("nan"), {}, 0.01, "sha"

        replay = replay_rng_modes(
            "binary-placeholder", copy.deepcopy(self.fire),
            iterations=10, seed=2710, evaluator=fake_native,
        )
        self.assertFalse(replay["stochastic"]["success"])
        self.assertEqual("NONFINITE_NATIVE_METRIC", replay["stochastic"]["category"])
        self.assertIsNone(replay["stochastic"].get("diagnostic_score"))


    def test_rng_gaps_count_each_exact_request_once_not_summary_twice(self):
        from native_gear_probe import group_gear_gaps
        rows = [{
            "profile_id": "druid/feral_cat",
            "status": "BLOCKED_NATIVE_GEAR_EVALUATION",
            "blocker": "2 distinct failures",
            "blocker_category": "RUST_BALANCED_RNG_PROBABILITY",
            "request_path": "profiles/druid__feral_cat/gear_attempt_000.request.json",
            "request_sha256": "sha-0",
            "native_failures": [
                {"category": "RUST_BALANCED_RNG_PROBABILITY",
                 "request_path": f"profiles/druid__feral_cat/gear_attempt_{i:03}.request.json",
                 "request_sha256": f"sha-{i}", "reason": "native panic",
                 "rng_replay": {"accounting": "NOT_PAID_NOT_PROMOTABLE"}}
                for i in range(2)
            ],
        }]
        groups = group_gear_gaps(rows)
        rng = groups["RUST_BALANCED_RNG_PROBABILITY"]["profiles"]
        self.assertEqual(2, len(rng))
        self.assertEqual(2, len({r["request_sha256"] for r in rng}))
        self.assertTrue(all(r["rng_replay"]["accounting"] == "NOT_PAID_NOT_PROMOTABLE"
                            for r in rng))


    def test_native_probe_cli_accepts_keyword_only_engine_source(self):
        import inspect
        from native_gear_probe import probe_all
        params = inspect.signature(probe_all).parameters
        self.assertEqual(inspect.Parameter.KEYWORD_ONLY, params["engine_src"].kind)
        self.assertEqual(inspect.Parameter.KEYWORD_ONLY, params["binary"].kind)


    def test_rng_backtrace_captures_exact_seed_and_raw_stderr_without_score(self):
        import json
        import subprocess
        import tempfile
        from native_gear_probe import capture_rng_backtrace
        source = copy.deepcopy(self.fire)
        source["simOptions"] = {"iterations": 1, "randomSeed": "42"}
        original = copy.deepcopy(source)
        seen = []

        def fake_runner(command, **kwargs):
            payload = json.loads(Path(command[command.index("--request") + 1]).read_text())
            seen.append((command, kwargs, payload))
            return subprocess.CompletedProcess(
                command, 101, "", "thread panicked: balanced RNG: probability must be finite and in [0,1]\\nstack backtrace:\\n  0: native_rng::proc\\n")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "balanced.stderr.txt"
            result = capture_rng_backtrace(
                "binary-placeholder", source, iterations=10, seed=2710,
                stderr_path=path, runner=fake_runner)
            self.assertEqual(1, len(seen))
            command, kwargs, payload = seen[0]
            self.assertEqual("balanced", kwargs["env"]["WOWSIM_RNG_MODE"])
            self.assertEqual("1", kwargs["env"]["RUST_BACKTRACE"])
            self.assertIn("--gate", command)
            self.assertEqual(10, payload["simOptions"]["iterations"])
            self.assertEqual("2710", payload["simOptions"]["randomSeed"])
            self.assertEqual(101, result["exit_code"])
            self.assertTrue(result["panic_reproduced"])
            self.assertTrue(result["backtrace_present"])
            self.assertEqual("DIAGNOSTIC_NOT_PAID", result["accounting"])
            self.assertEqual(path.read_text(), result["stderr_excerpt"])
            self.assertNotIn("score", result)
            self.assertEqual(source, original)



    def test_mutate_from_adds_second_legal_source_bounded_gear_slot(self):
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], self.items)
        original = copy.deepcopy(self.fire)
        first, audit1 = adapter.mutate_one(random.Random(11))
        # Exclude all choices at the first index so the next mutation must
        # exercise a different source-verified position.
        blocked = {(audit1["source_slot_index"], item_id)
                   for item_id in adapter.pools[audit1["source_slot_index"]]}
        second, audit2 = adapter.mutate_from(first, random.Random(22),
                                              excluded_swaps=blocked)
        self.assertNotEqual(audit1["source_slot_index"], audit2["source_slot_index"])
        self.assertEqual(2, sum(
            a != b for a, b in zip(
                original["raid"]["parties"][0]["players"][0]["equipment"]["items"],
                second["raid"]["parties"][0]["players"][0]["equipment"]["items"])))
        adapter.validate(second)
        self.assertEqual(original, self.fire)
        self.assertNotEqual(first, second)

    def test_mutate_from_refuses_illegal_input_before_proposal(self):
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], self.items)
        bad = copy.deepcopy(self.fire)
        bad["simOptions"] = {"iterations": 999}
        with self.assertRaisesRegex(GearRejected, "NON_GEAR_CHANGED"):
            adapter.mutate_from(bad, random.Random(1))

if __name__ == "__main__":
    unittest.main()
