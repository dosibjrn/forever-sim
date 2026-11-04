"""Thin P3 item-option transport for the selected MythicSim Rust binary.

Native Rust owns all item, level, class, slot and equip eligibility. This
module only invokes its read-only CLI and preserves returned candidates;
it never consults Forever's SQLite item catalogue or infers legality.
"""
from __future__ import annotations

import json
import subprocess
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
        "source": response.get("source"),
    }
