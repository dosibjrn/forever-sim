from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .catalogue import ItemCatalogue, ItemRecord, RequiredLevelOrigin
from .required_level_model import apply_inferred_required_levels, build_required_level_model, build_availability_floor_model

CLASS_IDS = {"warrior": 1, "paladin": 2, "hunter": 3, "rogue": 4, "priest": 5,
             "shaman": 7, "mage": 8, "warlock": 9, "druid": 11}

_SLOT_BY_ID = {
    1: "head", 2: "neck", 3: "shoulder", 4: "shirt", 5: "chest", 6: "waist",
    7: "legs", 8: "feet", 9: "wrist", 10: "hands", 11: "finger", 12: "trinket",
    13: "one_hand", 14: "off_hand", 15: "ranged", 16: "back", 17: "two_hand",
    19: "tabard", 21: "main_hand", 22: "off_hand", 23: "off_hand", 24: "ammo",
    25: "thrown", 26: "ranged", 28: "relic",
}

_ARMOR_SUBCLASS = {
    0: "misc", 1: "cloth", 2: "leather", 3: "mail", 4: "plate", 6: "shield",
    7: "libram", 8: "idol", 9: "totem", 10: "sigil",
}

_WEAPON_SUBCLASS = {
    0: "axe", 1: "two_hand_axe", 2: "bow", 3: "gun", 4: "mace", 5: "two_hand_mace",
    6: "polearm", 7: "sword", 8: "two_hand_sword", 10: "staff", 13: "fist",
    15: "dagger", 16: "thrown", 18: "crossbow", 19: "wand", 20: "fishing_pole",
}

_TYPED_KEYS = {
    "str": "strength", "agi": "agility", "sta": "stamina", "int": "intellect",
    "spi": "spirit", "atkpwr": "attack_power", "splpwr": "spell_power",
    "manargn": "mp5", "hitrtng": "hit", "critstrkrtng": "crit", "defrtng": "defense",
    "dodgertng": "dodge", "armorbonus": "bonus_armor",
}

_EXTRA_NUMERIC_KEYS = (
    "spldmg", "healthrgn", "firres", "frores", "natres", "arcres", "holres",
    "splpen", "exprtng", "parryrtng", "blockrtng", "resipct", "rgdatkpwr",
)


