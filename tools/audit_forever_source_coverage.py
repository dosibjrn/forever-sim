#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rulesets.forever.data.audit import audit_catalogue
from src.rulesets.forever.data.catalogue import DEFAULT_SNAPSHOT_ID, ForeverSourceCatalogue


def _markdown(report: dict) -> str:
    lines = [
        f"# Forever source coverage — v{(ROOT / 'VERSION').read_text().strip()}",
        "",
        f"Snapshot: `{report['snapshot']['snapshot_id']}`  ",
        f"Normalized fingerprint: `{report['snapshot']['normalized_fingerprint']}`  ",
        f"Audit fingerprint: `{report['audit_fingerprint']}`  ",
        f"Result: **{'PASS' if report['ok'] else 'FAIL'}**",
        "",
        "## Coverage",
        "",
        "| Class | source talents | ID-resolved talents | source spells | ID-resolved families | talent status | spell status |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, row in report["classes"].items():
        lines.append(
            f"| {key.title()} | {row['source_roster']['talents']} | {row['canonical']['talents']} | "
            f"{row['source_roster']['spells']} | {row['canonical']['spell_families']} | "
            f"{row['coverage']['talent_status_pct']:.2f}% | {row['coverage']['spell_status_pct']:.2f}% |"
        )
    lines += [
        "",
        "`status` coverage counts both resolved and explicitly unresolved entries. It is expected to be 100%; ID coverage grows in later source-fidelity increments.",
        "",
        f"Wowhead resolved source refs: **{report['wowhead_resolved_refs']}**",
        "",
        "## Explicit unresolved reasons",
        "",
    ]
    for reason, count in report["unresolved_reasons"].items():
        lines.append(f"- `{reason}`: {count}")
    lines += ["", "## Audit issues", ""]
    if report["issues"]:
        for issue in report["issues"]:
            lines.append(f"- **{issue.get('severity','?').upper()}** `{issue.get('kind')}`: `{json.dumps(issue, sort_keys=True)}`")
    else:
        lines.append("- none")
    lines += [
        "",
        "## Interpretation",
        "",
        "The pinned snapshot distinguishes exact identities, supported normalized effects, and explicit unresolved/opaque semantics. Coverage must not be read as full mechanics fidelity; server-side/ambiguous behavior remains explicit rather than silently guessed.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT_ID)
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--md-out", type=Path)
    args = ap.parse_args()
    cat = ForeverSourceCatalogue(args.snapshot)
    report = audit_catalogue(cat)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
