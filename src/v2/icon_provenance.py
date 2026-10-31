from __future__ import annotations

"""Icon/entity provenance for the Decisions listener.

Talent/spell icon keys come from the generated Talents Forever data cache.  No
image bytes live in the repo; the listener uses the cached client icon key with
the Wowhead/Zamimg CDN.  Exact Wowhead item/spell IDs are retained separately
when we have them, so tooltips/links can still be attached without making icon
coverage depend on a hand-maintained ID registry.
"""

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from src.rulesets.forever.data.catalogue import default_catalogue


ROOT = Path(__file__).resolve().parents[2]
ICON_CACHE = ROOT / "data" / "forever" / "talentsforever_icon_cache.json"
ICON_CDN = "https://wow.zamimg.com/images/wow/icons/small/{icon_key}.jpg"
_WOWHEAD_ENTITY_RE = re.compile(r"https?://(?:www\.)?wowhead\.com/(?:forever/|classic/)?(item|spell)=(\d+)", re.I)
_CACHE: dict[str, Any] | None = None


def _load_cache() -> dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(ICON_CACHE.read_text(encoding="utf-8"))
        except Exception:
            _CACHE = {"classes": {}}
    return _CACHE


def _entity(*, entity_kind: str, entity_id: int, provenance_url: str, provenance_source: str) -> dict[str, Any]:
    return {
        "entity_kind": str(entity_kind),
        "entity_id": int(entity_id),
        "entity_verified": True,
        "provenance_url": str(provenance_url),
        "provenance_source": str(provenance_source),
    }


def _from_exact_wowhead_url(url: str | None, *, expected_kind: str | None = None) -> dict[str, Any] | None:
    text = str(url or "").strip()
    m = _WOWHEAD_ENTITY_RE.search(text)
    if not m:
        return None
    kind, raw_id = m.group(1).lower(), int(m.group(2))
    if expected_kind and kind != expected_kind:
        return None
    return _entity(
        entity_kind=kind,
        entity_id=raw_id,
        provenance_url=text,
        provenance_source=f"Wowhead exact {kind} URL from simulator source data",
    )


def _cache_icon(class_name: str, section: str, key: str) -> dict[str, Any] | None:
    cache = _load_cache()
    row = (((cache.get("classes") or {}).get(str(class_name).lower()) or {}).get(section) or {}).get(str(key))
    if not isinstance(row, dict) or not row.get("icon_key"):
        return None
    icon_key = str(row["icon_key"])
    return {
        "icon_verified": True,
        "icon_provider": "talentsforever_data",
        "icon_key": icon_key,
        "icon_url": ICON_CDN.format(icon_key=icon_key),
        "icon_name": row.get("name") or str(key),
        "icon_provenance_url": cache.get("source_url") or "https://talentsforever.com/data.json",
        "icon_provenance_source": "Talents Forever data.json · " + ("historical beta snapshot icon" if row.get("historical_snapshot") else "WoW Forever beta client-derived icon key"),
        "icon_license": cache.get("license") or "CC BY 4.0",
        "icon_attribution": cache.get("attribution") or "Talents Forever (talentsforever.com)",
    }


def _merge_icon_entity(icon: dict[str, Any] | None, entity: dict[str, Any] | None) -> dict[str, Any] | None:
    if not icon and not entity:
        return None
    out: dict[str, Any] = {}
    if icon:
        out.update(icon)
    if entity:
        out.update(entity)
    # Preserve a single generic provenance pair for old consumers. Prefer exact
    # entity provenance when available; otherwise point at the icon data source.
    if "provenance_url" not in out and icon:
        out["provenance_url"] = icon.get("icon_provenance_url")
        out["provenance_source"] = icon.get("icon_provenance_source")
    return out


