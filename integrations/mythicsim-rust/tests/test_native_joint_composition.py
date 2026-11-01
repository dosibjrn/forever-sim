"""Two-class FAKE evaluator contract for the ONE native search core.

Not a native Rust run or P7 certification. Production two-class evidence
requires pinned engine, per-class verified 51-point talent/gear/APL adapters,
exact paid-request replay, and independent stochastic holdout.
"""
from __future__ import annotations

import copy
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_joint_composition import (
    CandidateAxis, JointCandidateAdapter, search_joint,
)


class FakeClock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        self.value += .001
        return self.value


def fixture(class_name: str, nslots: int, spell: int, first_id: int):
    return {
        "raid": {"parties": [{"players": [{
            "class": class_name,
            "equipment": {"items": [{"id": first_id + j}
                                    for j in range(nslots)]},
            "talentsString": "source-build",
            "rotation": {"priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": spell}}}},
                {"action": {"castSpell": {"spellId": {"spellId": spell + 1}}}},
            ]},
        }]}]},
        "encounter": {"duration": 180, "targets": 1},
        "simOptions": {"iterations": 3, "randomSeed": "47"},
        "partyBuffs": {"frozen": True},
    }


def player(request):
    return request["raid"]["parties"][0]["players"][0]


def adapters(reference, spell, first_id):
    native_ids = {first_id, first_id + 500, first_id + 501}
    original_gear = copy.deepcopy(player(reference)["equipment"]["items"])
    original_apl = copy.deepcopy(player(reference)["rotation"]["priorityList"])

    def gear_choice(rng):
        out = copy.deepcopy(original_gear)
        out[0]["id"] = rng.choice(sorted(native_ids))
        return out

    def gear_mutate(current, rng):
        out = copy.deepcopy(current)
        out[0]["id"] = rng.choice(sorted(native_ids - {out[0]["id"]}))
        return out

    def gear_legal(items):
        return (
            isinstance(items, list) and len(items) == len(original_gear)
            and items[1:] == original_gear[1:]
            and isinstance(items[0], dict)
            and items[0].get("id") in native_ids
        )

    def talents_cold(rng):
        return rng.choice(("legal-build-A", "legal-build-B"))

    def talents_mutate(current, _rng):
        return "legal-build-B" if current == "legal-build-A" else "legal-build-A"

    def talents_legal(s):
        return s in ("legal-build-A", "legal-build-B")

    def apl_cold(rng):
        a = copy.deepcopy(original_apl)
        if rng.randrange(2):
            a.reverse()
        return a

    def apl_mutate(current, _rng):
        return list(reversed(copy.deepcopy(current)))

    def apl_legal(actions):
        return (
            isinstance(actions, list)
            and len(actions) == 2
            and sorted(a["action"]["castSpell"]["spellId"]["spellId"]
                       for a in actions) == [spell, spell + 1]
        )

    def joint_legal(request):
        p = player(request)
        return (p["class"] == player(reference)["class"]
                and gear_legal(p["equipment"]["items"])
                and talents_legal(p["talentsString"])
                and apl_legal(p["rotation"]["priorityList"]))

    return JointCandidateAdapter(
        reference, joint_legal=joint_legal,
        gear=CandidateAxis(gear_choice, gear_mutate, gear_legal),
        talents=CandidateAxis(talents_cold, talents_mutate, talents_legal),
        apl=CandidateAxis(apl_cold, apl_mutate, apl_legal),
    )


