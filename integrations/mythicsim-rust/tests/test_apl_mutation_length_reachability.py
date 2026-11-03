"""Cold APL length must cover source-legal policies beyond the saved reference length."""
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

    source_spells, same_spell_predicates, allowed_casts, source_predicates, source_aura_keys = _corpus(source_actions)
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

    source_shapes = {
        json.dumps(_predicate_shape(predicate), sort_keys=True, separators=(",", ":"))
        for predicate in source_predicates
    }
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
        spell_refs, aura_refs, valid = _condition_spell_identity_keys(condition)
        if (not valid
                or not set(spell_refs) <= source_spell_keys
                or not set(aura_refs) <= source_aura_keys):
            continue
        shape = json.dumps(
            _predicate_shape(condition), sort_keys=True, separators=(",", ":")
        )
        historical_compatible_count += 1
        historical_compatible_shapes.add(shape)
        target_key = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        same_spell_shapes = {
            json.dumps(_predicate_shape(predicate), sort_keys=True, separators=(",", ":"))
            for predicate in same_spell_predicates.get(target_key, ())
        }
        if shape not in same_spell_shapes:
            historical_cross_cast_count += 1
            historical_cross_cast_shapes.add(shape)

    # Both spellId and auraId references must be exact source cast identities.
    # Preserve the 11 source-compatible historical conditions, including six
    # cross-cast predicates; the five 408255 aura references are not cast-backed.
    assert historical_compatible_count == 16
    assert historical_cross_cast_count == 7
    assert historical_compatible_shapes <= source_shapes
    assert historical_cross_cast_shapes <= source_shapes

    saved_snapshot = json.loads(json.dumps(source_actions))
    generated = mutate_apl(None, source_actions, random.Random(29), cold=True)
    assert len(generated) >= len(historical_actions)
    assert len(generated) <= 20
    assert source_actions == saved_snapshot



def test_cold_and_elite_keep_exact_source_action_condition_pairings():
    # Conditions are part of their source cast action, not a reusable pool.
    # A generated 10463-style aura guard must never be detached, grafted,
    # tuned or dropped while its cast remains in the candidate.
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
    templates_by_spell = {}
    source_noncast = set()
    for entry in source_actions:
        action = entry["action"]
        cast = action.get("castSpell")
        if isinstance(cast, dict):
            key = json.dumps(cast.get("spellId"), sort_keys=True, separators=(",", ":"))
            templates_by_spell.setdefault(key, set()).add(
                json.dumps(action, sort_keys=True, separators=(",", ":"))
            )
        else:
            source_noncast.add(
                json.dumps(action, sort_keys=True, separators=(",", ":"))
            )

    for seed in range(128):
        cold = mutate_apl(None, source_actions, random.Random(seed), cold=True)
        elite = mutate_apl(cold, source_actions, random.Random(seed + 1000))
        for proposal in (cold, elite):
            for entry in proposal:
                action = entry["action"]
                cast = action.get("castSpell")
                if isinstance(cast, dict):
                    key = json.dumps(
                        cast.get("spellId"), sort_keys=True, separators=(",", ":")
                    )
                    assert json.dumps(
                        action, sort_keys=True, separators=(",", ":")
                    ) in templates_by_spell[key], (seed, proposal, action)
                else:
                    assert json.dumps(
                        action, sort_keys=True, separators=(",", ":")
                    ) in source_noncast
    assert source_actions == source_snapshot


def test_native_damage_witness_follows_conditional_opaque_prefix_for_cold_and_elite_apls():
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
    templates_by_spell = {}
    noncast_templates = set()
    for entry in source_actions:
        action = entry["action"]
        cast = action.get("castSpell")
        if isinstance(cast, dict):
            key = json.dumps(cast.get("spellId"), sort_keys=True, separators=(",", ":"))
            templates_by_spell.setdefault(key, set()).add(
                json.dumps(action, sort_keys=True, separators=(",", ":"))
            )
        else:
            noncast_templates.add(
                json.dumps(action, sort_keys=True, separators=(",", ":"))
            )

    for seed in range(128):
        cold = mutate_apl(None, source_actions, random.Random(seed), cold=True)
        elite = mutate_apl(cold, source_actions, random.Random(seed + 1000))
        for proposal in (cold, elite):
            prefix = [
                entry for entry in proposal
                if (
                    not isinstance(entry.get("action", {}).get("castSpell"), dict)
                    or (
                        "condition" in entry.get("action", {})
                        and entry.get("action", {}).get("castSpell", {}).get(
                            "spellId", {}
                        ).get("spellId") != 11713
                    )
                )
            ]
            anchored = _ensure_native_damage_action(
                proposal, witnesses, random.Random(seed),
                source_actions=source_actions,
            )
            assert anchored[:len(prefix)] == prefix
            assert len(anchored) <= 20

            witness_actions = [
                entry for entry in anchored
                if entry.get("action", {}).get("castSpell", {}).get(
                    "spellId", {}
                ).get("spellId") == 11713
            ]
            assert witness_actions
            assert all(
                entry["action"] == source_actions[1]["action"]
                for entry in witness_actions
            )

            for entry in anchored:
                action = entry.get("action", {})
                cast = action.get("castSpell")
                if isinstance(cast, dict):
                    key = json.dumps(
                        cast.get("spellId"), sort_keys=True, separators=(",", ":")
                    )
                    assert json.dumps(
                        action, sort_keys=True, separators=(",", ":")
                    ) in templates_by_spell[key]
                else:
                    assert json.dumps(
                        action, sort_keys=True, separators=(",", ":")
                    ) in noncast_templates
        assert source_actions == source_snapshot
    assert cross_cast_seen
