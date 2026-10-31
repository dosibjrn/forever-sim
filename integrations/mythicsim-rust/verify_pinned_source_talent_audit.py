#!/usr/bin/env python3
"""Replay 28 pinned fixture blob/talent identities; never claim native scores.

The evidence ledger's Git blob SHA1 is checked against the actual bytes of
each gsim or pinned MythicSim engine request. This is source provenance ONLY,
not rank/prerequisite legality, a Rust invocation, or PROCESS P7 acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path


class SourceAuditError(ValueError):
    """An exact source fixture or the evidence ledger is inconsistent."""


def _require(ok: bool, profile: str, field: str, detail: str = "") -> None:
    if not ok:
        raise SourceAuditError(f"{profile}: {field} mismatch {detail}".strip())


def verify_row(row: dict, *, repo_root: Path, engine_src: Path) -> tuple[str, str, int]:
    """Check source bytes, class identity, talents and point metadata."""
    profile = row["profile_id"]
    cls = profile.split("/", 1)[0]
    repository = row["source_repository"]
    if repository == "dosibjrn/mage-level-sim":
        root = repo_root.resolve()
    elif repository == "sage3648/mythicsim-forever-engine":
        root = engine_src.resolve()
    else:
        raise SourceAuditError(f"{profile}: unrecognized source_repository {repository}")
    path = (root / row["source_path"]).resolve()
    _require(path.is_relative_to(root), profile, "source_path", "(escapes source root)")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SourceAuditError(f"{profile}: source_path unreadable: {exc}") from exc
    git_blob = hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()
    _require(git_blob == row["git_blob_sha1"], profile, "git_blob_sha1")
    try:
        request = json.loads(data)
        player = request["raid"]["parties"][0]["players"][0]
        actual_class = player["class"]
        talents = player["talentsString"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise SourceAuditError(f"{profile}: malformed native request: {exc}") from exc
    _require(actual_class == "Class" + cls.capitalize(),
             profile, "class identity", f"({actual_class})")
    _require(talents == row["source_talent_string"], profile, "source_talent_string")
    _require(isinstance(talents, str)
             and talents.count("-") in (1, 2)
             and all(ch in "0123456789-" for ch in talents),
             profile, "talent encoding")
    points = sum(int(ch) for ch in talents if ch != "-")
    _require(points == row["source_talent_points"], profile, "source_talent_points")
    _require(max(0, 51 - points) == row["points_missing_to_51"],
             profile, "points_missing_to_51")
    status = "POINTS_51_UNVERIFIED_TREE" if points == 51 else (
        "INCOMPLETE_51" if points < 51 else "OVERALLOCATED_51")
    _require(row["point_total_status"] == status, profile, "point_total_status")
    return cls, talents, points


def verify_audit(audit: dict, *, repo_root: Path, engine_src: Path) -> dict:
    """Verify every row and aggregate census, without manufacturing fixtures."""
    rows = audit["rows"]
    profiles = [r["profile_id"] for r in rows]
    _require(len(rows) == 28 and len(set(profiles)) == 28,
             "inventory", "28 unique profiles")
    donors: dict[str, set[str]] = defaultdict(set)
    incomplete = []
    classes = set()
    mage_census = 0
    for row in rows:
        cls, talents, points = verify_row(
            row, repo_root=repo_root, engine_src=engine_src)
        classes.add(cls)
        if points == 51:
            donors[cls].add(talents)
        else:
            incomplete.append({
                "profile_id": row["profile_id"],
                "points": points,
                "missing": max(0, 51 - points),
            })
        if (cls == "mage" and points == 51 and
                row["source_path"].startswith("validation/2026-10-04-mage-census/bases/")):
            mage_census += 1
    summary = audit["summary"]
    _require(len(classes) == 9, "inventory", "nine classes")
    expected = {
        "rows": 28,
        "classes": len(classes),
        "source_requests_read": len(rows),
        "point_total_51": len(rows) - len(incomplete),
        "incomplete_point_totals": len(incomplete),
        "distinct_51_point_donor_builds_by_class": {
            cls: len(donors[cls]) for cls in sorted(classes)
        },
        "mage_census_51_point_smoke_sources": mage_census,
    }
    for key, value in expected.items():
        _require(summary.get(key) == value, "inventory", key)
    _require(sorted(summary["non_51_profiles"], key=lambda x: x["profile_id"])
             == sorted(incomplete, key=lambda x: x["profile_id"]),
             "inventory", "non_51_profiles")
    for row in rows:
        cls = row["profile_id"].split("/", 1)[0]
        _require(row["same_class_51_point_donor_builds"] == len(donors[cls]),
                 row["profile_id"], "same_class_51_point_donor_builds")
    return {"rows": len(rows), "classes": len(classes),
            "point_total_51": len(rows) - len(incomplete),
            "incomplete": incomplete, "mage_census": mage_census,
            "scope": "SOURCE_BYTES_AND_POINT_TOTAL_ONLY_NOT_NATIVE_SIMULATION"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", required=True, type=Path)
    ap.add_argument("--engine-src", required=True, type=Path)
    ap.add_argument("--audit", required=True, type=Path)
    args = ap.parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    actual_revision = subprocess.check_output(
        ["git", "-C", str(args.engine_src), "rev-parse", "HEAD"],
        text=True).strip()
    _require(actual_revision == audit["engine_commit"],
             "engine", "engine_commit")
    print(json.dumps(verify_audit(
        audit, repo_root=args.repo_root, engine_src=args.engine_src),
        sort_keys=True))


if __name__ == "__main__":
    main()
