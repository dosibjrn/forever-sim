#!/usr/bin/env python3
"""Load a bounded, deterministic donor corpus from the pinned Rust engine.

These are additional source request fixtures, not synthetic items or a game-law
proof. Consumers bound proposals by same-class, exact-slot-shape, source-observed
entries and native item identity/type. MythicSim Rust alone decides armor,
class, level, unique and all other equipment legality.
"""
from __future__ import annotations

import hashlib
import json
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
                "item_count": item["item_count"],
            }
            for item in inventory["fixtures"]
        ],
        "skipped_sources": inventory["skipped"],
    }, indent=2))
