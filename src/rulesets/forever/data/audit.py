from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from .catalogue import ForeverSourceCatalogue
from .provenance import stable_json_fingerprint, wowhead_id_from_url


ROOT = Path(__file__).resolve().parents[4]
ICON_CACHE = ROOT / "data" / "forever" / "talentsforever_icon_cache.json"


def _roster() -> dict[str, Any]:
    return json.loads(ICON_CACHE.read_text(encoding="utf-8"))


def audit_catalogue(cat: ForeverSourceCatalogue) -> dict[str, Any]:
    cache = _roster()
    issues: list[dict[str, Any]] = []
    classes: dict[str, Any] = {}
    for class_key in cat.classes():
        roster = ((cache.get("classes") or {}).get(class_key) or {})
        source_talent_rows = dict(roster.get("talents") or {})
        source_talents = set(source_talent_rows)
        source_spells = set((roster.get("spells") or {}).keys())
        # Coverage is measured in source-roster key space.  Local compatibility
        # keys such as ``imp_frostbolt`` are intentionally allowed to differ
        # from source keys such as ``improved_frostbolt``.
        canonical_source_talents: set[str] = set()
        canonical_local_talents: set[str] = set()
        seen_records: set[tuple[str, str]] = set()
        for row in cat._talents.get(class_key, {}).values():  # intentional internal audit view
            marker = (class_key, row.local_key)
            if marker in seen_records:
                continue
            seen_records.add(marker)
            canonical_local_talents.add(row.local_key)
            matches = [k for k, src in source_talent_rows.items() if str((src or {}).get("name")) == row.name]
            canonical_source_talents.update(matches)
        canonical_spells = set(cat._spells.get(class_key, {}).keys())
        unresolved = cat.unresolved(class_key)
        unresolved_talents = {str(u.details.get("source_roster_key") or u.local_key) for u in unresolved if u.entity_kind == "talent"}
        unresolved_spells = {str(u.details.get("source_roster_key") or u.local_key) for u in unresolved if u.entity_kind == "spell"}
        missing_talent_status = sorted(source_talents - canonical_source_talents - unresolved_talents)
        missing_spell_status = sorted(source_spells - canonical_spells - unresolved_spells)
        if missing_talent_status:
            issues.append({"severity": "error", "class": class_key, "kind": "unclassified_talents", "keys": missing_talent_status})
        if missing_spell_status:
            issues.append({"severity": "error", "class": class_key, "kind": "unclassified_spells", "keys": missing_spell_status})
        classes[class_key] = {
            "source_roster": {"talents": len(source_talents), "spells": len(source_spells)},
            "canonical": {"talents": len(canonical_local_talents), "spell_families": len(canonical_spells)},
            "unresolved": {"talents": len(unresolved_talents), "spells": len(unresolved_spells)},
            "coverage": {
                "talent_status_pct": round(100.0 * len(source_talents & (canonical_source_talents | unresolved_talents)) / max(1, len(source_talents)), 2),
                "spell_status_pct": round(100.0 * len(source_spells & (canonical_spells | unresolved_spells)) / max(1, len(source_spells)), 2),
                "talent_id_pct": round(100.0 * len(source_talents & canonical_source_talents) / max(1, len(source_talents)), 2),
                "spell_family_id_pct": round(100.0 * len(source_spells & canonical_spells) / max(1, len(source_spells)), 2),
            },
        }

    # Source refs are validated by catalogue construction; repeat explicit URL/ID
    # accounting here so the report is independently useful.
    wowhead_refs = 0
    server_side_effects = 0
    unsupported_effects = 0
    for fam in cat._spells.values():
        for rows in fam.values():
            for row in rows:
                ref = row.source_ref
                if ref.provider == "wowhead":
                    wowhead_refs += 1
                    if wowhead_id_from_url(ref.url) != int(ref.entity_id):
                        issues.append({"severity": "error", "kind": "url_id_mismatch", "url": ref.url})
                for effect in row.effects:
                    server_side_effects += int(effect.server_side_script)
                    unsupported_effects += int(effect.normalization_status != "supported")
    unique_talents = set()
    for class_key, rows in cat._talents.items():
        for row in rows.values():
            if (class_key, row.local_key) in unique_talents:
                continue
            unique_talents.add((class_key, row.local_key))
            for ref in row.source_refs:
                if ref.provider == "wowhead":
                    wowhead_refs += 1
                    if wowhead_id_from_url(ref.url) != int(ref.entity_id):
                        issues.append({"severity": "error", "kind": "url_id_mismatch", "url": ref.url})
            for rank in row.rank_records:
                for effect in rank.effects:
                    server_side_effects += int(effect.server_side_script)
                    unsupported_effects += int(effect.normalization_status != "supported")

    reasons = Counter(u.reason for u in cat.unresolved())
    report = {
        "snapshot": cat.summary(),
        "source_roster_generated": cache.get("source_generated"),
        "source_roster_url": cache.get("source_url"),
        "classes": classes,
        "wowhead_resolved_refs": wowhead_refs,
        "effect_status": {
            "server_side_script": server_side_effects,
            "unsupported_or_ambiguous": unsupported_effects,
        },
        "unresolved_reasons": dict(sorted(reasons.items())),
        "issues": issues,
    }
    report["audit_fingerprint"] = stable_json_fingerprint(report)
    report["ok"] = not any(row.get("severity") == "error" for row in issues)
    return report
