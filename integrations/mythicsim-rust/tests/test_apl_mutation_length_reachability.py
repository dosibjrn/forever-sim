"""Cold APL length must cover source-legal policies beyond the saved reference length."""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apl_mutation import _condition_spell_identity_keys, _corpus, mutate_apl


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

    _, _same_spell_predicates, allowed_casts, source_predicates = _corpus(source_actions)
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
    historical_shapes = {
        json.dumps(_predicate_shape(action["action"]["condition"]),
                   sort_keys=True, separators=(",", ":"))
        for action in historical_actions
        if isinstance(action.get("action", {}).get("condition"), dict)
    }
    assert historical_shapes <= source_shapes

    saved_snapshot = json.loads(json.dumps(source_actions))
    generated = mutate_apl(None, source_actions, random.Random(29), cold=True)
    assert len(generated) >= len(historical_actions)
    assert len(generated) <= 20
    assert source_actions == saved_snapshot



def test_cold_and_elite_cast_conditions_remain_bound_to_source_spell_set():
    # Same-spell predicates are preferred, but compatible source-cast
    # predicates may cross between casts when every exact spell reference
    # belongs to the source cast set. useItem/opaque predicates are excluded.
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
                "condition": {"dotIsActive": {"spellId": {"spellId": 12662}}},
            }
        },
    ]
    source_snapshot = json.loads(json.dumps(source_actions))
    spells, same_spell, _allowed_casts, compatible = _corpus(source_actions)
    source_spell_keys = {
        json.dumps(spell, sort_keys=True, separators=(",", ":"))
        for spell in spells
    }
    compatible_shapes = {
        json.dumps(_predicate_shape(predicate), sort_keys=True, separators=(",", ":"))
        for predicate in compatible
    }
    item_shape = json.dumps(
        _predicate_shape(source_actions[-2]["action"]["condition"]),
        sort_keys=True, separators=(",", ":"),
    )
    opaque_shape = json.dumps(
        _predicate_shape(source_actions[-1]["action"]["condition"]),
        sort_keys=True, separators=(",", ":"),
    )
    assert item_shape not in compatible_shapes
    assert opaque_shape not in compatible_shapes

    same_shapes = {
        key: {
            json.dumps(_predicate_shape(predicate), sort_keys=True, separators=(",", ":"))
            for predicate in predicates
        }
        for key, predicates in same_spell.items()
    }
    cross_spell_seen = False
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
                refs, valid = _condition_spell_identity_keys(condition)
                assert valid, (seed, cold, condition)
                assert set(refs) <= source_spell_keys, (seed, cold, key, refs)
                shape = json.dumps(
                    _predicate_shape(condition), sort_keys=True, separators=(",", ":")
                )
                assert shape in compatible_shapes, (seed, cold, key, shape)
                if shape not in same_shapes.get(key, set()):
                    cross_spell_seen = True
    assert cross_spell_seen, "Compatible cross-spell predicates must remain eligible"
    assert source_actions == source_snapshot
