"""Cold APL length and native-damage fallback must preserve source-compatible predicates."""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apl_mutation import _condition_spell_identity_keys, _corpus, mutate_apl
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


def _shape_set(predicates):
    return {
        json.dumps(_predicate_shape(predicate), sort_keys=True, separators=(",", ":"))
        for predicate in predicates
    }


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

    source_spells, same_spell, allowed_casts, source_predicates = _corpus(source_actions)
    source_spell_keys = {
        json.dumps(spell, sort_keys=True, separators=(",", ":"))
        for spell in source_spells
    }
    historical_casts = {
        json.dumps(action["action"]["castSpell"]["spellId"],
                   sort_keys=True, separators=(",", ":"))
        for action in historical_actions
        if isinstance(action.get("action", {}).get("castSpell"), dict)
    }
    assert historical_casts <= allowed_casts

    source_shapes = _shape_set(source_predicates)
    historical_compatible_shapes = set()
    historical_compatible_count = 0
    historical_cross_cast_shapes = set()
    historical_cross_cast_count = 0
    for action in historical_actions:
        action_body = action.get("action", {})
        condition = action_body.get("condition")
        cast = action_body.get("castSpell", {})
        identity = cast.get("spellId") if isinstance(cast, dict) else None
        if not isinstance(condition, dict) or not isinstance(identity, dict):
            continue
        refs, valid = _condition_spell_identity_keys(condition)
        if not valid or not set(refs) <= source_spell_keys:
            continue
        shape = json.dumps(
            _predicate_shape(condition), sort_keys=True, separators=(",", ":")
        )
        historical_compatible_count += 1
        historical_compatible_shapes.add(shape)
        target_key = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        if shape not in _shape_set(same_spell.get(target_key, ())):
            historical_cross_cast_count += 1
            historical_cross_cast_shapes.add(shape)

    # 11/16 historical conditions are source-compatible; 6 are cross-cast,
    # including spell-agnostic predicates. The five conditions referencing
    # aura 408255 are excluded because it is not in the saved source cast set.
    assert historical_compatible_count == 11
    assert historical_cross_cast_count == 6
    assert historical_compatible_shapes <= source_shapes
    assert historical_cross_cast_shapes <= source_shapes

    saved_snapshot = json.loads(json.dumps(source_actions))
    generated = mutate_apl(None, source_actions, random.Random(29), cold=True)
    assert len(generated) >= len(historical_actions)
    assert len(generated) <= 20
    assert source_actions == saved_snapshot


def test_cold_and_elite_cast_conditions_use_only_source_compatible_cast_predicates():
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
    compatible_shapes = _shape_set(compatible)
    assert json.dumps(_predicate_shape(source_actions[-2]["action"]["condition"]),
                      sort_keys=True, separators=(",", ":")) not in compatible_shapes
    assert json.dumps(_predicate_shape(source_actions[-1]["action"]["condition"]),
                      sort_keys=True, separators=(",", ":")) not in compatible_shapes

    same_shapes = {key: _shape_set(predicates) for key, predicates in same_spell.items()}
    cross_cast_seen = False
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
                    cross_cast_seen = True
    assert cross_cast_seen, "Compatible cross-cast predicates must remain eligible"
    assert source_actions == source_snapshot


def test_native_damage_witness_follows_conditional_opaque_prefix_and_precedes_utility_casts():
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
    source_spells, same_spell, _allowed_casts, compatible = _corpus(source_actions)
    source_spell_keys = {
        json.dumps(spell, sort_keys=True, separators=(",", ":"))
        for spell in source_spells
    }
    compatible_shapes = _shape_set(compatible)
    same_shapes = {key: _shape_set(predicates) for key, predicates in same_spell.items()}
    item_shape = json.dumps(
        _predicate_shape(source_actions[-1]["action"]["condition"]),
        sort_keys=True, separators=(",", ":"),
    )
    assert item_shape not in compatible_shapes

    cross_cast_seen = False
    for seed in range(128):
        cold = mutate_apl(None, source_actions, random.Random(seed), cold=True)
        elite = mutate_apl(cold, source_actions, random.Random(seed + 1000))
        for proposal in (cold, elite):
            prefix = [
                entry for entry in proposal
                if not isinstance(entry.get("action", {}).get("castSpell"), dict)
                or "condition" in entry.get("action", {})
            ]
            anchored = _ensure_native_damage_action(
                proposal, witnesses, random.Random(seed)
            )
            assert anchored[:len(prefix)] == prefix
            assert len(anchored) <= 20

            fallback = anchored[len(prefix)]["action"]
            assert fallback["castSpell"]["spellId"] == {"spellId": 11713}
            assert "condition" not in fallback
            assert all(
                isinstance(entry.get("action", {}).get("castSpell"), dict)
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
                refs, valid = _condition_spell_identity_keys(condition)
                assert valid
                assert set(refs) <= source_spell_keys
                shape = json.dumps(
                    _predicate_shape(condition), sort_keys=True, separators=(",", ":")
                )
                assert shape in compatible_shapes
                if shape not in same_shapes.get(key, set()):
                    cross_cast_seen = True
        assert source_actions == source_snapshot
    assert cross_cast_seen
