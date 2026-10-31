#!/usr/bin/env python3
from __future__ import annotations

"""Build/audit-time Wowhead Forever source verifier.

Runtime simulation never imports or calls this tool.  It accepts explicit
captured entity records and can optionally perform online verification.  This
keeps refresh deliberate and reproducible rather than making live web content a
runtime dependency.
"""

import argparse
import json
from pathlib import Path
import re
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rulesets.forever.data.importers.wowhead import normalize_capture
from src.rulesets.forever.data.provenance import stable_json_fingerprint


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "mage-optimizer-source-audit/0.11.42"})
    with urllib.request.urlopen(req, timeout=20) as response:  # noqa: S310 - explicit build-time verifier
        return response.read().decode("utf-8", errors="replace")


def _verify_html(row: dict, html: str) -> list[str]:
    issues: list[str] = []
    if str(row["entity_id"]) not in html:
        issues.append("entity_id_not_observed_in_page")
    title = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if title and row["name"].lower() not in re.sub(r"\s+", " ", title.group(1)).lower():
        issues.append("page_title_name_mismatch")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="JSON array of explicit captured Wowhead entities")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--verify-online", action="store_true", help="Fetch each page now; never used by runtime")
    args = ap.parse_args()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit("input must be a JSON array")
    rows = []
    failures = 0
    for item in raw:
        row = normalize_capture(item)
        verification = {"online_checked": False, "issues": []}
        if args.verify_online:
            verification["online_checked"] = True
            try:
                verification["issues"] = _verify_html(row, _fetch(row["url"]))
            except Exception as exc:  # build-time diagnostics should be explicit
                verification["issues"] = [f"fetch_failed:{type(exc).__name__}:{exc}"]
        failures += bool(verification["issues"])
        row["verification"] = verification
        rows.append(row)
    artifact = {
        "schema": "wowhead-normalized-capture-v1",
        "rows": rows,
        "fingerprint": stable_json_fingerprint(rows),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} entities -> {args.out}; failures={failures}; fingerprint={artifact['fingerprint']}")
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
