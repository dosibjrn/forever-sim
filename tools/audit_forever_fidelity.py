#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rulesets.forever.fidelity import inventory_report


def _markdown(report: dict) -> str:
    out = [
        f"# Forever modeled-behavior fidelity inventory — v{(ROOT / 'VERSION').read_text().strip()}",
        "",
        report["scope"] + ".",
        "",
        "This is intentionally separate from source-ID coverage: a canonical entity may be resolved while its server/event semantics remain partial.",
        "",
        "| Class | Open gaps | High | Medium | Low |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, row in report["classes"].items():
        out.append(f"| {key.title()} | {row['count']} | {row['high']} | {row['medium']} | {row['low']} |")
    for key, row in report["classes"].items():
        out += ["", f"## {key.title()}", ""]
        for issue in row["issues"]:
            impacts = ", ".join(issue["impacts"])
            out += [
                f"### `{issue['issue_id']}` — {issue['mechanic']}",
                "",
                f"**{issue['status']} / {issue['severity']}** · impact: {impacts} · target active: {issue.get('active_for_target_server', True)} · M46 blocker: {issue.get('blocks_m46_for_target_server', False)}",
                "",
                issue["summary"],
                "",
                f"Resolution: {issue['resolution']}",
                "",
                "Evidence: " + "; ".join(f"`{x}`" for x in issue["evidence"]),
                "",
            ]
    out += ["", f"Audit result: **{'PASS' if report['ok'] else 'FAIL'}**", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=Path)
    ap.add_argument("--md-out", type=Path)
    args = ap.parse_args()
    report = inventory_report()
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload, encoding="utf-8")
    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(_markdown(report), encoding="utf-8")
    print(payload, end="")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
