"""Thin P3 item-option transport for the selected MythicSim Rust binary.

Native Rust owns all item, level, class, slot and equip eligibility. This
module only invokes its read-only CLI and preserves returned candidates;
it never consults Forever's SQLite item catalogue or infers legality.
"""
from __future__ import annotations

import json
import math
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Callable


class NativeItemOptionsError(ValueError):
    """Native item-options was unavailable or returned an unusable response."""


def query_native_p3_item_options(
    binary: str | Path, class_key: str, level: int, *,
    spec: str = "unrestricted", slot: str = "all",
    runner: Callable = subprocess.run,
) -> dict:
    """Forward a query unchanged; never infer legality or fall back to SQLite."""
    command = [str(binary), "item-options", "--class", str(class_key),
               "--level", str(int(level)), "--spec", spec, "--slot", slot]
    try:
        completed = runner(command, capture_output=True, text=True,
                           timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_EXECUTION_FAILED") from exc
    if completed.returncode != 0:
        raise NativeItemOptionsError(
            "P3_NATIVE_ITEM_OPTIONS_EXECUTION_FAILED:" +
            str(completed.stderr or "").strip()[-500:])
    try:
        response = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_INVALID_JSON") from exc
    if not isinstance(response, dict):
        raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_INVALID_RESPONSE")
    if (response.get("class") != str(class_key).lower()
            or type(response.get("level")) is not int
            or response["level"] != int(level)
            or response.get("spec") != spec
            or response.get("slot") != slot):
        raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_REQUEST_MISMATCH")
    status = response.get("status")
    if status == "refused":
        refusal = response.get("refusal") or {}
        code = refusal.get("code") if isinstance(refusal, dict) else None
        raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_REFUSED:" + str(code or "UNKNOWN"))
    if response.get("required_level_supported") is not True:
        raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_LEVEL_SOURCE_UNAVAILABLE")
    unverified_count = response.get("unverified_candidate_count")
    if type(unverified_count) is not int or unverified_count < 0:
        raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_INVALID_UNVERIFIED_COUNT")
    if str(class_key).lower() == "shaman" and "excluded_non_client_item_count" not in response:
        raise NativeItemOptionsError(
            "P3_NATIVE_ITEM_OPTIONS_EXCLUDED_NON_CLIENT_COUNT_UNAVAILABLE")
    excluded_count = response.get("excluded_non_client_item_count", 0)
    if type(excluded_count) is not int or excluded_count < 0:
        raise NativeItemOptionsError(
            "P3_NATIVE_ITEM_OPTIONS_INVALID_EXCLUDED_NON_CLIENT_COUNT")
    if status == "partial_level_unknown":
        if unverified_count == 0:
            raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_STATUS_COUNT_MISMATCH")
    elif unverified_count != 0:
        raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_STATUS_COUNT_MISMATCH")
    if status not in ("ok", "empty", "partial_level_unknown") or not isinstance(response.get("items"), list):
        raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_INVALID_RESPONSE")
    if ((status == "empty" and response["items"])
            or (status == "ok" and not response["items"])):
        raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_STATUS_COUNT_MISMATCH")
    for item in response["items"]:
        if (not isinstance(item, dict) or type(item.get("item_id")) is not int
                or not isinstance(item.get("stats"), dict)
                or type(item.get("required_level")) is not int
                or type(item.get("item_level")) not in (int, type(None))
                or not isinstance(item.get("slot"), str)):
            raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_INVALID_ITEM_SHAPE")
    return response


def _native_mage_spellbook_request() -> dict:
    """Minimal prepare request; only the native Mage spellbook is consumed."""
    return {
        "encounter": {
            "duration": 60,
            "targets": [{
                "canCrush": True,
                "damageSpread": 0.3333,
                "id": 213336,
                "level": 63,
                "minBaseDamage": 3000.0,
                "name": "Native Mage spellbook probe",
                "parryHaste": True,
                "stats": [0.0] * 41,
                "swingSpeed": 2.0,
            }],
        },
        "raid": {
            "parties": [{
                "players": [{
                    "class": "ClassMage",
                    "name": "native-mage-spellbook",
                    "race": "RaceGnome",
                    "talentsString": "0-0-0",
                    "mage": {"options": {"classOptions": {
                        "defaultMageArmor": "MageArmorMageArmor",
                    }}},
                    "equipment": {"items": []},
                    "rotation": {
                        "type": "TypeAPL",
                        "priorityList": [{
                            "action": {
                                "castSpell": {
                                    "spellId": {"spellId": 8401},
                                },
                            },
                        }],
                    },
                }],
            }],
        },
        "simOptions": {"iterations": 1, "randomSeed": "42"},
    }


def _native_shaman_spellbook_request() -> dict:
    """Prepare only a Shaman spellbook; do not use the L60 actor's stats."""
    request = _native_mage_spellbook_request()
    player = request["raid"]["parties"][0]["players"][0]
    player.pop("mage")
    player.update({
        "class": "ClassShaman",
        "name": "native-shaman-spellbook",
        "race": "RaceOrc",
        "elementalShaman": {"options": {"classOptions": {}}},
        "rotation": {
            "type": "TypeAPL",
            "priorityList": [{
                "action": {"castSpell": {"spellId": {"spellId": 915}}},
            }],
        },
    })
    return request


def _query_native_spell_coefficients(
    binary: str | Path, *, request: dict, class_key: str,
    runner: Callable = subprocess.run,
) -> dict:
    """Transport native PreparedV2 spell facts, never L60 actor stats.

    Rank IDs must be matched to already-sourced actions at the P3 caller;
    preparation alone is not a character-level or stat-weight witness.
    """
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=True
        ) as handle:
            json.dump(request, handle)
            handle.flush()
            completed = runner(
                [str(binary), "prepare", "--request", handle.name],
                capture_output=True, text=True, timeout=60, check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_EXECUTION_FAILED") from exc
    if completed.returncode != 0:
        details = str(completed.stderr or "").strip()
        try:
            failure = json.loads(completed.stdout)
        except (ValueError, TypeError):
            failure = None
        if isinstance(failure, dict):
            refusal = failure.get("refusal")
            if isinstance(refusal, dict):
                code = str(refusal.get("code") or "UNKNOWN")
                reason = str(refusal.get("reason") or "")
                details = f"{code}:{reason}".strip(":")
            elif not details:
                details = json.dumps(failure, sort_keys=True)
        if not details:
            details = str(completed.stdout or "").strip()
        raise NativeItemOptionsError(
            "P3_NATIVE_SPELLBOOK_PREPARE_FAILED:" + details[-500:])
    try:
        prepared = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_INVALID_JSON") from exc
    if (not isinstance(prepared, dict)
            or prepared.get("contract") != "forever-prepared"
            or prepared.get("schema_version") != 2):
        raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_INVALID_PREPARED_V2")
    player = prepared.get("player")
    if (not isinstance(player, dict)
            or str(player.get("class") or "").lower().removeprefix("class") != class_key):
        raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_CLASS_MISMATCH")
    spells = player.get("spells")
    if not isinstance(spells, list):
        raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_SPELLS_UNAVAILABLE")
    coefficients = {}
    for spell in spells:
        if not isinstance(spell, dict):
            continue
        action_id = spell.get("action_id")
        spell_id = action_id.get("spell_id") if isinstance(action_id, dict) else None
        coefficient = spell.get("bonus_coefficient")
        if type(spell_id) is not int or type(coefficient) not in (int, float):
            continue
        coefficient = float(coefficient)
        if not math.isfinite(coefficient) or coefficient < 0.0:
            raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_INVALID_COEFFICIENT")
        previous = coefficients.get(spell_id)
        if previous is not None and abs(previous - coefficient) > 1e-9:
            raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_DUPLICATE_COEFFICIENT_CONFLICT")
        coefficients[spell_id] = coefficient
    if not coefficients:
        raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_NO_DAMAGE_COEFFICIENTS")
    reference = prepared.get("reference")
    engine_revision = (
        reference.get("engine_revision") if isinstance(reference, dict) else None)
    if not isinstance(engine_revision, str) or not engine_revision:
        raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_ENGINE_REVISION_UNAVAILABLE")
    return {
        "source": "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS",
        "engine_revision": engine_revision,
        "spell_power_coefficients": coefficients,
    }


def query_native_mage_spell_coefficients(
    binary: str | Path, *, runner: Callable = subprocess.run,
) -> dict:
    """Read the selected native Mage spellbook without consuming L60 stats."""
    return _query_native_spell_coefficients(
        binary, request=_native_mage_spellbook_request(),
        class_key="mage", runner=runner)


def query_native_shaman_spell_coefficients(
    binary: str | Path, *, runner: Callable = subprocess.run,
) -> dict:
    """Read the native Shaman rank-915 coefficient, or refuse explicitly."""
    facts = _query_native_spell_coefficients(
        binary, request=_native_shaman_spellbook_request(),
        class_key="shaman", runner=runner)
    if 915 not in facts["spell_power_coefficients"]:
        raise NativeItemOptionsError(
            "P3_NATIVE_SHAMAN_LIGHTNING_BOLT_915_COEFFICIENT_UNAVAILABLE")
    return facts


def apply_native_mage_spell_coefficients(
    ir, native_facts: dict, *, allowed_action_ids: frozenset[str] | None = None,
):
    """Copy exact native coefficients onto matching existing source-ranked actions.

    This is a field-level native fact transport, not action generation or a
    second legality catalogue. Only actions already present in the source IR
    and carrying the exact native spell ID can be enriched.
    """
    from src.game.model.ir import DamageEffect

    coefficients = native_facts.get("spell_power_coefficients")
    if not isinstance(coefficients, dict):
        raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_COEFFICIENT_MAP_INVALID")
    source = native_facts.get("source")
    engine_revision = native_facts.get("engine_revision")
    if source != "MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS" or not engine_revision:
        raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_PROVENANCE_INVALID")

    updated_actions = []
    applied = []
    resolved_spell_ids = set()
    new_source_facts = list(getattr(ir, "source_facts", ()) or ())
    for action in tuple(getattr(ir, "actions", ()) or ()):
        metadata = dict(getattr(action, "metadata", {}) or {})
        rank_source = metadata.get("rank_source")
        spell_id = rank_source.get("spell_id") if isinstance(rank_source, dict) else None
        if (allowed_action_ids is not None
                and str(getattr(action, "id", "")) not in allowed_action_ids):
            updated_actions.append(action)
            continue
        if type(spell_id) is not int or spell_id not in coefficients:
            updated_actions.append(action)
            continue
        coefficient = float(coefficients[spell_id])
        if not math.isfinite(coefficient) or coefficient < 0.0:
            raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_INVALID_COEFFICIENT")
        effects = []
        has_direct_damage = False
        fact = {
            "authority": "mythicsim_rust_prepared_v2",
            "engine_revision": engine_revision,
            "spell_id": spell_id,
            "field": "bonus_coefficient",
            "value": coefficient,
            "action_id": str(getattr(action, "id", "")),
        }
        for effect in tuple(getattr(action, "effects", ()) or ()):
            if isinstance(effect, DamageEffect):
                current = float(effect.spell_power_coefficient)
                if current > 1e-12 and abs(current - coefficient) > 1e-9:
                    raise NativeItemOptionsError(
                        "P3_NATIVE_SPELL_COEFFICIENT_CONFLICT:" + str(spell_id))
                field_provenance = dict(effect.field_provenance or {})
                existing = tuple(field_provenance.get("spell_power_coefficient", ()) or ())
                if fact not in existing:
                    field_provenance["spell_power_coefficient"] = existing + (fact,)
                effects.append(replace(
                    effect, spell_power_coefficient=coefficient,
                    field_provenance=field_provenance))
                has_direct_damage = True
            else:
                effects.append(effect)
        if not has_direct_damage:
            updated_actions.append(action)
            continue
        metadata["native_spell_power_coefficient_verified"] = True
        metadata["native_spell_power_coefficient"] = coefficient
        metadata["native_spell_power_coefficient_engine_revision"] = engine_revision
        provenance = tuple(getattr(action, "provenance", ()) or ())
        if fact not in provenance:
            provenance = provenance + (fact,)
        updated_actions.append(replace(
            action, effects=tuple(effects), metadata=metadata, provenance=provenance))
        applied.append({
            "action_id": str(getattr(action, "id", "")),
            "spell_id": spell_id,
            "spell_power_coefficient": coefficient,
        })
        resolved_spell_ids.add(spell_id)
        new_source_facts.append(fact)

    if not applied:
        raise NativeItemOptionsError("P3_NATIVE_SPELLBOOK_NO_MATCHING_SOURCE_ACTION")
    unsupported = tuple(
        blocker for blocker in tuple(getattr(ir, "unsupported_semantics", ()) or ())
        if not (
            isinstance(blocker, dict)
            and blocker.get("code") == "source_rank_spell_power_coefficient_unverified"
            and blocker.get("spell_id") in resolved_spell_ids
        )
    )
    enriched = replace(
        ir, actions=tuple(updated_actions), source_facts=tuple(new_source_facts),
        unsupported_semantics=unsupported,
    )
    return enriched, applied


def apply_native_shaman_lightning_bolt_coefficient(ir, native_facts: dict):
    """Enrich only the already-sourced lightning_bolt:915 rank from native."""
    coefficients = native_facts.get("spell_power_coefficients")
    if not isinstance(coefficients, dict) or 915 not in coefficients:
        raise NativeItemOptionsError(
            "P3_NATIVE_SHAMAN_LIGHTNING_BOLT_915_COEFFICIENT_UNAVAILABLE")
    exact = dict(native_facts)
    exact["spell_power_coefficients"] = {915: coefficients[915]}
    try:
        enriched, applied = apply_native_mage_spell_coefficients(
            ir, exact, allowed_action_ids=frozenset({"lightning_bolt:915"}))
    except NativeItemOptionsError as exc:
        if str(exc) == "P3_NATIVE_SPELLBOOK_NO_MATCHING_SOURCE_ACTION":
            raise NativeItemOptionsError(
                "P3_NATIVE_SHAMAN_LIGHTNING_BOLT_915_SOURCE_RANK_MISMATCH") from exc
        raise
    if len(applied) != 1 or applied[0]["action_id"] != "lightning_bolt:915":
        raise NativeItemOptionsError(
            "P3_NATIVE_SHAMAN_LIGHTNING_BOLT_915_SOURCE_RANK_MISMATCH")
    return enriched, applied


# Only unit-preserving source fields. Native rating and pseudo-stat units
# must not be silently converted into legacy listview chance units.
_DIRECT_SCORE_FIELDS = {
    "Strength": "strength", "Agility": "agility", "Stamina": "stamina",
    "Intellect": "intellect", "Spirit": "spirit",
    "AttackPower": "attack_power", "SpellDamage": "spell_power",
    "HealingPower": "healing", "MP5": "mp5",
    "Armor": "armor", "BonusArmor": "bonus_armor",
}


def native_p3_item_records(binary: str | Path, class_key: str, level: int,
                           *, runner: Callable = subprocess.run):
    """Project Rust items into the existing scorer's shape.

    Return (records, unmapped_by_item, source_metadata). Nonzero unmapped
    source axes become explicit P3 blockers instead of invented scorer
    evidence. The candidate set itself is never filtered by Python.
    """
    from src.rulesets.forever.items.catalogue import ItemRecord

    response = query_native_p3_item_options(binary, class_key, level, runner=runner)
    records = []
    unmapped_by_item = {}
    for option in response["items"]:
        fields = {}
        unmapped = {}
        for name, amount in option["stats"].items():
            if type(amount) not in (int, float):
                raise NativeItemOptionsError("P3_NATIVE_ITEM_OPTIONS_INVALID_STAT_VALUE")
            if name in _DIRECT_SCORE_FIELDS:
                target = _DIRECT_SCORE_FIELDS[name]
                fields[target] = fields.get(target, 0.0) + float(amount)
            elif amount != 0:
                unmapped[name] = float(amount)
        if option.get("pseudo_stats") and any(float(x) != 0 for x in option["pseudo_stats"]):
            unmapped["PseudoStats"] = 1.0
        ranged_type = str(option.get("ranged_weapon_type") or "")
        weapon_type = str(option.get("weapon_type") or "")
        if ranged_type == "RangedWeaponTypeWand":
            weapon_name = "wand"
        elif weapon_type.startswith("WeaponType"):
            weapon_name = weapon_type.removeprefix("WeaponType").lower()
        else:
            weapon_name = ""
        hand_type = str(option.get("hand_type") or "")
        min_damage = float(option.get("weapon_damage_min") or 0.0)
        max_damage = float(option.get("weapon_damage_max") or 0.0)
        speed = float(option.get("weapon_speed") or 0.0)
        if (min_damage or max_damage) and speed <= 0:
            unmapped["WeaponDamageWithoutSpeed"] = 1.0
        weapon_dps = (min_damage + max_damage) / (2.0 * speed) if speed > 0 else 0.0
        item_id = option["item_id"]
        records.append(ItemRecord(
            item_id=item_id, name=str(option.get("name") or ""),
            slot=option["slot"], item_level=option["item_level"],
            required_level=option["required_level"],
            required_level_origin=str(option.get("required_level_origin") or ""),
            weapon_type=weapon_name,
            weapon_hands=2 if hand_type == "HandTypeTwoHand" else (1 if hand_type else 0),
            weapon_min_damage=min_damage, weapon_max_damage=max_damage,
            weapon_speed=speed, weapon_dps=weapon_dps,
            identity_origin="mythicsim_native", source_type="mythicsim_native",
            **fields,
        ))
        if unmapped:
            unmapped_by_item[item_id] = tuple(sorted(unmapped))
    return tuple(records), unmapped_by_item, {
        "status": response["status"],
        "unverified_candidate_count": response["unverified_candidate_count"],
        "excluded_non_client_item_count": response.get("excluded_non_client_item_count", 0),
        "source": response.get("source"),
    }
