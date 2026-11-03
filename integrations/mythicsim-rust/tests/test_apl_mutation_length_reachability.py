"""Cold APL length must cover source-legal policies beyond the saved reference length."""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apl_mutation import _corpus, mutate_apl
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

    _, predicates_by_spell, allowed_casts = _corpus(source_actions)
    source_predicates = [
        predicate
        for predicates in predicates_by_spell.values()
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



def test_cold_and_elite_cast_conditions_remain_bound_to_their_source_spell():
    # The old global predicate pool could graft a Life Tap condition onto
    # Curse of Elements (or even a potion condition onto either cast).
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
                "condition": {"auraIsActive": {"auraId": {"spellId": 1311680}}},
            }
        },
        {
            "action": {
                "useItem": {"itemId": 12662},
                "condition": {"auraIsActive": {"auraId": {"spellId": 12662}}},
            }
        },
    ]
    source_conditions = {}
    for item in source_actions:
        action = item["action"]
        cast = action.get("castSpell")
        condition = action.get("condition")
        if isinstance(cast, dict) and isinstance(cast.get("spellId"), dict):
            key = json.dumps(cast["spellId"], sort_keys=True, separators=(",", ":"))
            source_conditions.setdefault(key, set()).add(
                json.dumps(condition, sort_keys=True, separators=(",", ":"))
            )

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
                observed = json.dumps(condition, sort_keys=True, separators=(",", ":"))
                assert observed in source_conditions.get(key, set()), (
                    f"seed={seed}, cold={cold}, spell={key}, condition={observed}"
                )



def test_native_damage_anchor_and_spell_bound_predicates_compose_on_cold_and_elite_apls():
    # A source-paid baseline proves 11713 damages; 11689 is a non-damaging
    # Life Tap cast. The item predicate must never enter either cast's pool.
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
                "condition": {"auraIsActive": {"auraId": {"spellId": 11713}}},
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
    _, predicates_by_spell, _ = _corpus(source_actions)
    assert set(predicates_by_spell) == {
        json.dumps({"spellId": 11689}, sort_keys=True, separators=(",", ":")),
        json.dumps({"spellId": 11713}, sort_keys=True, separators=(",", ":")),
    }

    for seed in range(128):
        cold = mutate_apl(None, source_actions, random.Random(seed), cold=True)
        elite = mutate_apl(cold, source_actions, random.Random(seed + 1000))
        for proposal in (cold, elite):
            anchored = _ensure_native_damage_action(
                proposal, witnesses, random.Random(seed)
            )
            first = anchored[0]["action"]
            assert first["castSpell"]["spellId"] == {"spellId": 11713}
            assert "condition" not in first

            # Every generated cast predicate remains attached to the exact
            # source spell identity; the non-cast item condition is excluded.
            for entry in anchored:
                action = entry.get("action", {})
                cast = action.get("castSpell")
                condition = action.get("condition")
                if not isinstance(cast, dict) or condition is None:
                    continue
                key = json.dumps(
                    cast.get("spellId"), sort_keys=True, separators=(",", ":")
                )
                observed = json.dumps(
                    condition, sort_keys=True, separators=(",", ":")
                )
                allowed = {
                    json.dumps(item, sort_keys=True, separators=(",", ":"))
                    for item in predicates_by_spell.get(key, ())
                }
                assert observed in allowed, (seed, key, observed)
        assert source_actions == source_snapshot
