from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from .catalogue import ItemRecord, RequiredLevelOrigin, extract_wowhead_item_id, legacy_item_id


def _pick(data: dict[str, Any], *names: str, default: Any = 0.0) -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return default


def legacy_row_to_item(row: Any, *, namespace: str, default_slot: str = "") -> ItemRecord:
    """Losslessly normalize the currently hard-coded item dataclasses.

    This is deliberately permissive: I1 is a migration shell, not an upstream
    parser. Unknown numeric fields are retained in ``extra_stats``.
    """
    data = asdict(row) if is_dataclass(row) else dict(row)
    name = str(data.get("name", ""))
    source_url = str(data.get("source_url", "") or "")
    upstream_id = extract_wowhead_item_id(source_url)
    item_id = upstream_id if upstream_id is not None else legacy_item_id(name=name, source_url=source_url, namespace=namespace)

    required_level = data.get("required_level")
    if required_level is None and "effective_level" in data:
        required_level = data.get("effective_level")

    known = {
        "name", "slot", "item_level", "required_level", "quality", "armor_type", "weapon_type",
        "weapon_hands", "weapon_min_damage", "weapon_max_damage", "weapon_speed", "weapon_dps",
        "armor", "bonus_armor", "strength", "agility", "stamina", "intellect", "spirit",
        "attack_power", "spell_power", "spell_damage", "healing", "mp5", "spell_hit", "spell_crit",
        "hit", "crit", "defense", "dodge", "source_type", "source", "source_name", "source_url",
        "profession", "family", "quest_min_level", "quest_gray_level", "note", "damage_power",
    }
    extra_stats: dict[str, float] = {}
    for key, value in data.items():
        if key in known or not isinstance(value, (int, float)):
            continue
        extra_stats[key] = float(value)

    return ItemRecord(
        item_id=item_id,
        name=name,
        slot=str(data.get("slot", default_slot) or default_slot),
        item_level=int(data["item_level"]) if data.get("item_level") is not None else None,
        required_level=int(required_level) if required_level is not None else None,
        required_level_origin=RequiredLevelOrigin.OBSERVED.value if required_level is not None else RequiredLevelOrigin.INFERRED_INTERPOLATED.value,
        quality=data.get("quality"),
        armor_type=str(data.get("armor_type", "") or ""),
        weapon_type=str(data.get("weapon_type", "") or ""),
        weapon_hands=int(data.get("weapon_hands", 0) or 0),
        weapon_min_damage=float(data.get("weapon_min_damage", 0.0) or 0.0),
        weapon_max_damage=float(data.get("weapon_max_damage", 0.0) or 0.0),
        weapon_speed=float(data.get("weapon_speed", 0.0) or 0.0),
        weapon_dps=float(data.get("weapon_dps", data.get("wand_dps", 0.0)) or 0.0),
        armor=float(data.get("armor", 0.0) or 0.0),
        bonus_armor=float(data.get("bonus_armor", 0.0) or 0.0),
        strength=float(data.get("strength", 0.0) or 0.0),
        agility=float(data.get("agility", 0.0) or 0.0),
        stamina=float(data.get("stamina", 0.0) or 0.0),
        intellect=float(data.get("intellect", 0.0) or 0.0),
        spirit=float(data.get("spirit", 0.0) or 0.0),
        attack_power=float(data.get("attack_power", 0.0) or 0.0),
        spell_power=float(_pick(data, "spell_power", "spell_damage", default=0.0) or 0.0),
        healing=float(data.get("healing", 0.0) or 0.0),
        mp5=float(data.get("mp5", 0.0) or 0.0),
        hit=float(_pick(data, "hit", "spell_hit", default=0.0) or 0.0),
        crit=float(_pick(data, "crit", "spell_crit", default=0.0) or 0.0),
        defense=float(data.get("defense", 0.0) or 0.0),
        dodge=float(data.get("dodge", 0.0) or 0.0),
        source_type=str(data.get("source_type", data.get("profession", "")) or ""),
        source_name=str(data.get("source_name", data.get("source", data.get("family", ""))) or ""),
        source_url=source_url,
        identity_origin="wowhead_item" if upstream_id is not None else "legacy_synthetic",
        fetch_status="legacy_cached",
        extra_stats=extra_stats,
    )


def migrate_legacy_rows(rows: Iterable[Any], *, namespace: str, default_slot: str = "") -> list[ItemRecord]:
    return [legacy_row_to_item(row, namespace=namespace, default_slot=default_slot) for row in rows]
