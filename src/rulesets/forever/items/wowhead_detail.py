from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable

from .catalogue import ItemCatalogue, ItemRecord, RequiredLevelOrigin


_JSON_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/(?:ld\+)?json["\'][^>]*>(?P<body>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title[^>]*>(?P<body>.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_ITEM_ID_RE = re.compile(r"/item=(\d+)(?:/|$)")
_REQ_TEXT_RE = re.compile(r"Requires\s+Level\s+(\d+)", re.IGNORECASE)
_ILVL_TEXT_RE = re.compile(r"Item\s+Level\s+(\d+)", re.IGNORECASE)
_ARMOR_TEXT_RE = re.compile(r"([\d,.]+)\s+Armor\b", re.IGNORECASE)
_STAT_TEXT_PATTERNS = {
    "strength": re.compile(r"\+(\d+(?:\.\d+)?)\s+Strength\b", re.IGNORECASE),
    "agility": re.compile(r"\+(\d+(?:\.\d+)?)\s+Agility\b", re.IGNORECASE),
    "stamina": re.compile(r"\+(\d+(?:\.\d+)?)\s+Stamina\b", re.IGNORECASE),
    "intellect": re.compile(r"\+(\d+(?:\.\d+)?)\s+Intellect\b", re.IGNORECASE),
    "spirit": re.compile(r"\+(\d+(?:\.\d+)?)\s+Spirit\b", re.IGNORECASE),
}
_HEAL_DAMAGE_TEXT_RE = re.compile(
    r"Increases\s+healing\s+done\s+by\s+up\s+to\s+(\d+(?:\.\d+)?)\s+and\s+damage\s+done\s+by\s+up\s+to\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_SPELL_DAMAGE_TEXT_RE = re.compile(
    r"Increases\s+damage(?:\s+and\s+healing)?\s+done\s+by\s+magical\s+spells(?:\s+and\s+effects)?\s+by\s+up\s+to\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

_SLOT_TEXT = {
    "Head": "head", "Neck": "neck", "Shoulder": "shoulder", "Back": "back",
    "Chest": "chest", "Wrist": "wrist", "Hands": "hands", "Waist": "waist",
    "Legs": "legs", "Feet": "feet", "Finger": "finger", "Trinket": "trinket",
    "Main Hand": "main_hand", "Off Hand": "off_hand", "One-Hand": "one_hand",
    "Two-Hand": "two_hand", "Held In Off-hand": "off_hand", "Ranged": "ranged",
}


@dataclass(frozen=True)
class ParsedWowheadItem:
    item_id: int
    name: str
    slot: str
    item_level: int | None
    required_level: int | None
    quality: int | None = None
    armor_type: str = ""
    weapon_type: str = ""
    weapon_hands: int = 0
    weapon_min_damage: float = 0.0
    weapon_max_damage: float = 0.0
    weapon_speed: float = 0.0
    armor: float = 0.0
    stats: dict[str, float] | None = None
    extra_stats: dict[str, float] | None = None


@dataclass(frozen=True)
class DetailRefreshResult:
    item_id: int
    status: str
    used_cached_values: bool
    message: str = ""


def _walk(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    lowered = {str(k).lower(): v for k, v in mapping.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _clean_text(value: str) -> str:
    return html_lib.unescape(_TAG_RE.sub(" ", value)).replace("\xa0", " ").strip()


def _slot_from_value(value: Any) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    aliases = {
        "head": "head", "neck": "neck", "shoulder": "shoulder", "shoulders": "shoulder",
        "back": "back", "chest": "chest", "wrist": "wrist", "wrists": "wrist",
        "hands": "hands", "waist": "waist", "legs": "legs", "feet": "feet",
        "finger": "finger", "ring": "finger", "trinket": "trinket", "main hand": "main_hand",
        "off hand": "off_hand", "one-hand": "one_hand", "one hand": "one_hand",
        "two-hand": "two_hand", "two hand": "two_hand", "ranged": "ranged",
    }
    return aliases.get(raw.lower(), "")


def parse_wowhead_detail_page(*, item_id: int, raw_html: str) -> ParsedWowheadItem:
    """Parse conservative item facts from captured Wowhead detail HTML.

    The parser prefers explicit JSON objects embedded by the page and falls back
    to visible tooltip text for the small set of core facts needed by the
    catalogue. Unknown fields remain unknown; they are never invented.
    """
    html = str(raw_html)
    if not html.strip():
        raise ValueError("empty Wowhead detail response")

    json_objects: list[dict[str, Any]] = []
    for match in _JSON_SCRIPT_RE.finditer(html):
        try:
            payload = json.loads(match.group("body"))
        except json.JSONDecodeError:
            continue
        json_objects.extend(_walk(payload))

    # Captured/synthetic fixtures may expose a compact canonical object. This is
    # also intentionally compatible with a future local capture normalizer.
    canonical_match = re.search(
        r'<script[^>]+id=["\']wowhead-item-data["\'][^>]*>(?P<body>.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if canonical_match:
        try:
            payload = json.loads(canonical_match.group("body"))
            json_objects.insert(0, payload)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid wowhead-item-data JSON") from exc

    chosen: dict[str, Any] = {}
    for obj in json_objects:
        obj_id = _integer(_first(obj, "item_id", "itemId", "id"))
        has_item_shape = any(
            _first(obj, key) is not None
            for key in ("itemLevel", "item_level", "requiredLevel", "required_level", "slot", "inventoryType")
        )
        if obj_id == int(item_id) and has_item_shape:
            chosen = obj
            break
        if has_item_shape and not chosen:
            chosen = obj

    title_match = _TITLE_RE.search(html)
    title = _clean_text(title_match.group("body")) if title_match else ""
    title = re.sub(r"\s*[-–|]\s*Wowhead.*$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s*[-–|]\s*Item\s*[-–|]\s*Forever\s*$", "", title, flags=re.IGNORECASE).strip()
    name = str(_first(chosen, "name", "itemName") or title or f"Wowhead item {item_id}").strip()

    text = _clean_text(html)
    item_level = _integer(_first(chosen, "itemLevel", "item_level", "level"))
    required_level = _integer(_first(chosen, "requiredLevel", "required_level", "reqLevel", "reqlevel"))
    slot = _slot_from_value(_first(chosen, "slot", "inventoryType", "inventory_type"))
    quality = _integer(_first(chosen, "quality", "qualityId", "quality_id"))
    armor_type = str(_first(chosen, "armorType", "armor_type", "subclass", "subClass") or "").strip().lower()
    weapon_type = str(_first(chosen, "weaponType", "weapon_type") or "").strip().lower()
    weapon_hands = _integer(_first(chosen, "weaponHands", "weapon_hands", "hands")) or 0
    min_damage = _number(_first(chosen, "minDamage", "weapon_min_damage", "dmgMin")) or 0.0
    max_damage = _number(_first(chosen, "maxDamage", "weapon_max_damage", "dmgMax")) or 0.0
    weapon_speed = _number(_first(chosen, "speed", "weaponSpeed", "weapon_speed")) or 0.0
    armor = _number(_first(chosen, "armor", "baseArmor")) or 0.0

    if item_level is None:
        match = _ILVL_TEXT_RE.search(text)
        item_level = int(match.group(1)) if match else None
    if required_level is None:
        match = _REQ_TEXT_RE.search(text)
        required_level = int(match.group(1)) if match else None
    if not slot:
        for visible, normalized in sorted(_SLOT_TEXT.items(), key=lambda kv: -len(kv[0])):
            if re.search(rf"\b{re.escape(visible)}\b", text, re.IGNORECASE):
                slot = normalized
                break
    if not armor_type:
        armor_match = re.search(r"\b(Cloth|Leather|Mail|Plate)\b", text, re.IGNORECASE)
        if armor_match:
            armor_type = armor_match.group(1).lower()
    if armor == 0.0:
        match = _ARMOR_TEXT_RE.search(text)
        armor = float(match.group(1).replace(",", "")) if match else 0.0

    stats_obj = _first(chosen, "stats", "attributes")
    stats: dict[str, float] = {}
    if isinstance(stats_obj, dict):
        aliases = {
            "str": "strength", "strength": "strength", "agi": "agility", "agility": "agility",
            "sta": "stamina", "stamina": "stamina", "int": "intellect", "intellect": "intellect",
            "spi": "spirit", "spirit": "spirit", "attackpower": "attack_power", "attack_power": "attack_power",
            "spellpower": "spell_power", "spell_power": "spell_power", "healing": "healing",
            "mp5": "mp5", "hit": "hit", "crit": "crit", "defense": "defense", "dodge": "dodge",
            "bonusarmor": "bonus_armor", "bonus_armor": "bonus_armor",
        }
        for key, value in stats_obj.items():
            normalized = aliases.get(str(key).replace(" ", "").lower())
            number = _number(value)
            if normalized and number is not None:
                stats[normalized] = number
    for stat, pattern in _STAT_TEXT_PATTERNS.items():
        if stat not in stats:
            match = pattern.search(text)
            if match:
                stats[stat] = float(match.group(1))
    heal_damage = _HEAL_DAMAGE_TEXT_RE.search(text)
    if heal_damage:
        stats.setdefault("healing", float(heal_damage.group(1)))
        stats.setdefault("spell_power", float(heal_damage.group(2)))
    elif "spell_power" not in stats:
        spell_damage = _SPELL_DAMAGE_TEXT_RE.search(text)
        if spell_damage:
            stats["spell_power"] = float(spell_damage.group(1))

    if not name or name.startswith("Wowhead item "):
        raise ValueError("item name missing from Wowhead detail response")
    if item_level is None and required_level is None and not slot and not stats and armor == 0.0:
        raise ValueError("no item facts found in Wowhead detail response")

    return ParsedWowheadItem(
        item_id=int(item_id),
        name=name,
        slot=slot,
        item_level=item_level,
        required_level=required_level,
        quality=quality,
        armor_type=armor_type,
        weapon_type=weapon_type,
        weapon_hands=weapon_hands,
        weapon_min_damage=min_damage,
        weapon_max_damage=max_damage,
        weapon_speed=weapon_speed,
        armor=armor,
        stats=stats,
        extra_stats={},
    )


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def refresh_item_detail(
    catalogue: ItemCatalogue,
    *,
    item_id: int,
    raw_html: str | None = None,
    fetch_error: str | None = None,
    fetched_at: str | None = None,
    source_url: str | None = None,
    commit: bool = True,
) -> DetailRefreshResult:
    """Apply one detail refresh without destroying the last good cached facts."""
    existing = catalogue.get_item(int(item_id))
    if existing is None:
        existing = ItemRecord(
            item_id=int(item_id),
            name=f"Wowhead item {item_id}",
            slot="",
            required_level=None,
            required_level_origin=RequiredLevelOrigin.MISSING.value,
            source_url=source_url or f"https://www.wowhead.com/forever/item={item_id}",
            identity_origin="wowhead_item",
            fetch_status="list_only",
        )
        catalogue.upsert_item(existing, commit=commit)

    error = str(fetch_error or "").strip()
    parsed: ParsedWowheadItem | None = None
    if not error:
        try:
            parsed = parse_wowhead_detail_page(item_id=int(item_id), raw_html=raw_html or "")
        except Exception as exc:  # parser failure is a cache-fallback condition
            error = f"parse error: {exc}"

    if parsed is None:
        has_verified_cache = existing.fetch_status in {"verified", "cached_fallback"} and bool(existing.last_verified_at)
        status = "cached_fallback" if has_verified_cache else "fetch_failed"
        updated = replace(existing, fetch_status=status, last_fetch_error=error or "detail fetch failed")
        catalogue.upsert_item(updated, commit=commit)
        if has_verified_cache:
            message = (
                f"Item {item_id} could not be verified from Wowhead; using locally cached values "
                f"from {existing.last_verified_at}."
            )
        else:
            message = f"Item {item_id} could not be verified from Wowhead and has no verified local cache."
        return DetailRefreshResult(int(item_id), status, has_verified_cache, message)

    timestamp = fetched_at or _iso_now()
    stat = parsed.stats or {}
    fingerprint = hashlib.sha256((raw_html or "").encode("utf-8")).hexdigest()
    req_origin = (
        RequiredLevelOrigin.OBSERVED.value
        if parsed.required_level is not None
        else RequiredLevelOrigin.MISSING.value
    )
    updated = ItemRecord(
        item_id=parsed.item_id,
        name=parsed.name,
        slot=parsed.slot,
        item_level=parsed.item_level,
        required_level=parsed.required_level,
        required_level_origin=req_origin,
        quality=parsed.quality,
        armor_type=parsed.armor_type,
        weapon_type=parsed.weapon_type,
        weapon_hands=parsed.weapon_hands,
        weapon_min_damage=parsed.weapon_min_damage,
        weapon_max_damage=parsed.weapon_max_damage,
        weapon_speed=parsed.weapon_speed,
        weapon_dps=(
            ((parsed.weapon_min_damage + parsed.weapon_max_damage) / 2.0) / parsed.weapon_speed
            if parsed.weapon_speed > 0 else 0.0
        ),
        armor=parsed.armor,
        bonus_armor=stat.get("bonus_armor", 0.0),
        strength=stat.get("strength", 0.0),
        agility=stat.get("agility", 0.0),
        stamina=stat.get("stamina", 0.0),
        intellect=stat.get("intellect", 0.0),
        spirit=stat.get("spirit", 0.0),
        attack_power=stat.get("attack_power", 0.0),
        spell_power=stat.get("spell_power", 0.0),
        healing=stat.get("healing", 0.0),
        mp5=stat.get("mp5", 0.0),
        hit=stat.get("hit", 0.0),
        crit=stat.get("crit", 0.0),
        defense=stat.get("defense", 0.0),
        dodge=stat.get("dodge", 0.0),
        source_type="wowhead_detail",
        source_name="Forever Item",
        source_url=source_url or existing.source_url or f"https://www.wowhead.com/forever/item={item_id}",
        identity_origin="wowhead_item",
        last_verified_at=timestamp,
        fetch_status="verified",
        upstream_fingerprint=fingerprint,
        last_fetch_error="",
        extra_stats=parsed.extra_stats or {},
    )
    catalogue.upsert_item(updated, commit=commit)
    return DetailRefreshResult(int(item_id), "verified", False, "")