# Exact IDs are optional metadata. Icon coverage does *not* depend on this map.
_PALADIN_TALENT_ENTITIES = {
    "deflection": _entity(entity_kind="spell", entity_id=20064, provenance_url="https://www.wowhead.com/classic/spell=20064/deflection", provenance_source="Wowhead Classic, exact spell ID 20064"),
    "benediction": _entity(entity_kind="spell", entity_id=20101, provenance_url="https://www.wowhead.com/forever/spell=20101/benediction", provenance_source="Wowhead Forever, exact spell ID 20101"),
    "conviction": _entity(entity_kind="spell", entity_id=20121, provenance_url="https://www.wowhead.com/forever/spell=20121/conviction", provenance_source="Wowhead Forever, exact spell ID 20121"),
    "seal_of_command": _entity(entity_kind="spell", entity_id=20375, provenance_url="https://www.wowhead.com/classic/spell=20375/seal-of-command", provenance_source="audited exact spell-ID record 20375"),
    "divine_strength": _entity(entity_kind="spell", entity_id=20262, provenance_url="https://www.wowhead.com/forever/spell=20262/divine-strength", provenance_source="Wowhead Forever, exact spell ID 20262"),
    "divine_intellect": _entity(entity_kind="spell", entity_id=20257, provenance_url="https://www.wowhead.com/forever/spell=20257/divine-intellect", provenance_source="Wowhead Forever, exact spell ID 20257"),
    "toughness": _entity(entity_kind="spell", entity_id=20143, provenance_url="https://www.wowhead.com/forever/spell=20143/toughness", provenance_source="Wowhead Forever, exact spell ID 20143"),
    "redoubt": _entity(entity_kind="spell", entity_id=20137, provenance_url="https://www.wowhead.com/forever/spell=20137/redoubt", provenance_source="Wowhead Forever, exact spell ID 20137"),
    "anticipation": _entity(entity_kind="spell", entity_id=20100, provenance_url="https://www.wowhead.com/forever/spell=20100/anticipation", provenance_source="Wowhead Forever, exact spell ID 20100"),
    "improved_seal_of_fury": _entity(entity_kind="spell", entity_id=1314103, provenance_url="https://www.wowhead.com/forever/spell=1314103/improved-seal-of-fury", provenance_source="Wowhead Forever, exact spell ID 1314103"),
    "improved_righteous_fury": _entity(entity_kind="spell", entity_id=20468, provenance_url="https://www.wowhead.com/forever/spell=20468/improved-righteous-fury", provenance_source="Wowhead Forever, exact rank spell ID 20468"),
    "shield_specialization": _entity(entity_kind="spell", entity_id=20148, provenance_url="https://www.wowhead.com/forever/spell=20148/shield-specialization", provenance_source="Wowhead Forever, exact spell ID 20148"),
    "improved_judgement": _entity(entity_kind="spell", entity_id=25956, provenance_url="https://www.wowhead.com/forever/spell=25956/improved-judgement", provenance_source="Wowhead Forever, exact rank spell ID 25956"),
    "holy_conduit": _entity(entity_kind="spell", entity_id=1237268, provenance_url="https://www.wowhead.com/forever/spell=1237268/holy-conduit", provenance_source="Wowhead Forever, exact spell ID 1237268"),
    "vindication": _entity(entity_kind="spell", entity_id=9452, provenance_url="https://www.wowhead.com/forever/spell=9452/vindication", provenance_source="Wowhead Forever, exact spell ID 9452"),
    "sanctified_judgement": _entity(entity_kind="spell", entity_id=1311074, provenance_url="https://www.wowhead.com/forever/spell=1311074/sanctified-judgement", provenance_source="Wowhead Forever, exact spell ID 1311074"),
    "pursuit_of_justice": _entity(entity_kind="spell", entity_id=26023, provenance_url="https://www.wowhead.com/forever/spell=26023/pursuit-of-justice", provenance_source="Wowhead Forever, exact rank spell ID 26023"),
}

