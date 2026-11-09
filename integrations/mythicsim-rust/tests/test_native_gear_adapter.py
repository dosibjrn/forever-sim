"""Mock-fixture admission tests; NO fake scores may enter native reports."""
import copy
import random
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from native_gear_adapter import NativeGearAdapter, GearRejected


def req(cls, ids):
    return {
        "raid": {"parties": [{"players": [{"class": "Class" + cls,
            "equipment": {"items": [{"id": x} for x in ids]},
            "talentsString": "51",
            "rotation": {"priorityList": [{"action": {"wait": {}}}]}}]}]},
        "simOptions": {"iterations": 3, "randomSeed": "47"},
    }


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
        self.assertEqual((0, 1, 2), adapter.mutable_indices)
        self.assertEqual({10, 11}, {item["id"] for item in adapter.variants[0]})
        self.assertEqual({20, 21}, {item["id"] for item in adapter.variants[1]})
        self.assertEqual({30, 31}, {item["id"] for item in adapter.variants[2]})  # native decides weapon/hand legality

    def test_native_mutation_preserves_reference_talents_apl_and_weapon(self):
        original = copy.deepcopy(self.fire)
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], self.items)
        candidate, audit = adapter.mutate_one(random.Random(10))
        self.assertEqual(original, self.fire)
        original_player = original["raid"]["parties"][0]["players"][0]
        candidate_player = candidate["raid"]["parties"][0]["players"][0]
        self.assertEqual(original_player["talentsString"], candidate_player["talentsString"])
        self.assertEqual(original_player["rotation"], candidate_player["rotation"])
        self.assertEqual(1, sum(
            a != b for a, b in zip(original_player["equipment"]["items"],
                                   candidate_player["equipment"]["items"])))
        self.assertIn(audit["source_slot_index"], (0, 1, 2))
        adapter.validate(candidate)

    def test_native_item_type_and_class_rules_do_not_prevent_source_proposal(self):
        items = copy.deepcopy(self.items)
        items[11]["class_allowlist"] = ["ClassWarrior"]
        items[11]["type"] = "ItemTypeChest"  # wrong slot/type is still a native decision
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], items)
        self.assertTrue(any(item["id"] == 11 for item in adapter.variants[0]))
        candidate = copy.deepcopy(self.fire)
        candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {"id": 11}
        adapter.validate(candidate)  # proposal only; MythicSim owns the verdict

        from native_joint_two_class import native_score_request, native_payload, fingerprint
        from native_matrix import NativeCandidateRefusal
        import time
        seen = []
        raw = {"status": "INVALID", "error": "native equipment refusal"}
        def native_runner(_binary, request, iterations, seed, rng_mode, _deadline, *, objective="DPS"):
            self.assertEqual("DPS", objective)
            seen.append(copy.deepcopy(request))
            raise NativeCandidateRefusal(
                "INVALID", raw_response=raw, reason=raw["error"],
                request_sha256=fingerprint(native_payload(request, iterations, seed)),
            )
        with self.assertRaises(NativeCandidateRefusal) as caught:
            native_score_request(Path("forever-engine"), candidate, 4, 731,
                                 "balanced", time.monotonic() + 1.0,
                                 runner=native_runner)
        self.assertEqual([candidate], seen)
        self.assertEqual("INVALID", caught.exception.status)
        self.assertIs(raw, caught.exception.raw_response)

    def test_source_observed_same_id_enchant_variant_is_mutable(self):
        # RED before fix: ID-only pools reported no mutable gear even though
        # the pinned same-class request had a different exact item entry.
        source = copy.deepcopy(self.fire)
        donor = copy.deepcopy(self.fire)
        donor["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {
            "id": 10, "enchant": {"effectId": 123}
        }
        adapter = NativeGearAdapter("mage", source, [source, donor], self.items)
        self.assertEqual((0,), adapter.mutable_indices)
        candidate, audit = adapter.mutate_one(random.Random(2))
        entry = candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]
        self.assertEqual({"id": 10, "enchant": {"effectId": 123}}, entry)
        self.assertEqual(10, audit["from_id"])
        self.assertEqual(10, audit["to_id"])
        adapter.validate(candidate)
        unobserved = copy.deepcopy(candidate)
        unobserved["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["enchant"]["effectId"] = 124
        with self.assertRaisesRegex(GearRejected, "SOURCE_SLOT"):
            adapter.validate(unobserved)

    def test_native_refusal_excludes_exact_enchant_variant_not_every_same_id_variant(self):
        # Two observed enchants share the item ID. Rejecting one native
        # request must not silently discard the other source proposal.
        source = req("Mage", [10])
        donors = []
        for effect_id in (123, 456):
            donor = copy.deepcopy(source)
            donor["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {
                "id": 10, "enchant": {"effectId": effect_id}
            }
            donors.append(donor)
        adapter = NativeGearAdapter("mage", source, [source, *donors])
        first, audit = adapter.mutate_one(random.Random(7))
        excluded = {(audit["source_slot_index"], audit["to_id"],
                     audit["to_variant_sha256"])}
        second, second_audit = adapter.mutate_one(
            random.Random(7), excluded_swaps=excluded
        )
        self.assertEqual(10, audit["to_id"])
        self.assertEqual(10, second_audit["to_id"])
        self.assertNotEqual(
            first["raid"]["parties"][0]["players"][0]["equipment"]["items"][0],
            second["raid"]["parties"][0]["players"][0]["equipment"]["items"][0],
        )
        self.assertNotEqual(audit["to_variant_sha256"],
                            second_audit["to_variant_sha256"])
        adapter.validate(second)
        # The same exact-variant exclusion applies when extending a candidate.
        extended, extended_audit = adapter.mutate_from(
            first, random.Random(7), excluded_swaps=excluded
        )
        self.assertEqual(second["raid"]["parties"][0]["players"][0]["equipment"]["items"],
                         extended["raid"]["parties"][0]["players"][0]["equipment"]["items"])
        self.assertEqual(second_audit["to_variant_sha256"],
                         extended_audit["to_variant_sha256"])

    def test_weapon_id_and_enchant_proposals_reach_native(self):
        source = req("Shaman", [30])
        enchant_donor = copy.deepcopy(source)
        enchant_donor["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {
            "id": 30, "enchant": {"effectId": 123}
        }
        items = {
            30: {"type": "ItemTypeWeapon", "hand_type": "HandTypeTwoHand",
                 "class_allowlist": ["ClassShaman"]},
            31: {"type": "ItemTypeWeapon", "hand_type": "HandTypeOneHand",
                 "class_allowlist": ["ClassShaman"]},
        }
        enchant_adapter = NativeGearAdapter("shaman", source, [source, enchant_donor], items)
        self.assertEqual((0,), enchant_adapter.mutable_indices)
        enchant_candidate, audit = enchant_adapter.mutate_one(random.Random(2))
        entry = enchant_candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]
        self.assertEqual({"id": 30, "enchant": {"effectId": 123}}, entry)
        self.assertEqual(30, audit["from_id"])
        self.assertEqual(30, audit["to_id"])
        enchant_adapter.validate(enchant_candidate)

        # A different weapon/hand identity is a proposal too; Rust owns the refusal.
        changed_weapon = copy.deepcopy(source)
        changed_weapon["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {"id": 31}
        adapter = NativeGearAdapter("shaman", source, [source, changed_weapon], items)
        self.assertEqual((0,), adapter.mutable_indices)
        candidate, audit = adapter.mutate_one(random.Random(2))
        self.assertEqual({"id": 31}, candidate["raid"]["parties"][0]["players"][0]
                         ["equipment"]["items"][0])
        self.assertEqual(30, audit["from_id"])
        self.assertEqual(31, audit["to_id"])
        adapter.validate(candidate)

        from native_joint_two_class import native_score_request, native_payload, fingerprint
        from native_matrix import NativeCandidateRefusal
        import time
        seen = []
        raw = {"status": "INVALID", "reason": "native hand/equipment refusal"}

        def native_runner(_binary, request, iterations, seed, rng_mode, _deadline, *, objective="DPS"):
            self.assertEqual("DPS", objective)
            seen.append(copy.deepcopy(request))
            raise NativeCandidateRefusal(
                "INVALID", raw_response=raw, reason=raw["reason"],
                request_sha256=fingerprint(native_payload(request, iterations, seed)),
            )

        with self.assertRaises(NativeCandidateRefusal) as caught:
            native_score_request(Path("forever-engine"), candidate, 4, 731,
                                 "balanced", time.monotonic() + 1.0,
                                 runner=native_runner)
        self.assertEqual([candidate], seen)
        self.assertEqual("INVALID", caught.exception.status)
        self.assertIs(raw, caught.exception.raw_response)

    def test_source_observed_unknown_item_identity_is_not_a_python_veto(self):
        source = req("Mage", [10])
        donor = req("Mage", [999999])
        adapter = NativeGearAdapter("mage", source, [source, donor], self.items)
        self.assertEqual((0,), adapter.mutable_indices)
        candidate = copy.deepcopy(source)
        candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {"id": 999999}
        adapter.validate(candidate)  # unknown native identity is sent to Rust, not pre-rejected

        from native_joint_two_class import native_score_request, native_payload, fingerprint
        from native_matrix import NativeCandidateRefusal
        import time
        seen = []
        raw = {"status": "INVALID", "reason": "native unknown-item refusal"}

        def native_runner(_binary, request, iterations, seed, rng_mode, _deadline, *, objective="DPS"):
            self.assertEqual("DPS", objective)
            seen.append(copy.deepcopy(request))
            raise NativeCandidateRefusal(
                "INVALID", raw_response=raw, reason=raw["reason"],
                request_sha256=fingerprint(native_payload(request, iterations, seed)),
            )

        with self.assertRaises(NativeCandidateRefusal) as caught:
            native_score_request(Path("forever-engine"), candidate, 4, 731,
                                 "balanced", time.monotonic() + 1.0,
                                 runner=native_runner)
        self.assertEqual([candidate], seen)
        self.assertEqual("INVALID", caught.exception.status)
        self.assertIs(raw, caught.exception.raw_response)

    def test_no_alternatives_blocks_explicitly(self):
        adapter = NativeGearAdapter("mage", self.fire, [self.fire], self.items)
        with self.assertRaisesRegex(GearRejected, "NO_SOURCE_BOUNDED_ALTERNATIVE"):
            adapter.mutate_one(random.Random(1))

    def test_native_unique_category_is_not_a_python_legality_veto(self):
        items = copy.deepcopy(self.items)
        items[11]["limit_category"] = 55
        items[20]["limit_category"] = 55
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], items)
        candidate = copy.deepcopy(self.fire)
        candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {"id": 11}
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
        unique_adapter.validate(copy.deepcopy(source))  # native decides uniqueness

    def test_candidate_cannot_mutate_encounter_or_buffs_during_gear_probe(self):
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], self.items)
        candidate = copy.deepcopy(self.fire)
        candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {"id": 11}
        candidate["simOptions"] = {"iterations": 1}
        with self.assertRaisesRegex(GearRejected, "NON_GEAR_CHANGED"):
            adapter.validate(candidate)

    def test_source_observed_armor_subtype_is_forwarded_to_native(self):
        items = copy.deepcopy(self.items)
        items[10]["armor_type"] = "ArmorTypeCloth"
        items[11]["armor_type"] = "ArmorTypePlate"
        items[11]["required_level"] = 61
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], items)
        self.assertTrue(any(item["id"] == 11 for item in adapter.variants[0]))
        candidate = copy.deepcopy(self.fire)
        candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {"id": 11}
        adapter.validate(candidate)  # no Python armor or level legality verdict

    def test_distinct_source_bounded_swaps_can_be_retried_after_native_failure(self):
        adapter = NativeGearAdapter("mage", self.fire, [self.fire, self.frost], self.items)
        seen = set()
        candidates = []
        for _ in range(3):
            candidate, audit = adapter.mutate_one(random.Random(11), excluded_swaps=seen)
            swap = (audit["source_slot_index"], audit["to_id"])
            self.assertNotIn(swap, seen)
            seen.add(swap)
            candidates.append(candidate)
            adapter.validate(candidate)
        self.assertEqual(3, len(seen))  # head, chest and weapon proposals all remain searchable
        with self.assertRaisesRegex(GearRejected, "NO_SOURCE_OBSERVED_SWAP"):
            adapter.mutate_one(random.Random(11), excluded_swaps=seen)

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
            self.assertEqual("balanced", command[command.index("--rng-mode") + 1])
            self.assertNotIn("WOWSIM_RNG_MODE", kwargs["env"])
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
        blocked = {
            (audit1["source_slot_index"], item["id"])
            for item in adapter.variants[audit1["source_slot_index"]]
        }
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