class SameSearchCoreAcrossClasses(unittest.TestCase):
    def test_two_class_joint_search_uses_same_kernel_and_all_three_axes(self):
        for class_name, slots, spell, iid in (
            ("ClassDruid", 16, 1001, 2001),
            ("ClassHunter", 18, 2001, 3001),
        ):
            with self.subTest(class_name=class_name):
                ref = fixture(class_name, slots, spell, iid)
                snapshot = copy.deepcopy(ref)
                adapter = adapters(ref, spell, iid)
                paid = []

                def mock_evaluate(candidate, *, iterations, seed, rng_mode):
                    self.assertTrue(adapter.legal(candidate))
                    self.assertEqual("balanced", rng_mode)
                    self.assertEqual(3, iterations)
                    self.assertEqual(123, seed)
                    paid.append(copy.deepcopy(candidate))
                    p = player(candidate)
                    return (100.0 + p["equipment"]["items"][0]["id"] * .001
                            + (p["talentsString"] == "legal-build-B") * .1
                            + (p["rotation"]["priorityList"][0]["action"]
                               ["castSpell"]["spellId"]["spellId"] == spell + 1) * .2)

                result = search_joint(
                    profile_id=class_name + "/test",
                    adapter=adapter, evaluate=mock_evaluate,
                    seconds=.09, iterations=3, seed=123, clock=FakeClock(),
                )
                self.assertEqual("RAN", result["status"])
                self.assertGreater(result["paid_candidates"], 0)
                self.assertEqual(result["paid_candidates"], len(paid))
                self.assertEqual(snapshot, ref, "Frozen request was mutated")
                self.assertEqual(snapshot, adapter.reference)
                self.assertEqual(slots, len(player(result["best_candidate"])
                                            ["equipment"]["items"]))
                # Genuine three-dimensional candidate exploration within ONE
                # search call; class-specific legality supplied via adapters.
                self.assertGreater(len({player(q)["equipment"]["items"][0]["id"]
                                        for q in paid}), 1)
                self.assertGreater(len({player(q)["talentsString"] for q in paid}), 1)
                self.assertGreater(len({tuple(
                    a["action"]["castSpell"]["spellId"]["spellId"]
                    for a in player(q)["rotation"]["priorityList"]) for q in paid}), 1)

    def test_illegal_item_talent_apl_class_and_scenario_are_rejected(self):
        ref = fixture("ClassDruid", 16, 1001, 2001)
        adapter = adapters(ref, 1001, 2001)
        good = adapter.propose(random.Random(123))
        self.assertTrue(adapter.legal(good))
        for corrupt in ("gear", "talent", "apl", "class", "encounter", "buffs"):
            with self.subTest(corrupt=corrupt):
                bad = copy.deepcopy(good)
                if corrupt == "gear":
                    player(bad)["equipment"]["items"][0]["id"] = 999999
                elif corrupt == "talent":
                    player(bad)["talentsString"] = "illegal-build"
                elif corrupt == "apl":
                    player(bad)["rotation"]["priorityList"][0]["action"][
                        "castSpell"]["spellId"]["spellId"] = 99999
                elif corrupt == "class":
                    player(bad)["class"] = "ClassMage"
                elif corrupt == "encounter":
                    bad["encounter"]["duration"] = 60
                else:
                    bad["partyBuffs"]["frozen"] = False
                self.assertFalse(adapter.legal(bad))

    def test_mutate_can_select_all_three_axes_simultaneously(self):
        adapter = adapters(fixture("ClassHunter", 18, 2001, 3001), 2001, 3001)
        initial = adapter.propose(random.Random(42))

        class ThreeAxes:
            def random(self):
                return .99

            def sample(self, sequence, n):
                self.assert_is_three(n)
                return list(sequence)

            def choice(self, options):
                return options[-1]

            def assert_is_three(self, n):
                assert n == 3

        updated = adapter.mutate(initial, ThreeAxes())
        self.assertTrue(adapter.legal(updated))
        for key in ("equipment", "talentsString", "rotation"):
            self.assertNotEqual(player(initial)[key], player(updated)[key])


class SourceTalentEncodingContracts(unittest.TestCase):
    """Pinned Rust fixtures use both two-tree and three-tree encodings.

    The point counter must not reject an entire class merely because one
    legitimate 51-point source fixture omits the final empty tree delimiter.
    These are source strings, NOT synthesized legal talent allocations.
    """

    def test_rogue_assassination_two_tree_source_has_51_points(self):
        from native_joint_two_class import talent_points
        self.assertEqual(51, talent_points("0053031055110105-30230320201401"))

    def test_holy_priest_two_tree_source_has_51_points(self):
        from native_joint_two_class import talent_points
        self.assertEqual(51, talent_points("00520101133-33505003030121531"))

    def test_three_tree_source_and_explicit_empty_middle_tree(self):
        from native_joint_two_class import talent_points
        self.assertEqual(51, talent_points("005303105-32030320201515221-002"))
        self.assertEqual(51, talent_points("025303011030--50052201221302251"))

    def test_invalid_talent_encoding_stays_rejected(self):
        from native_joint_two_class import talent_points
        for invalid in ("12345", "1-2-3-4", "1-2-X", "", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    talent_points(invalid)


if __name__ == "__main__":
    unittest.main()