_PALADIN_ROTATION_ENTITIES = {
    "seal_of_command": _PALADIN_TALENT_ENTITIES["seal_of_command"],
    "judgement": _entity(entity_kind="spell", entity_id=20271, provenance_url="https://www.wowhead.com/forever/spell=20271/judgement", provenance_source="Wowhead Forever, exact spell ID 20271"),
    "holy_strike": _entity(entity_kind="spell", entity_id=1866, provenance_url="https://www.wowhead.com/forever/spell=1866/holy-strike", provenance_source="Wowhead Forever, exact L20 spell ID 1866"),
}

_ITEM_ENTITY_FALLBACKS = {
    "Wolfsbane": _entity(entity_kind="item", entity_id=267369, provenance_url="https://www.wowhead.com/forever/item=267369/wolfsbane", provenance_source="Wowhead Forever, exact item ID 267369"),
    "Crusader's Chain Shirt": _entity(entity_kind="item", entity_id=250492, provenance_url="https://www.wowhead.com/forever/item=250492", provenance_source="Wowhead Forever, exact item ID 250492"),
    "Crusader's Gloves": _entity(entity_kind="item", entity_id=250512, provenance_url="https://www.wowhead.com/forever/item=250512", provenance_source="Wowhead Forever, exact item ID 250512"),
    "Crusader's Chain Belt": _entity(entity_kind="item", entity_id=250517, provenance_url="https://www.wowhead.com/forever/item=250517", provenance_source="Wowhead Forever, exact item ID 250517"),
    "Crusader's Boots": _entity(entity_kind="item", entity_id=250507, provenance_url="https://www.wowhead.com/forever/item=250507", provenance_source="Wowhead Forever, exact item ID 250507"),
    "Crusader's Chain Leggings": _entity(entity_kind="item", entity_id=250497, provenance_url="https://www.wowhead.com/forever/item=250497", provenance_source="Wowhead Forever, exact item ID 250497"),
}


_FOREVER_TALENT_ENTITY_FALLBACKS = {
    # Source catalogue snapshots predate this exact Forever ID resolution.
    # Keep the override explicit and provenance-pinned instead of guessing from
    # the talent name or icon key.
    ("druid", "genesis"): _entity(
        entity_kind="spell",
        entity_id=1223081,
        provenance_url="https://www.wowhead.com/forever/spell=1223081/genesis",
        provenance_source="Wowhead Forever, exact spell ID 1223081",
    ),
}


def _catalogue_talent_entity(class_name: str, talent_key: str) -> dict[str, Any] | None:
    """Return exact Wowhead talent identity from the pinned source catalogue.

    The normalized Forever fixtures already retain exact source URLs/IDs for
    many talents. I21 must consume that provenance rather than maintaining a
    second hand-written registry or exposing icon-only talent rows.
    """
    try:
        row = default_catalogue().talent(str(class_name).lower(), str(talent_key))
    except (KeyError, ValueError):
        return None
    for ref in row.source_refs:
        if ref.provider != "wowhead" or not isinstance(ref.entity_id, int):
            continue
        exact = _from_exact_wowhead_url(ref.url, expected_kind="spell")
        if exact and int(exact["entity_id"]) == int(ref.entity_id):
            exact["provenance_source"] = f"Pinned Forever source catalogue · {ref.provider} exact talent anchor"
            return exact
    return None


def talent_icon(class_name: str, talent_key: str) -> dict[str, Any] | None:
    key = str(talent_key or "")
    cls = str(class_name).lower()
    aliases = {"imp_frostbolt":"improved_frostbolt", "imp_frost_nova":"improved_frost_nova",
               "imp_fireball":"improved_fireball", "imp_scorch":"improved_scorch",
               "master_elements":"master_of_elements", "gift_of_earthmother":"gift_of_the_earthmother"}
    canonical_key = aliases.get(key, key)
    icon = _cache_icon(class_name, "talents", canonical_key)
    entity = (
        (_PALADIN_TALENT_ENTITIES.get(key) if cls == "paladin" else None)
        or _catalogue_talent_entity(cls, canonical_key)
        or _FOREVER_TALENT_ENTITY_FALLBACKS.get((cls, canonical_key))
    )
    return deepcopy(_merge_icon_entity(icon, entity))


