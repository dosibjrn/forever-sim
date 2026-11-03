#!/usr/bin/env python3
"""Load a bounded, deterministic donor corpus from the pinned Rust engine.

These are additional source request fixtures, not synthetic items or a full
class/equip-law proof. Consumers must still apply same-class, exact-slot-shape,
native item DB, item-type, armor-type, class-allowlist and level guards.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


DONOR_DIRECTORIES = (
    "fixtures/forever-gaps",
    "fixtures/mage/prepared-v2",
    "validation/2026-10-04-hunter-preset-matrix/variants",
    "validation/2026-10-04-production-gear-swaps/requests",
)

SOURCE_CLASSES = frozenset({
    "ClassDruid",
    "ClassHunter",
    "ClassMage",
    "ClassPaladin",
    "ClassPriest",
    "ClassRogue",
    "ClassShaman",
    "ClassWarlock",
    "ClassWarrior",
})


# Emit a profile hint only when the pinned source path explicitly names one
# class/spec pair. Generic or ambiguous fixtures remain class-only gear donors.
PROFILE_PATH_TOKENS = {
    "druid/balance": ("balance-druid", "druid-balance"),
    "druid/feral_cat": ("feral-cat-druid", "druid-feral-cat"),
    "druid/feral_bear": ("feral-bear-druid", "druid-feral-bear"),
    "druid/restoration": ("restoration-druid", "druid-restoration"),
    "hunter/beast_mastery": ("beast-mastery-hunter", "beastmastery-hunter"),
    "hunter/marksmanship": ("marksmanship-hunter", "hunter-marksmanship"),
    "hunter/survival": ("survival-hunter", "hunter-survival"),
    "mage/arcane": ("arcane-mage", "mage-arcane"),
    "mage/fire": ("fire-mage", "mage-fire"),
    "mage/frost": ("frost-mage", "mage-frost"),
    "paladin/holy": ("holy-paladin", "paladin-holy"),
    "paladin/protection": ("protection-paladin", "paladin-protection"),
    "paladin/retribution": ("retribution-paladin", "paladin-retribution"),
    "priest/discipline": ("discipline-priest", "priest-discipline"),
    "priest/holy": ("holy-priest", "priest-holy"),
    "priest/shadow": ("shadow-priest", "priest-shadow"),
    "rogue/assassination": ("assassination-rogue", "rogue-assassination"),
    "rogue/combat": ("combat-rogue", "rogue-combat"),
    "rogue/subtlety": ("subtlety-rogue", "rogue-subtlety"),
    "shaman/elemental": ("elemental-shaman", "shaman-elemental"),
    "shaman/enhancement": ("enhancement-shaman", "shaman-enhancement"),
    "shaman/restoration": ("restoration-shaman", "shaman-restoration"),
    "warlock/affliction": ("affliction-warlock", "warlock-affliction"),
    "warlock/demonology": ("demonology-warlock", "warlock-demonology"),
    "warlock/destruction": ("destruction-warlock", "warlock-destruction"),
    "warrior/arms": ("arms-warrior", "warrior-arms"),
    "warrior/fury": ("fury-warrior", "warrior-fury"),
    "warrior/protection": ("protection-warrior", "warrior-protection"),
}


def source_profile_hint(source_path: str, class_name: str) -> str | None:
    """Return an explicit class/spec hint from a pinned fixture path, else None.

    The request's class remains authoritative. This is deliberately
    conservative: it never guesses feral cat vs bear or spec from generic
    class-only names.
    """
    if not isinstance(source_path, str) or class_name not in SOURCE_CLASSES:
        return None
    class_key = class_name[len("Class"):].lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", source_path.lower()).strip("-")
    if class_key not in normalized.split("-"):
        return None
    padded = f"-{normalized}-"
    matches = [
        profile_id
        for profile_id, tokens in PROFILE_PATH_TOKENS.items()
        if profile_id.split("/", 1)[0] == class_key
        and any(f"-{token}-" in padded for token in tokens)
    ]
    return matches[0] if len(matches) == 1 else None


def _first_player(request: dict) -> dict | None:
    try:
        return request["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError):
        return None


def load_source_donor_fixtures(engine_src: Path) -> dict:
    """Return pinned same-class request donors plus explicit skip accounting.

    Only the four curated engine fixture directories above are scanned. Each
    accepted donor carries its relative source path and SHA-256 of the exact
    bytes read from the checked-out engine gitlink. Invalid JSON is fatal;
    unsupported player/class/equipment shapes are skipped and recorded.
    """
    engine_src = Path(engine_src)
    fixtures = []
    skipped = []
    for relative_dir in DONOR_DIRECTORIES:
        directory = engine_src / relative_dir
        if not directory.is_dir():
            raise FileNotFoundError(
                f"SOURCE_DONOR_DIRECTORY_MISSING:{relative_dir}"
            )
        for path in sorted(directory.glob("*.request.json")):
            raw = path.read_bytes()
            relative_path = path.relative_to(engine_src).as_posix()
            try:
                request = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"SOURCE_DONOR_JSON_INVALID:{relative_path}"
                ) from exc
            source_player = _first_player(request)
            if source_player is None:
                skipped.append({
                    "source_path": relative_path,
                    "reason": "MISSING_FIRST_PLAYER",
                })
                continue
            class_name = source_player.get("class")
            if class_name not in SOURCE_CLASSES:
                skipped.append({
                    "source_path": relative_path,
                    "reason": "UNSUPPORTED_OR_MISSING_CLASS",
                })
                continue
            equipment = source_player.get("equipment")
            gear_items = equipment.get("items") if isinstance(equipment, dict) else None
            if not isinstance(gear_items, list) or not gear_items:
                skipped.append({
                    "source_path": relative_path,
                    "reason": "MISSING_OR_EMPTY_EQUIPMENT_ITEMS",
                })
                continue
            fixtures.append({
                "source_path": relative_path,
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "class_name": class_name,
                "profile_id_hint": source_profile_hint(relative_path, class_name),
                "item_count": len(gear_items),
                "request": request,
            })
    fixtures.sort(key=lambda item: item["source_path"])
    skipped.sort(key=lambda item: item["source_path"])
    return {
        "directories": list(DONOR_DIRECTORIES),
        "fixtures": fixtures,
        "skipped": skipped,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-src", required=True, type=Path)
    args = parser.parse_args()
    inventory = load_source_donor_fixtures(args.engine_src)
    print(json.dumps({
        "directories": inventory["directories"],
        "loaded": len(inventory["fixtures"]),
        "skipped": len(inventory["skipped"]),
        "manifest": [
            {
                "source_path": item["source_path"],
                "source_sha256": item["source_sha256"],
                "class_name": item["class_name"],
                "profile_id_hint": item["profile_id_hint"],
                "item_count": item["item_count"],
            }
            for item in inventory["fixtures"]
        ],
        "skipped_sources": inventory["skipped"],
    }, indent=2))
