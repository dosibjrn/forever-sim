"""M46 closure/readiness report.

This is deliberately a deterministic *contract* refresh, not M47 optimization.
It refreshes representative L20/L40/L60 player-facing gear/stat outputs and
summarizes the explicit fidelity inventory so plan state cannot drift from code.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import game_context
from src.rulesets.forever.fidelity import inventory_report
from tools.report_backend_comparison import build_report as build_backend_comparison
from src.rulesets.forever.release_gate import fixed_fixture_rows

LEVELS = (20, 40, 60)
FAMILY = {"mage": "frost", "paladin": "protection", "druid": "feral"}


def _fixture_rows(cls: str) -> list[dict]:
    return fixed_fixture_rows(cls)


def build_report() -> dict:
    fidelity = inventory_report()
    classes = {}
    for cls in ("mage", "paladin", "druid"):
        rows = _fixture_rows(cls)
        by_level = {}
        for row in rows:
            level = int(row["level"])
            if level not in LEVELS:
                continue
            gear = row.get("gear_stats") or {}
            weights = row.get("stat_weights") or {}
            by_level[str(level)] = {
                "mobs_per_hour": row.get("mobs_per_hour"),
                "allocation": row.get("allocation"),
                "rotation": row.get("rotation"),
                "gear_provenance": gear.get("provenance"),
                "gear_totals": {k: gear.get(k) for k in ("strength","agility","stamina","intellect","spirit","spell_power","healing_power","mp5","armor","defense","weapon_dps") if k in gear},
                "reference_stat": weights.get("reference_stat"),
                "weight_statuses": {k: v.get("status") for k, v in (weights.get("weights") or {}).items() if isinstance(v, dict)},
            }
        issues = fidelity["classes"][cls]
        classes[cls] = {
            "open_issue_count": issues["count"],
            "high": issues["high"],
            "medium": issues["medium"],
            "low": issues["low"],
            "issues": [x["issue_id"] for x in issues["issues"]],
            "levels": by_level,
        }
    blockers = [x for c in fidelity["classes"].values() for x in c["issues"] if x.get("blocks_m46_for_target_server", x["severity"] in {"high", "medium"})]
    backend = build_backend_comparison()
    return {
        "schema_version": 1,
        "scope": "M46 deterministic fidelity/gear/stat closure refresh; NOT optimized M47 routes",
        "classes": classes,
        "remaining_high_medium": [x["issue_id"] for x in blockers],
        "backend_comparison": {
            "ready": backend["ready_for_m46_done"],
            "blocking_items": backend["blocking_items"],
            "mage_status": backend["mage"]["status"],
            "druid_status": backend["druid"]["status"],
            "release_status": backend["release"]["status"],
        },
        "ready_for_m46_done": len(blockers) == 0 and backend["ready_for_m46_done"],
    }


def render_md(report: dict, version: str) -> str:
    out = [f"# M46 closure refresh — v{version}", "", report["scope"], ""]
    for cls, data in report["classes"].items():
        out += [f"## {cls.title()}", "", f"Open fidelity: {data['open_issue_count']} (high {data['high']}, medium {data['medium']}, low {data['low']})", ""]
        if data["issues"]:
            out += ["Issues: " + ", ".join(f"`{x}`" for x in data["issues"]), ""]
        out += ["| Level | mobs/h | allocation | reference stat | gear provenance |", "|---:|---:|---|---|---|"]
        for level in ("20", "40", "60"):
            row = data["levels"].get(level, {})
            mph = row.get("mobs_per_hour")
            mph_s = f"{mph:.1f}" if isinstance(mph, (int, float)) else "n/a"
            out.append(f"| {level} | {mph_s} | {row.get('allocation','')} | {row.get('reference_stat','')} | {row.get('gear_provenance','')} |")
        out.append("")
    backend = report["backend_comparison"]
    out += [
        "## Readiness", "",
        "Remaining high/medium fidelity rows: " + (", ".join(f"`{x}`" for x in report["remaining_high_medium"]) or "none"), "",
        "Backend-comparison blockers: " + (", ".join(f"`{x}`" for x in backend["blocking_items"]) or "none"), "",
        f"Mage comparison status: `{backend['mage_status']}`; Druid: `{backend['druid_status']}`; release: `{backend['release_status']}`.", "",
        f"M46 DONE-ready by this strict closure check: **{'YES' if report['ready_for_m46_done'] else 'NO'}**", "",
        "This report intentionally does not optimize routes. Optimized Mage/Paladin/Druid × L20/L40/L60 belongs to M47.", ""
    ]
    return "\n".join(out)


def main() -> None:
    report = build_report()
    version = (ROOT / "VERSION").read_text().strip()
    out_json = ROOT / f"docs/validation/M46_CLOSURE_REFRESH_v{version}.json"
    out_md = ROOT / f"docs/validation/M46_CLOSURE_REFRESH_v{version}.md"
    out_json.write_text(json.dumps(report, indent=2) + "\n")
    out_md.write_text(render_md(report, version))
    print(json.dumps({"ready": report["ready_for_m46_done"], "remaining_high_medium": report["remaining_high_medium"]}))


if __name__ == "__main__":
    main()
