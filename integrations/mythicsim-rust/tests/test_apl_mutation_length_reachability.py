"""Cold APL length must cover source-legal policies beyond the saved reference length."""
import copy
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apl_mutation import _corpus, mutate_apl


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

    # The high-scoring historical APL is only an identity/predicate-vocabulary
    # and length witness. Its old spell/predicate pairings are not admitted by
    # the current generator. The generator receives only the saved request.
    assert len(source_actions) == 10
    assert len(historical_actions) == 19

    source_casts, source_by_identity, allowed_casts = _corpus(source_actions)
    source_predicates = [
        entry["action"]["condition"] for entry in source_actions
        if isinstance(entry.get("action", {}).get("condition"), dict)
        and entry["action"]["condition"]
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



def _spell_pair(entry):
    action = entry.get("action", {})
    spell = action.get("castSpell", {}).get("spellId")
    if not isinstance(spell, dict) or not isinstance(spell.get("spellId"), int):
        return None
    condition = action.get("condition")
    shape = _predicate_shape(condition) if isinstance(condition, dict) and condition else None
    return (
        json.dumps(spell, sort_keys=True, separators=(",", ":")),
        json.dumps(shape, sort_keys=True, separators=(",", ":")) if shape is not None else None,
    )


def _assert_source_spell_condition_pairs(candidate, source_actions):
    source_pairs = {
        pair for entry in source_actions if (pair := _spell_pair(entry)) is not None
    }
    for entry in candidate:
        pair = _spell_pair(entry)
        if pair is not None:
            assert pair in source_pairs, f"cross-wired spell/predicate pair: {pair}"


def _rogue_source_actions():
    return [
        {"action": {
            "castSpell": {"spellId": {"spellId": 1856}},
            "condition": {"not": {"val": {"auraIsActive": {
                "auraId": {"spellId": 1784}
            }}}},
        }},
        {"action": {
            "castSpell": {"spellId": {"spellId": 11269}},
            "condition": {"auraIsActive": {"auraId": {"spellId": 1784}}},
        }},
        {"action": {"castSpell": {"spellId": {"spellId": 25300}}}},
    ]


def _warlock_source_actions():
    return [
        {"action": {
            "castSpell": {"spellId": {"spellId": 11689}},
            "condition": {"cmp": {
                "lhs": {"currentManaPercent": {}}, "op": "OpLt",
                "rhs": {"const": {"val": "10%"}},
            }},
        }},
        {"action": {
            "castSpell": {"spellId": {"spellId": 1311680}},
            "condition": {"not": {"val": {"auraIsActive": {
                "auraId": {"spellId": 1311680},
                "sourceUnit": {"type": "CurrentTarget"},
            }}}},
        }},
        {"action": {"castSpell": {"spellId": {"spellId": 25307}}}},
    ]


def test_cold_and_elite_mutations_never_crosswire_spell_conditions():
    # These are the exact identities implicated by the seven zero-DPS receipts:
    # Rogue Vanish/Stealth and Warlock Life Tap/Curse of Elements.
    for source_actions in (_rogue_source_actions(), _warlock_source_actions()):
        for seed in range(128):
            cold = mutate_apl(None, source_actions, random.Random(seed), cold=True)
            _assert_source_spell_condition_pairs(cold, source_actions)
            elite = mutate_apl(
                copy.deepcopy(source_actions), source_actions, random.Random(seed),
                cold=False,
            )
            _assert_source_spell_condition_pairs(elite, source_actions)


def test_cold_generation_keeps_the_last_source_unconditional_spell_as_fallback():
    for source_actions, fallback_id in (
        (_rogue_source_actions(), 25300),
        (_warlock_source_actions(), 25307),
    ):
        for seed in range(64):
            generated = mutate_apl(None, source_actions, random.Random(seed), cold=True)
            assert any(
                entry.get("action", {}).get("castSpell", {}).get("spellId", {}).get("spellId") == fallback_id
                and "condition" not in entry.get("action", {})
                for entry in generated
            )


def test_saved_druid_source_candidates_keep_spell_condition_pairs():
    repo = ROOT.parent.parent
    reference = json.loads(
        (repo / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json").read_text()
    )
    source_actions = reference["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
    for seed in range(64):
        generated = mutate_apl(None, source_actions, random.Random(seed), cold=True)
        _assert_source_spell_condition_pairs(generated, source_actions)
