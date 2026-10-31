"""TDD/RED contract for the shared native Rust-backed L60 search kernel.

This test is intentionally failing until the NEXT AGENT implements
integrations/mythicsim-rust/native_matrix.py. DO NOT SKIP OR XFAIL it.
No Rust CLI or fake DPS evidence enters the published native matrix here:
all evaluate() callbacks in this file are test doubles ONLY.

Work order: docs/workorders/GENERIC_NATIVE_RUST_L60_5_30_300.md
"""
from __future__ import annotations

import copy
import json
import math
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))

# Required interface for the next agent, deliberately not implemented yet:
from native_matrix import enumerate_l60_profiles, search_native, next_budget


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        # Deterministic clock makes the budget test fast and not flaky.
        self.t += 0.001
        return self.t


class NativeGenericMatrixContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(
            (ROOT / "config/validation/checkpoint_148.json").read_text()
        )
        cls.profiles = [
            (class_key, spec)
            for class_key in cls.registry["class_order"]
            for spec in cls.registry["spec_profiles"][class_key]
        ]

    def test_inventory_28_fixed_spec_profiles_nine_classes(self):
        observed = enumerate_l60_profiles(self.registry)
        self.assertEqual(self.profiles, observed)
        self.assertEqual(28, len(observed))
        self.assertEqual(9, len({cls for cls, _ in observed}))
        self.assertEqual(28, len(set(observed)))

    def test_inventory_37_with_optional_unrestricted(self):
        observed = enumerate_l60_profiles(self.registry, include_unrestricted=True)
        self.assertEqual(37, len(observed))
        self.assertEqual(37, len(set(observed)))
        for cls in self.registry["class_order"]:
            self.assertIn((cls, "unrestricted"), observed)
        self.assertEqual(self.profiles, observed[:28])

    def _fake_search(self, cls, spec, idx, *, reference=None, seed=11):
        # Intentionally *not* a native request. This is a pure kernel test and
        # must not depend on the Druid's talents, APL or 16 gear positions.
        slot_count = 12 + (idx % 7)
        reference = copy.deepcopy(reference) if reference is not None else {
            "class": cls,
            "spec": spec,
            "equipment": [{"slot": n, "id": 101 + n} for n in range(slot_count)],
            "talents": {"arbitrary_class_talent": 0},
            "apl": [{"cast_spell": 47000 + idx}],
        }
        original = copy.deepcopy(reference)
        evaluations = []

        def propose(rng: random.Random):
            cand = copy.deepcopy(reference)
            cand["equipment"][0]["id"] = rng.randint(200, 99999)
            return cand

        def mutate(candidate, rng: random.Random):
            cand = copy.deepcopy(candidate)
            cand["equipment"][-1]["id"] = rng.randint(200, 99999)
            return cand

        def legal(candidate):
            return (
                candidate["class"] == cls
                and candidate["spec"] == spec
                and len(candidate["equipment"]) == slot_count
                and all(isinstance(item["id"], int) and item["id"] > 0
                        for item in candidate["equipment"])
                and candidate["apl"] == reference["apl"]
            )

        def evaluate(candidate, *, iterations, seed, rng_mode):
            self.assertTrue(legal(candidate))
            self.assertGreater(iterations, 0)
            self.assertIsInstance(seed, int)
            self.assertIn(rng_mode, ("balanced", "stochastic"))
            evaluations.append(copy.deepcopy(candidate))
            return 100.0 + candidate["equipment"][0]["id"] / 100000.0

        result = search_native(
            profile_id=f"{cls}/{spec}",
            reference=reference,
            propose=propose,
            mutate=mutate,
            legal=legal,
            evaluate=evaluate,
            seconds=0.025,
            iterations=2,
            seed=seed,
            clock=FakeClock(),
        )
        self.assertEqual(original, reference, "Search mutated frozen reference")
        return result, evaluations, slot_count

    def test_fake_evaluator_all_28_profiles_same_search_function(self):
        for idx, (cls, spec) in enumerate(self.profiles):
            with self.subTest(class_key=cls, spec=spec):
                result, evaluated, count = self._fake_search(cls, spec, idx)
                self.assertEqual("RAN", result["status"])
                self.assertEqual(f"{cls}/{spec}", result["profile_id"])
                self.assertGreater(result["paid_candidates"], 0)
                self.assertEqual(len(evaluated), result["paid_candidates"])
                self.assertEqual(count, len(result["best_candidate"]["equipment"]))
                self.assertTrue(math.isfinite(result["best_score"]))
                self.assertLessEqual(result["elapsed_s"], 0.028)

    def test_missing_reference_blocks_without_any_evaluator_call(self):
        def fail(*_args, **_kwargs):
            self.fail("No callback may be invoked for a missing reference")

        result = search_native(
            profile_id="priest/holy",
            reference=None,
            propose=fail,
            mutate=fail,
            legal=fail,
            evaluate=fail,
            seconds=0.025,
            iterations=2,
            seed=1234,
            clock=FakeClock(),
        )
        self.assertEqual("BLOCKED_REFERENCE_MISSING", result["status"])
        self.assertEqual(0, result["paid_candidates"])

    def test_cold_rediscovery_not_illegal_by_identity_alone(self):
        # The reference may be generated naturally by a cold proposal. Never
        # seed it in production, but do not ban an identical legal outcome.
        reference = {"class": "mage", "spec": "fire", "equipment": [{"id": 12}]}
        calls = []

        def score(candidate, *, iterations, seed, rng_mode):
            calls.append(candidate)
            return 70.0

        result = search_native(
            profile_id="mage/fire",
            reference=reference,
            propose=lambda _rng: copy.deepcopy(reference),
            mutate=lambda candidate, _rng: copy.deepcopy(candidate),
            legal=lambda candidate: candidate == reference,
            evaluate=score,
            seconds=0.010,
            iterations=1,
            seed=0,
            clock=FakeClock(),
        )
        self.assertEqual("RAN", result["status"])
        self.assertTrue(calls)
        self.assertEqual(reference, result["best_candidate"])

    def test_zero_budget_blocks_without_evaluator(self):
        def fail(*_args, **_kwargs):
            self.fail("Zero-budget probe must not pay a candidate")

        result = search_native(
            profile_id="warlock/affliction",
            reference={"class": "warlock", "spec": "affliction"},
            propose=fail,
            mutate=fail,
            legal=fail,
            evaluate=fail,
            seconds=0.0,
            iterations=1,
            seed=42,
            clock=FakeClock(),
        )
        self.assertEqual("BLOCKED_BUDGET_TOO_SMALL", result["status"])
        self.assertEqual(0, result["paid_candidates"])

    def test_stages_promote_valid_ran_even_without_improvement(self):
        runnable = {"status": "RAN", "paid_candidates": 1, "engine_errors": 0}
        self.assertEqual(30, next_budget(5, runnable))
        self.assertEqual(300, next_budget(30, runnable))
        self.assertIsNone(next_budget(300, runnable))
        self.assertIsNone(next_budget(5, {**runnable, "paid_candidates": 0}))
        self.assertIsNone(next_budget(5, {**runnable, "status": "BLOCKED_GEAR_LEGALITY"}))
        self.assertIsNone(next_budget(5, {**runnable, "engine_errors": 1}))
        # Improvements are NOT required to promote a correctly running search:
        self.assertEqual(30, next_budget(5, {**runnable, "improvement": -0.1}))

    def test_budget_exhaustion_is_not_a_native_engine_failure(self):
        calls = []

        def evaluate(candidate, *, iterations, seed, rng_mode):
            calls.append(candidate)
            if len(calls) > 1:
                raise TimeoutError("No remaining time before native execution")
            return 80.0

        result = search_native(
            profile_id="hunter/survival",
            reference={"profile": "hunter/survival", "gear": [1, 2, 3]},
            propose=lambda rng: {"n": rng.randint(1, 1000000)},
            mutate=lambda candidate, rng: {"n": rng.randint(1, 1000000)},
            legal=lambda candidate: isinstance(candidate["n"], int),
            evaluate=evaluate,
            seconds=0.025,
            iterations=1,
            seed=11,
            clock=FakeClock(),
        )
        self.assertEqual("RAN", result["status"])
        self.assertEqual(0, result["engine_errors"])
        self.assertEqual(1, result["paid_candidates"])
        self.assertIsNone(next_budget(300, result))
        self.assertEqual(30, next_budget(5, result))

    def test_non_finite_native_metric_is_not_a_paid_candidate(self):
        result = search_native(
            profile_id="rogue/combat",
            reference={"profile": "rogue/combat"},
            propose=lambda rng: {"n": rng.randint(1, 1000000)},
            mutate=lambda candidate, rng: {"n": rng.randint(1, 1000000)},
            legal=lambda candidate: True,
            evaluate=lambda candidate, *, iterations, seed, rng_mode: float("nan"),
            seconds=0.015,
            iterations=1,
            seed=11,
            clock=FakeClock(),
        )
        self.assertEqual("BLOCKED_ENGINE_ERROR", result["status"])
        self.assertEqual(0, result["paid_candidates"])
        self.assertGreater(result["engine_errors"], 0)



    def test_apl_preserves_source_item_and_other_cast_oneofs(self):
        # Fury source has itemId/otherId cast actions alongside normal spells.
        # Those existing native identities are legal; new identities are not.
        from apl_mutation import mutate_apl
        corpus = [
            {"action": {"castSpell": {"spellId": {"spellId": 11597, "rank": 5}}}},
            {"action": {"castSpell": {"spellId": {"itemId": 10646}}}},
            {"action": {"castSpell": {"spellId": {"otherId": "OtherActionPotion"}}}},
            {"action": {"castSpell": {"spellId": {"spellId": 1719}}}},
        ]
        frozen = copy.deepcopy(corpus)
        allowed = {json.dumps(a["action"]["castSpell"]["spellId"], sort_keys=True)
                   for a in corpus}
        rng = random.Random(2701)
        for _ in range(30):
            candidate = mutate_apl(None, corpus, rng, cold=True)
            self.assertTrue(candidate)
            self.assertTrue(all(
                json.dumps(a["action"]["castSpell"]["spellId"], sort_keys=True) in allowed
                for a in candidate
            ))
        self.assertEqual(frozen, corpus)

    def test_apl_preserves_source_complex_native_action_kinds(self):
        # Shadow source includes strictSequence, multidot and channelSpell.
        # Reordering source actions must not be mistaken for inventing them.
        from apl_mutation import mutate_apl
        corpus = [
            {"action": {"castSpell": {"spellId": {"spellId": 1259823}}}},
            {"action": {"castSpell": {"spellId": {"spellId": 10894}}}},
            {"action": {"strictSequence": {"actions": [
                {"castSpell": {"spellId": {"spellId": 14751}}}
            ]}}},
            {"action": {"multidot": {"maxDots": 5, "spellId": {"spellId": 10894}}}},
            {"action": {"channelSpell": {"spellId": {"spellId": 18807}}}},
            {"action": {"autocastOtherCooldowns": {}}},
        ]
        frozen = copy.deepcopy(corpus)
        noncast = {json.dumps(a["action"], sort_keys=True)
                   for a in corpus if "castSpell" not in a["action"]}
        rng = random.Random(2702)
        for _ in range(30):
            candidate = mutate_apl(None, corpus, rng, cold=True)
            self.assertTrue(all(
                json.dumps(a["action"], sort_keys=True) in noncast
                for a in candidate if "castSpell" not in a["action"]
            ))
        self.assertEqual(frozen, corpus)



    def test_native_item_db_inventory_uses_pinned_ids_not_slot_guesses(self):
        from tempfile import TemporaryDirectory
        from native_l60_matrix import load_native_item_index, describe_native_gear
        with TemporaryDirectory() as temp:
            source = Path(temp)
            (source / "data").mkdir()
            (source / "data/items.jsonl").write_text(
                json.dumps({"id": 35, "name": "Bent Staff",
                            "type": "ItemTypeWeapon", "hand_type": "HandTypeTwoHand"})
                + "\n" +
                json.dumps({"id": 40, "name": "Recruit's Boots",
                            "type": "ItemTypeFeet", "armor_type": "ArmorTypeCloth"})
                + "\n"
            )
            index = load_native_item_index(source)
            gear, missing = describe_native_gear(
                {"items": [{"id": 35}, {"id": 0}, {"id": 40}, {"id": 99999}]},
                index,
            )
            self.assertEqual([35, 40, 99999], [x["id"] for x in gear])
            self.assertEqual([0, 2, 3], [x["source_slot_index"] for x in gear])
            self.assertEqual("HandTypeTwoHand", gear[0]["hand_type"])
            self.assertEqual("ArmorTypeCloth", gear[1]["armor_type"])
            self.assertEqual([99999], missing)
            self.assertFalse(gear[2]["native_db_present"])


    def test_subprocess_timeout_is_budget_expiry_not_engine_error(self):
        import subprocess
        attempts = []

        def native(candidate, *, iterations, seed, rng_mode):
            attempts.append(candidate)
            if len(attempts) == 2:
                raise subprocess.TimeoutExpired(cmd=["forever-engine", "sim"], timeout=0.01)
            return 42.0

        result = search_native(
            profile_id="mage/fire", reference={"source": "pinned"},
            propose=lambda rng: {"nonce": rng.randint(1, 1000000)},
            mutate=lambda candidate, rng: {"nonce": rng.randint(1, 1000000)},
            legal=lambda candidate: True, evaluate=native,
            seconds=0.025, iterations=1, seed=27, clock=FakeClock(),
        )
        self.assertEqual("RAN", result["status"])
        self.assertEqual(1, result["paid_candidates"])
        self.assertEqual(0, result["engine_errors"])



    def test_apl_only_legal_guard_freezes_entire_native_request(self):
        # APL-only must never turn into a hidden buff, encounter, gear,
        # talent or simOptions search, even if a caller supplies bad mutations.
        from native_l60_matrix import legal_apl_only_request
        source = {
            "simOptions": {"randomSeed": "2710", "iterations": 10},
            "encounter": {"duration": 120},
            "raid": {"buffs": {"someBuff": True}, "parties": [{"players": [{
                "class": "ClassMage",
                "talentsString": "111",
                "equipment": {"items": [{"id": 35}, {"id": 40}]},
                "rotation": {"prepullActions": [{"action": "keep"}],
                             "priorityList": [
                    {"action": {"castSpell": {"spellId": {"spellId": 1001}}}},
                    {"action": {"castSpell": {"spellId": {"spellId": 1002}}}},
                ]},
            }]}]},
        }
        frozen = copy.deepcopy(source)
        legal = copy.deepcopy(source)
        actions = legal["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
        actions.reverse()
        self.assertTrue(legal_apl_only_request(source, legal))
        for key in ("simOptions", "encounter"):
            with self.subTest(non_apl=key):
                bad = copy.deepcopy(legal)
                bad[key]["unexpected"] = 1
                self.assertFalse(legal_apl_only_request(source, bad))
        for path in ("buffs", "equipment", "talentsString", "prepullActions"):
            with self.subTest(non_apl=path):
                bad = copy.deepcopy(legal)
                p = bad["raid"]["parties"][0]["players"][0]
                if path == "buffs":
                    bad["raid"]["buffs"]["someBuff"] = False
                elif path == "equipment":
                    p["equipment"]["items"][0]["id"] = 99
                elif path == "talentsString":
                    p["talentsString"] = "222"
                else:
                    p["rotation"]["prepullActions"] = []
                self.assertFalse(legal_apl_only_request(source, bad))
        self.assertEqual(source, frozen)

    def test_apl_only_legal_guard_rejects_unseen_native_spell_identity(self):
        from native_l60_matrix import legal_apl_only_request
        source = {"raid": {"parties": [{"players": [{
            "rotation": {"priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 1234}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 5678}}}},
            ]}
        }]}]}}
        legal = copy.deepcopy(source)
        legal["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"].reverse()
        self.assertTrue(legal_apl_only_request(source, legal))
        bad = copy.deepcopy(legal)
        bad["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"][0]["action"]["castSpell"]["spellId"] = {"spellId": 999999}
        self.assertFalse(legal_apl_only_request(source, bad))
        self.assertFalse(legal_apl_only_request(source, {"raid": {}}))

if __name__ == "__main__":
    unittest.main()
