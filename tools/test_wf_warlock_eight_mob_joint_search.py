"""Native eight-kill joint optimizer: search operators never emulate combat."""
import copy
import random
import unittest
from types import SimpleNamespace
from wf_warlock_eight_mob_joint_search import (
    source_item_pools, request_signature, apl_mutation,
    mutate_talents, mutate_request, sorted_observed_native,
    native_cast_identifiers,
)


def source():
    return {
        "raid": {"parties": [{"players": [{
            "talentsString": "2-1-0",
            "equipment": {"items": [{"id": 0} for _ in range(17)]},
            "rotation": {"priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 101}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 202}}}},
            ]},
            "warlock": {"options": {"classOptions": {"summon": "Succubus"}}},
        }]}]}
    }


def options():
    return {
        "level": 30,
        "items": [
            {"item_id": 100, "eligibility": "native_eligible",
             "native": {"required_level": 20, "slot": "head"}},
            {"item_id": 101, "eligibility": "native_eligible",
             "native": {"required_level": 31, "slot": "head"}},
            {"item_id": 102, "eligibility": "native_eligible",
             "native": {"required_level": 0, "slot": "head"}},
        ],
        "talents": {"trees": [
            {"talents": [{"index": 0, "max_rank": 5, "minimum_level": 10},
                         {"index": 1, "max_rank": 5, "minimum_level": 10}]},
            {"talents": [{"index": 0, "max_rank": 5, "minimum_level": 10}]},
            {"talents": [{"index": 0, "max_rank": 5, "minimum_level": 10}]},
        ]}
    }


class NativeEightSearchTests(unittest.TestCase):
    def test_only_source_level_eligible_gear_enters_mutations(self):
        pools = source_item_pools(options())
        self.assertEqual(pools[0], (100,))
        self.assertNotIn(101, pools[0])
        self.assertNotIn(102, pools[0])

    def test_talent_mutations_preserve_budget_without_claiming_legality(self):
        rng = random.Random(42)
        for _ in range(30):
            text = mutate_talents("2-1-0", options(), rng)
            self.assertEqual(sum(int(ch) for ch in text if ch.isdigit()), 3)
            self.assertEqual(len(text.split("-")), 3)

    def test_request_key_tracks_all_four_axes(self):
        base = source()
        mutated = copy.deepcopy(base)
        mutated["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"].reverse()
        self.assertNotEqual(request_signature(base), request_signature(mutated))
        mutated = copy.deepcopy(base)
        mutated["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] = {"id": 100}
        self.assertNotEqual(request_signature(base), request_signature(mutated))

    def test_apl_order_is_mutable_not_prescribed(self):
        class Native:
            @staticmethod
            def cast_apl(spell_id, *, guard=None):
                return {"action": {"castSpell": {"spellId": {"spellId": spell_id}}},
                        "guard": guard}
        ap = source()["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
        rng = random.Random(7)
        outcomes = [apl_mutation(ap, [{"spellId": 101}, {"spellId": 202},
                                     {"spellId": 303}, {"otherId": "OtherActionShoot"}], Native, rng)
                    for _ in range(50)]
        self.assertTrue(all(1 <= len(actions) <= 12 for actions in outcomes))
        self.assertTrue(any(actions != ap for actions in outcomes))
        self.assertTrue(any(actions[0] != ap[0] for actions in outcomes))

    def test_shoot_is_discovered_from_native_prepared_and_mutatable(self):
        native = {"player": {"spells": [
            {"action_id": {"spell_id": 116}},
            {"action_id": {"other_id": "OtherActionShoot"}},
        ]}}
        options = native_cast_identifiers(native)
        self.assertIn({"otherId": "OtherActionShoot"}, options)
        self.assertIn({"spellId": 116}, options)
        class Native:
            @staticmethod
            def cast_apl(spell_id, *, guard=None):
                return {"action": {"castSpell": {"spellId": {"spellId": spell_id}}}}
        actions = []
        rng = random.Random(1)
        for _ in range(100):
            actions = apl_mutation(actions or [], options, Native, rng)
            if any((item["action"].get("castSpell") or {}).get("spellId",{})
                   .get("otherId")=="OtherActionShoot" for item in actions):
                break
        self.assertTrue(any((item["action"].get("castSpell") or {}).get("spellId",{})
                            .get("otherId")=="OtherActionShoot" for item in actions))
        self.assertNotIn({"otherId": "OtherActionShoot"},
                         native_cast_identifiers({"player": {"spells": []}}))

    def test_model_ranks_only_real_native_eight_probes(self):
        probes = [{"probe": {"features": {"mean_kill_s": i}}, "result": {"candidate": i}}
                  for i in range(3)]
        probes[1]["probe"] = None
        def p(model, probe, **kwargs):
            return {"estimated_100_mob_elapsed_s": 2000 + probe["features"]["mean_kill_s"]}
        ordered = sorted_observed_native(probes, {"time_model": {}}, predict=p,
                                        engine_sha="r", scenario_id="s")
        self.assertEqual([case["result"]["candidate"] for _, case in ordered], [0, 2])


if __name__ == "__main__":
    unittest.main()