def _rotation_key(class_name: str, step: str) -> str:
    text = str(step or "").strip().lower()
    spells = (((_load_cache().get("classes") or {}).get(str(class_name).lower()) or {}).get("spells") or {})
    # Longest exact display-name prefix wins, so "Seal of Command" is resolved
    # before any shorter overlapping label if the source ever gains one.
    candidates = []
    for key, row in spells.items():
        name = str((row or {}).get("name") or "").strip().lower()
        if name and (text == name or text.startswith(name + " ") or text.startswith(name + " (") or text.startswith(name + ":")):
            candidates.append((len(name), key))
    return max(candidates, default=(0, ""))[1]


def rotation_icon(class_name: str, step: str, *, level: int | None = None) -> dict[str, Any] | None:
    key = _rotation_key(class_name, step)
    if not key:
        return None
    icon = _cache_icon(class_name, "spells", key)
    entity = _PALADIN_ROTATION_ENTITIES.get(key) if str(class_name).lower() == "paladin" else None
    return deepcopy(_merge_icon_entity(icon, entity))


@lru_cache(maxsize=1)
def _item_identities() -> dict:
    try:
        rows = json.loads((ROOT / "data/forever/item_identity_audit.json").read_text())["rows"]
    except (OSError, ValueError, KeyError):
        return {}
    return {int(row["item_id"]): row for row in rows if row.get("name")}


def item_icon(item_name: str, *, source_url: str | None = None) -> dict[str, Any] | None:
    exact = _from_exact_wowhead_url(source_url, expected_kind="item")
    if exact:
        evidence = _item_identities().get(exact["entity_id"])
        # A URL's slug is supplied by us; only independently fetched ID->name
        # evidence can authorize its tooltip. Reject stale/wrong metadata.
        if not evidence or evidence["name"] != str(item_name):
            return None
        exact["provenance_source"] = "Wowhead Forever tooltip ID/name audit"
        exact["identity_evidence_url"] = evidence["source_url"]
        exact["icon_verified"] = True
        exact["icon_provider"] = "wowhead_tooltips"
        return exact
    value = _ITEM_ENTITY_FALLBACKS.get(str(item_name or ""))
    if value:
        return item_icon(item_name, source_url=value["provenance_url"])
    return None


def decorate_talent_trees(class_name: str, trees: dict | None) -> dict:
    out = deepcopy(dict(trees or {}))
    for tree in out.values():
        for talent in list((tree or {}).get("talents") or ()):
            meta = talent_icon(class_name, talent.get("name", ""))
            if meta:
                talent["icon"] = meta
    return out


def _split_rotation(rotation: str | None) -> list[str]:
    return [x.strip() for x in re.split(r";| → |\s+then\s+", str(rotation or ""), flags=re.I) if x.strip()]


def decorate_rotation_steps(class_name: str, rotation: str | None, *, level: int | None = None) -> list[dict[str, Any]]:
    out = []
    for label in _split_rotation(rotation):
        row: dict[str, Any] = {"label": label}
        meta = rotation_icon(class_name, label, level=level)
        if meta:
            row["icon"] = meta
        out.append(row)
    return out


def decorate_gear_stats(gear_stats: dict | None) -> dict:
    out = deepcopy(dict(gear_stats or {}))
    slots = dict(out.get("slots") or {})
    decorated = {}
    for slot, raw in slots.items():
        row = deepcopy(dict(raw or {}))
        name = row.get("name") or row.get("item")
        meta = item_icon(str(name or ""), source_url=row.get("source_url"))
        row.pop("icon", None)
        row["identity_status"] = "verified" if meta else "unverified"
        if meta:
            row["icon"] = meta
        decorated[slot] = row
    if slots:
        out["slots"] = decorated
    return out
