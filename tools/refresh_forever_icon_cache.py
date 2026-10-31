#!/usr/bin/env python3
from __future__ import annotations

"""Refresh the small Forever talent/spell icon-key cache.

Source: https://talentsforever.com/data.json (CC BY 4.0).
No image bytes are downloaded.  The generated cache stores only names and the
client icon keys; the listener resolves those keys against the Wowhead/Zamimg
icon CDN at render time.
"""

import argparse
import json
from pathlib import Path
import re
import urllib.request

SOURCE_URL = "https://talentsforever.com/data.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "forever" / "talentsforever_icon_cache.json"


def slug(name: str) -> str:
    text = str(name or "").lower().replace("’", "'")
    text = text.replace("'", "")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return re.sub(r"_+", "_", text)


def _class_name(raw: object) -> str:
    if isinstance(raw, str):
        return slug(raw)
    if isinstance(raw, dict):
        for key in ("class", "className", "name", "id"):
            if raw.get(key):
                return slug(str(raw[key]))
    return ""


def _iter_class_blocks(section: object):
    """Yield (class_slug, payload) from dict- or list-shaped exports."""
    if isinstance(section, dict):
        for key, value in section.items():
            if isinstance(value, dict):
                yield slug(str(key)), value
        return
    if isinstance(section, list):
        for value in section:
            if not isinstance(value, dict):
                continue
            cls = _class_name(value)
            if cls:
                yield cls, value


def _talent_rows(block: dict):
    trees = block.get("trees") or block.get("talentTrees") or block.get("talents") or block
    if isinstance(trees, dict):
        values = list(trees.values())
    elif isinstance(trees, list):
        values = trees
    else:
        values = []
    for tree in values:
        if isinstance(tree, dict):
            rows = tree.get("talents") or tree.get("nodes") or []
            if isinstance(rows, dict):
                rows = list(rows.values())
        elif isinstance(tree, list):
            rows = tree
        else:
            rows = []
        for row in rows:
            if isinstance(row, dict) and row.get("name") and row.get("icon"):
                yield row


def _spell_icons(block: dict):
    icons = block.get("icons") or {}
    if isinstance(icons, dict):
        for name, icon in icons.items():
            if name and icon:
                yield str(name), str(icon)
    spells = block.get("spells") or []
    if isinstance(spells, dict):
        spells = list(spells.values())
    if isinstance(spells, list):
        for row in spells:
            if isinstance(row, dict) and row.get("name") and row.get("icon"):
                yield str(row["name"]), str(row["icon"])


def build_cache(raw: dict, *, source_url: str = SOURCE_URL) -> dict:
    classes: dict[str, dict] = {}
    for cls, block in _iter_class_blocks(raw.get("talents") or {}):
        dest = classes.setdefault(cls, {"talents": {}, "spells": {}})
        for row in _talent_rows(block):
            key = slug(row["name"])
            dest["talents"][key] = {"name": str(row["name"]), "icon_key": str(row["icon"])}
    for cls, block in _iter_class_blocks(raw.get("spellbooks") or raw.get("spellBooks") or {}):
        dest = classes.setdefault(cls, {"talents": {}, "spells": {}})
        for name, icon in _spell_icons(block):
            dest["spells"][slug(name)] = {"name": name, "icon_key": icon}

    # Fail closed if the source shape changes instead of writing an empty cache.
    if not classes or not any(v["talents"] or v["spells"] for v in classes.values()):
        raise ValueError("Talents Forever data shape did not contain recognizable talent/spell icon records")

    for value in classes.values():
        value["talents"] = dict(sorted(value["talents"].items()))
        value["spells"] = dict(sorted(value["spells"].items()))
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    return {
        "schema_version": 1,
        "source_url": source_url,
        "source_generated": raw.get("generated") or meta.get("generated") or raw.get("generatedAt"),
        "license": raw.get("license") or meta.get("license") or "CC BY 4.0",
        "attribution": "Talents Forever (talentsforever.com), WoW Forever beta client-derived icon keys",
        "classes": dict(sorted(classes.items())),
    }


def _read_source(path: Path | None, url: str) -> dict:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers={"User-Agent": "mage-sim-icon-cache/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, help="local data.json; avoids network and is used by tests")
    p.add_argument("--url", default=SOURCE_URL)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args()
    cache = build_cache(_read_source(args.source, args.url), source_url=args.url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {args.output} ({len(cache['classes'])} classes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