@dataclass(frozen=True)
class CaptureImportSummary:
    captured_at: str
    source_manifest_sha256: str
    canonical_items: int
    class_eligibility_rows: int
    observed_required_level: int
    inferred_required_level: int
    unresolved_required_level: int
    catalogue_hash: str
    leaf_counts: dict[str, int]
    merged_rows: dict[str, int]
    unique_ids_by_class: dict[str, int]
    union_unique_ids: int
    variant_rows_by_class: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "forever-item-catalogue-capture-import-v1",
            "captured_at": self.captured_at,
            "source_manifest_sha256": self.source_manifest_sha256,
            "canonical_items": self.canonical_items,
            "class_eligibility_rows": self.class_eligibility_rows,
            "observed_required_level": self.observed_required_level,
            "inferred_required_level": self.inferred_required_level,
            "unresolved_required_level": self.unresolved_required_level,
            "catalogue_hash": self.catalogue_hash,
            "leaf_counts": dict(sorted(self.leaf_counts.items())),
            "merged_rows": dict(sorted(self.merged_rows.items())),
            "unique_ids_by_class": dict(sorted(self.unique_ids_by_class.items())),
            "union_unique_ids": self.union_unique_ids,
            "variant_rows_by_class": dict(sorted(self.variant_rows_by_class.items())),
        }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _num(row: dict[str, Any], key: str) -> float:
    value = row.get(key, 0)
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_fingerprint(row: dict[str, Any]) -> str:
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_base_rows(rows: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Return exactly one non-variant Wowhead base row per item id.

    The captured listview payload repeats an item id for bonus-tree variants via
    ``parentListviewRowItem``. Those are evidence, not separate canonical items.
    """
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item_id = _int_or_none(row.get("id"))
        if item_id is not None:
            grouped[item_id].append(row)
    out: dict[int, dict[str, Any]] = {}
    for item_id, candidates in grouped.items():
        base = [r for r in candidates if "parentListviewRowItem" not in r]
        if len(base) != 1:
            raise ValueError(f"item {item_id}: expected exactly one base row, got {len(base)}")
        out[item_id] = base[0]
    return out


def item_record_from_listview(row: dict[str, Any], *, captured_at: str) -> ItemRecord:
    item_id = int(row["id"])
    slot_id = _int_or_none(row.get("slot"))
    item_class = _int_or_none(row.get("classs"))
    subclass = _int_or_none(row.get("subclass"))
    armor_type = _ARMOR_SUBCLASS.get(subclass, "") if item_class == 4 else ""
    weapon_type = _WEAPON_SUBCLASS.get(subclass, "") if item_class == 2 else ""
    slot = _SLOT_BY_ID.get(slot_id, "")
    hands = 2 if slot == "two_hand" else (1 if item_class == 2 and slot in {"one_hand", "main_hand", "off_hand"} else 0)

    typed = {field: _num(row, key) for key, field in _TYPED_KEYS.items()}
    extra_stats = {key: _num(row, key) for key in _EXTRA_NUMERIC_KEYS if _num(row, key) != 0.0}

    req = _int_or_none(row.get("reqlevel"))
    req_origin = RequiredLevelOrigin.OBSERVED.value if req is not None else RequiredLevelOrigin.MISSING.value
    return ItemRecord(
        item_id=item_id,
        name=str(row.get("name") or row.get("displayName") or f"Wowhead item {item_id}"),
        slot=slot,
        item_level=_int_or_none(row.get("level")),
        required_level=req,
        required_level_origin=req_origin,
        quality=_int_or_none(row.get("quality")),
        armor_type=armor_type,
        weapon_type=weapon_type,
        weapon_hands=hands,
        weapon_min_damage=_num(row, "dmgmin1"),
        weapon_max_damage=_num(row, "dmgmax1"),
        weapon_speed=_num(row, "speed"),
        weapon_dps=_num(row, "dps"),
        armor=_num(row, "armor"),
        bonus_armor=typed["bonus_armor"],
        strength=typed["strength"],
        agility=typed["agility"],
        stamina=typed["stamina"],
        intellect=typed["intellect"],
        spirit=typed["spirit"],
        attack_power=typed["attack_power"],
        spell_power=typed["spell_power"],
        mp5=typed["mp5"],
        hit=typed["hit"],
        crit=typed["crit"],
        defense=typed["defense"],
        dodge=typed["dodge"],
        source_type="wowhead_listview",
        source_name="Forever Items",
        source_url=f"https://www.wowhead.com/forever/item={item_id}",
        identity_origin="wowhead_listview",
        last_verified_at=captured_at,
        fetch_status="verified_listview",
        upstream_fingerprint=_row_fingerprint(row),
        extra_stats=extra_stats,
    )


def import_adaptive_capture(capture_dir: str | Path, catalogue_path: str | Path) -> CaptureImportSummary:
    capture = Path(capture_dir)
    manifest_path = capture / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    captured_at = str(manifest.get("captured_at") or "")
    attempts = list(manifest.get("attempts") or [])

    failed = [a for a in attempts if not a.get("accepted")]
    if failed:
        raise ValueError(f"capture contains {len(failed)} failed attempts")
    terminal = [a for a in attempts if a.get("accepted") and not a.get("needs_split")]
    if not terminal:
        raise ValueError("capture has no terminal leaf attempts")
    for a in terminal:
        if int(a.get("listview_unique_ids") or 0) >= 1000:
            raise ValueError(f"terminal leaf still capped at 1000 ids: {a.get('class_key')} {a.get('min_item_level')}-{a.get('max_item_level')}")
        found, displayed = a.get("found_count"), a.get("displayed_count")
        if found is not None and displayed is not None and int(found) > int(displayed):
            raise ValueError(f"terminal leaf still truncated: {a.get('class_key')} {a.get('min_item_level')}-{a.get('max_item_level')}")

    rows_by_class: dict[str, list[dict[str, Any]]] = {}
    bases_by_class: dict[str, dict[int, dict[str, Any]]] = {}
    for class_key in manifest.get("classes") or []:
        if class_key not in CLASS_IDS:
            raise ValueError(f"unsupported capture class: {class_key}")
        path = capture / f"{class_key}_merged.listview.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError(f"{path.name}: expected JSON array")
        rows_by_class[class_key] = rows
        bases_by_class[class_key] = canonical_base_rows(rows)

    union: dict[int, dict[str, Any]] = {}
    eligibility: dict[int, set[str]] = defaultdict(set)
    for class_key, base_rows in bases_by_class.items():
        for item_id, row in base_rows.items():
            eligibility[item_id].add(class_key)
            prior = union.get(item_id)
            if prior is None:
                union[item_id] = row
            elif _row_fingerprint(prior) != _row_fingerprint(row):
                # Search payload decorations can vary. Only reject if canonical modeled facts differ.
                modeled_keys = {
                    "name", "level", "reqlevel", "slot", "quality", "armor", "classs", "subclass",
                    "str", "agi", "sta", "int", "spi", "atkpwr", "splpwr", "manargn", "hitrtng",
                    "critstrkrtng", "defrtng", "dodgertng", "armorbonus", "dmgmin1", "dmgmax1", "speed", "dps",
                }
                diffs = {k for k in modeled_keys if prior.get(k) != row.get(k)}
                if diffs:
                    raise ValueError(f"item {item_id}: conflicting canonical facts across class captures: {sorted(diffs)}")

    catalogue_path = Path(catalogue_path)
    if catalogue_path.exists():
        catalogue_path.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(catalogue_path) + suffix)
        if p.exists():
            p.unlink()

    with ItemCatalogue(catalogue_path) as catalogue:
        records = [item_record_from_listview(row, captured_at=captured_at) for _, row in sorted(union.items())]
        catalogue.upsert_items(records)
        for item_id, classes in sorted(eligibility.items()):
            for class_key in sorted(classes):
                leaves = [
                    a for a in terminal
                    if a.get("class_key") == class_key
                    and int(a.get("min_item_level")) <= int(union[item_id].get("level") or -1) <= int(a.get("max_item_level"))
                ]
                provenance = ";".join(sorted(str(a.get("url")) for a in leaves))
                catalogue.add_class_eligibility(item_id, CLASS_IDS[class_key], provenance)
        build_required_level_model(catalogue, computed_at=captured_at)
        apply_inferred_required_levels(catalogue)
        observed_fit_rows = [x for x in catalogue.list_items() if x.item_level is not None and x.required_level is not None and x.required_level_origin == RequiredLevelOrigin.OBSERVED.value]
        if len(observed_fit_rows) >= 3 and len({x.item_level for x in observed_fit_rows}) >= 3:
            build_availability_floor_model(catalogue, computed_at=captured_at)
        items = catalogue.list_items()
        observed = sum(x.required_level_origin == RequiredLevelOrigin.OBSERVED.value for x in items)
        inferred = sum(x.required_level_origin in {RequiredLevelOrigin.INFERRED_MEDIAN.value, RequiredLevelOrigin.INFERRED_INTERPOLATED.value} for x in items)
        unresolved = sum(x.required_level is None for x in items)
        cat_hash = catalogue.catalogue_hash()
        class_rows = catalogue._conn.execute("SELECT COUNT(*) FROM item_class_eligibility").fetchone()[0]

    leaf_counts = {k: sum(a.get("class_key") == k for a in terminal) for k in rows_by_class}
    return CaptureImportSummary(
        captured_at=captured_at,
        source_manifest_sha256=_sha256(manifest_path),
        canonical_items=len(union),
        class_eligibility_rows=int(class_rows),
        observed_required_level=observed,
        inferred_required_level=inferred,
        unresolved_required_level=unresolved,
        catalogue_hash=cat_hash,
        leaf_counts=leaf_counts,
        merged_rows={k: len(v) for k, v in rows_by_class.items()},
        unique_ids_by_class={k: len(v) for k, v in bases_by_class.items()},
        union_unique_ids=len(union),
        variant_rows_by_class={k: len(rows_by_class[k]) - len(bases_by_class[k]) for k in rows_by_class},
    )
