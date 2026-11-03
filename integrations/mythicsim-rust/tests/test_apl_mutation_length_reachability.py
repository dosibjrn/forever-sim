"""Cold APL length must cover source-legal policies beyond the saved reference length."""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import unittest

from apl_mutation import (
    _condition_spell_identity_keys, _corpus, _new_cast, mutate_apl,
)
from native_joint_two_class import _ensure_native_damage_action, _native_positive_source_casts


def _predicate_shape(value):
    if isinstance(value, list):
        return [_predicate_shape(child) for child in value]
    if isinstance(value, dict):
        result = {}
        for key, child in sorted(value.items()):
            if (key == "val" and isinstance(child, str)
                    and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:ms|s)?", child)):
                result[key] = "<NUMERIC_LITERAL>"
            else:
                result[key] = _predicate_shape(child)
        return result
    return value


def test_cold_search_can_reach_legal_19_action_policy_length_without_seeding_it():
    repo = ROOT.parent.parent
    reference = json.loads(
        (repo / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json").read_text()
    )
    historical = json.loads(
        (repo / "docs/evidence/druid-l60-balance/p7.5/historical_wf678_winner_axes.json").read_text()
    )
    source_actions = reference["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
    historical_actions = historical["rotation"]["priorityList"]

    # The high-scoring historical APL is only a source-grammar/length witness.
    # The generator below receives the saved request grammar, never historical actions.
    assert len(source_actions) == 10
    assert len(historical_actions) == 19

    _, same_spell, allowed_casts, compatible = _corpus(source_actions)
    source_predicates = [
        predicate
        for predicates in same_spell.values()
        for predicate in predicates
    ]
    historical_casts = {
        json.dumps(action["action"]["castSpell"]["spellId"],
                   sort_keys=True, separators=(",", ":"))
        for action in historical_actions
        if isinstance(action.get("action", {}).get("castSpell"), dict)
    }
    assert historical_casts <= allowed_casts

    source_shapes = {
        json.dumps(_predicate_shape(predicate), sort_keys=True, separators=(",", ":"))
        for predicate in source_predicates
    }
    historical_compatible_shapes = []
    for action in historical_actions:
        condition = action.get("action", {}).get("condition")
        if not isinstance(condition, dict):
            continue
        refs, valid = _condition_spell_identity_keys(condition)
        # Keep same-spell predicates and the historically proven cross-spell
        # predicates whose references all belong to source cast identities.
        if valid and set(refs) <= allowed_casts:
            historical_compatible_shapes.append(json.dumps(
                _predicate_shape(condition), sort_keys=True, separators=(",", ":")
            ))
    assert len(historical_compatible_shapes) == 11
    assert set(historical_compatible_shapes) <= source_shapes

    saved_snapshot = json.loads(json.dumps(source_actions))
    generated = mutate_apl(None, source_actions, random.Random(29), cold=True)
    assert len(generated) >= len(historical_actions)
    assert len(generated) <= 20
    assert source_actions == saved_snapshot



def test_cold_and_elite_cast_conditions_use_only_source_compatible_predicates():
    source_actions = [
        {
            "action": {
                "castSpell": {"spellId": {"spellId": 11689}},
                "condition": {"auraIsActive": {"auraId": {"spellId": 11689}}},
            }
        },
        {
            "action": {
                "castSpell": {"spellId": {"spellId": 1311680}},
                "condition": {
                    "and": {"vals": [
                        {"auraIsActive": {"auraId": {"spellId": 1311680}}},
                        {"dotIsActive": {"spellId": {"spellId": 11689}}},
                    ]}
                },
            }
        },
        {
            "action": {
                "castSpell": {"spellId": {"spellId": 25311}},
                "condition": {"dotIsActive": {"spellId": {"spellId": 99999}}},
            }
        },
        {
            "action": {
                "useItem": {"itemId": 12662},
                "condition": {"auraIsActive": {"auraId": {"spellId": 12662}}},
            }
        },
        {
            "action": {
                "autocastOtherCooldowns": {},
                "condition": {"dotIsActive": {"spellId": {"spellId": 11689}}},
            }
        },
    ]
    _, same_spell, allowed_casts, compatible = _corpus(source_actions)
    compatible_shapes = {
        json.dumps(_predicate_shape(predicate), sort_keys=True, separators=(",", ":"))
        for predicate in compatible
    }
    same_shapes = {
        key: {
            json.dumps(_predicate_shape(predicate), sort_keys=True, separators=(",", ":"))
            for predicate in predicates
        }
        for key, predicates in same_spell.items()
    }

    for seed in range(128):
        for cold in (True, False):
            generated = mutate_apl(
                None if cold else source_actions,
                source_actions,
                random.Random(seed),
                cold=cold,
            )
            for item in generated:
                action = item.get("action", {})
                cast = action.get("castSpell")
                condition = action.get("condition")
                if not isinstance(cast, dict) or condition is None:
                    continue
                key = json.dumps(cast.get("spellId"), sort_keys=True, separators=(",", ":"))
                observed = json.dumps(_predicate_shape(condition),
                                      sort_keys=True, separators=(",", ":"))
                if observed not in same_shapes.get(key, set()):
                    assert observed in compatible_shapes
                    refs, valid = _condition_spell_identity_keys(condition)
                    assert valid and set(refs) <= allowed_casts


class TestAPLPredicateCompatibilityContracts(unittest.TestCase):
    @staticmethod
    def cast(spell_id, condition):
        return {
            "action": {
                "castSpell": {"spellId": {"spellId": spell_id}},
                "condition": condition,
            }
        }

    @staticmethod
    def aura_condition(spell_id):
        return {"auraIsActive": {"auraId": {"spellId": spell_id}}}

    def test_only_compatible_source_cast_predicates_enter_the_shared_pool(self):
        own = self.aura_condition(11689)
        cross = {
            "and": {"vals": [
                self.aura_condition(1311680),
                {"dotIsActive": {"spellId": {"spellId": 11689}}},
            ]}
        }
        unknown = {"dotIsActive": {"spellId": {"spellId": 99999}}}
        item_condition = self.aura_condition(12662)
        opaque_condition = {"dotIsActive": {"spellId": {"spellId": 12662}}}
        source_actions = [
            self.cast(11689, own),
            self.cast(1311680, cross),
            self.cast(25311, unknown),
            {
                "action": {
                    "useItem": {"itemId": 12662},
                    "condition": item_condition,
                }
            },
            {
                "action": {
                    "autocastOtherCooldowns": {},
                    "condition": opaque_condition,
                }
            },
        ]

        spells, same_spell, allowed_casts, compatible = _corpus(source_actions)
        spell_11689 = json.dumps({"spellId": 11689}, sort_keys=True, separators=(",", ":"))
        spell_1311680 = json.dumps({"spellId": 1311680}, sort_keys=True, separators=(",", ":"))
        spell_25311 = json.dumps({"spellId": 25311}, sort_keys=True, separators=(",", ":"))

        self.assertEqual(
            {spell_11689, spell_1311680, spell_25311},
            {json.dumps(x, sort_keys=True, separators=(",", ":")) for x in spells},
        )
        self.assertEqual((own,), same_spell[spell_11689])
        self.assertEqual((cross,), same_spell[spell_1311680])
        self.assertEqual((), same_spell[spell_25311])
        self.assertEqual((own, cross), compatible)
        self.assertNotIn(item_condition, compatible)
        self.assertNotIn(opaque_condition, compatible)
        self.assertNotIn(unknown, compatible)

        for predicate in compatible:
            refs, valid = _condition_spell_identity_keys(predicate)
            self.assertTrue(valid)
            self.assertTrue(set(refs) <= {spell_11689, spell_1311680, spell_25311})

    def test_same_spell_is_preferred_but_compatible_cross_spell_predicates_remain_eligible(self):
        own = self.aura_condition(11689)
        cross = self.aura_condition(1311680)
        source_actions = [
            self.cast(11689, own),
            self.cast(1311680, cross),
        ]
        _spells, same_spell, _allowed, compatible = _corpus(source_actions)

        same_count = 0
        cross_count = 0
        for seed in range(512):
            generated = _new_cast(
                [{"spellId": 11689}], same_spell, compatible, random.Random(seed)
            )
            condition = generated["action"].get("condition")
            if condition == own:
                same_count += 1
            elif condition == cross:
                cross_count += 1
            elif condition is not None:
                self.fail(f"Generated an unobserved predicate: {condition}")

        self.assertGreater(cross_count, 0, "Compatible cross-spell predicates must remain eligible")
        self.assertGreater(same_count, cross_count, "Same-spell predicates must remain preferred")


def test_native_damage_fallback_composes_with_cross_spell_compatible_predicates():
    source_actions = [
        {
            "action": {
                "castSpell": {"spellId": {"spellId": 11689}},
                "condition": {"auraIsActive": {"auraId": {"spellId": 11689}}},
            }
        },
        {
            "action": {
                "castSpell": {"spellId": {"spellId": 11713}},
                "condition": {"dotIsActive": {"spellId": {"spellId": 11689}}},
            }
        },
        {
            "action": {
                "useItem": {"itemId": 12662},
                "condition": {"auraIsActive": {"auraId": {"spellId": 12662}}},
            }
        },
    ]
    source_snapshot = json.loads(json.dumps(source_actions))
    baseline = {
        "result": {
            "raidMetrics": {
                "parties": [{
                    "players": [{
                        "actions": [
                            {"id": {"spellId": 11689}, "targets": [{"casts": 80}]},
                            {"id": {"spellId": 11713},
                             "targets": [{"casts": 10, "damage": 800.0}]},
                        ]
                    }]
                }]
            }
        }
    }
    witnesses = _native_positive_source_casts(source_actions, baseline)
    assert witnesses == [{"spellId": 11713}]
    _spells, same_spell, allowed_casts, compatible = _corpus(source_actions)
    assert source_actions[1]["action"]["condition"] in compatible

    compatible_shapes = {
        json.dumps(_predicate_shape(predicate), sort_keys=True, separators=(",", ":"))
        for predicate in compatible
    }
    same_shapes = {
        key: {
            json.dumps(_predicate_shape(predicate), sort_keys=True, separators=(",", ":"))
            for predicate in predicates
        }
        for key, predicates in same_spell.items()
    }

    for seed in range(128):
        for cold in (True, False):
            proposal = mutate_apl(
                None if cold else source_actions,
                source_actions,
                random.Random(seed),
                cold=cold,
            )
            prefix = [
                entry for entry in proposal
                if "condition" in entry.get("action", {})
                or "castSpell" not in entry.get("action", {})
            ]
            anchored = _ensure_native_damage_action(
                proposal, witnesses, random.Random(seed + 2000)
            )
            assert anchored[:len(prefix)] == prefix
            fallback = anchored[len(prefix)]["action"]
            assert fallback["castSpell"]["spellId"] == {"spellId": 11713}
            assert "condition" not in fallback
            assert all(
                "castSpell" in entry.get("action", {})
                and "condition" not in entry.get("action", {})
                for entry in anchored[len(prefix) + 1:]
            )

            for entry in anchored:
                action = entry.get("action", {})
                cast = action.get("castSpell")
                condition = action.get("condition")
                if not isinstance(cast, dict) or condition is None:
                    continue
                key = json.dumps(cast.get("spellId"), sort_keys=True, separators=(",", ":"))
                observed = json.dumps(_predicate_shape(condition), sort_keys=True, separators=(",", ":"))
                if observed not in same_shapes.get(key, set()):
                    assert observed in compatible_shapes
                    refs, valid = _condition_spell_identity_keys(condition)
                    assert valid and set(refs) <= allowed_casts
            assert source_actions == source_snapshot
