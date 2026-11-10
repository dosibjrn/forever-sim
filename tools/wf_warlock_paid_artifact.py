#!/usr/bin/env python3
"""Stage one exact paid Warlock predecessor pair from an Actions artifact.

This only locates source/route files. The paid-range producer itself must still
verify native binary, source/request and 100/100 ACK before spending or reusing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def restore_resume_cache(archive_dir: Path, from_level: int, out: Path) -> dict:
    """Restore a same-origin paid-range cache from an earlier Actions artifact.

    This only transports prior files; wf_warlock_paid_range independently
    verifies the predecessor/source/binary and each native paid receipt before
    considering a level reusable. No unsupported Warcraft facts are inferred.
    """
    matches = []
    for marker in archive_dir.rglob("range_progress.json"):
        if marker.parent.name != "warlock-paid-range":
            continue
        progress = json.loads(marker.read_text())
        if (isinstance(progress, dict)
                and progress.get("kind") == "warlock_native_paid_range_v1"
                and progress.get("from_level") == from_level):
            matches.append(marker.parent)
    if len(matches) > 1:
        raise ValueError(f"ambiguous same-origin paid range caches: {len(matches)}")
    if not matches:
        return {"restored": False}
    if out.exists():
        raise ValueError(f"resume output already exists: {out}")
    shutil.copytree(matches[0], out)
    return {"restored": True, "original": str(matches[0])}


def stage(archive_dir: Path, from_level: int, out: Path,
          resume_cache_out: Path | None = None) -> dict:
    if not 10 <= from_level < 60:
        raise ValueError("predecessor level must be L10..L59")
    if not archive_dir.is_dir():
        raise ValueError("extracted predecessor artifact does not exist")

    pairs = []
    for source in archive_dir.rglob("source_request.json"):
        if source.parent.name != "proposal" or f"L{from_level}" not in source.parts:
            continue
        route = source.parent.parent / "paid" / "route.json"
        if route.is_file():
            pairs.append((source, route))

    # Retain the original paid source when retrying a prior parameterized range.
    # A range artifact includes a copy of its starting source and route.
    for manifest in archive_dir.rglob("predecessor_manifest.json"):
        info = json.loads(manifest.read_text())
        if isinstance(info, dict) and info.get("from_level") == from_level:
            source = manifest.parent / "source_request.json"
            route = manifest.parent / "route.json"
            if source.is_file() and route.is_file():
                pairs.append((source, route))

    # Legacy L42 artifact has a separately named source and paid-route folder.
    if from_level == 42 and not pairs:
        for parent in (archive_dir, archive_dir / "predecessor"):
            source = parent / "warlock-l42-source" / "source_request.json"
            route = parent / "warlock-l42-native-route" / "route.json"
            if source.is_file() and route.is_file():
                pairs.append((source, route))

    if len(pairs) != 1:
        raise ValueError(
            f"expected exactly one paid L{from_level} source/route pair; "
            f"found {len(pairs)}. Do not infer or invent a predecessor."
        )

    source, route = pairs[0]
    for path in (source, route):
        if not isinstance(json.loads(path.read_text()), dict):
            raise ValueError(f"non-object source/route JSON: {path}")
    out.mkdir(parents=True, exist_ok=True)
    staged_source = out / "source_request.json"
    staged_route = out / "route.json"
    shutil.copyfile(source, staged_source)
    shutil.copyfile(route, staged_route)
    result = {
        "from_level": from_level,
        "source_original": str(source),
        "route_original": str(route),
        "source_sha256": hashlib.sha256(staged_source.read_bytes()).hexdigest(),
        "route_sha256": hashlib.sha256(staged_route.read_bytes()).hexdigest(),
    }
    if resume_cache_out is not None:
        result["resume_cache"] = restore_resume_cache(
            archive_dir, from_level, resume_cache_out)
    (out / "predecessor_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--from-level", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resume-cache-out", type=Path,
                        help="Reuse a same-origin paid-range cache from the artifact")
    args = parser.parse_args()
    print(json.dumps(stage(args.archive_dir, args.from_level, args.out,
                           resume_cache_out=args.resume_cache_out), indent=2))


if __name__ == "__main__":
    main()
