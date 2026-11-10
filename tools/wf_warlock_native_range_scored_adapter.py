#!/usr/bin/env python3
"""Source-prepared candidate scorer adapter for the one-call native range search.

Input: one JSON optimizer request on stdin. The manifest contains *files produced
by the native source/prepare path*, not Python Warcraft build/legality rules.
Work1's existing scorer executes each selected source-prepared alternative.
Only original same-run terminal receipts can qualify for Work2's charged score.

This adapter never supplies continuity, recovery, or a fabricated winner when
native evidence is missing. It does not run a different per-level optimizer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


def _refusal(entry: dict, reason: str, source: str | None = None) -> dict:
    return {
        "status": reason, "native_prepared": False,
        "source_request_sha256": source, "candidate_id": entry.get("id"),
    }


def evaluate_request(
    request: dict, *, manifest: Path, binary: Path, target_hp: float,
    scorer_command: list[str], artifact_dir: Path,
    run_command: Callable[..., Any] = subprocess.run,
) -> list[dict]:
    """Translate Work2's frontier request to Work1's actual prepared-file scorer.

    Requiring an exact source-request file, prepared native actor and (for later
    levels) a separately recorded native continuity receipt prevents manifest
    labels from becoming fictitious lineage. No paid run starts for missing
    source or ancestry. The scorer's raw same-run native receipts are retained.
    """
    level, parent = request["level"], request["parent"]
    budget, mobs = request["budget"], request["mob_count"]
    if (type(level) is not int or not 10 <= level <= 60
            or type(mobs) is not int or not 2 <= mobs <= 100
            or type(budget) is not int or budget < 1
            or request.get("rng_mode") != "balanced"
            or request.get("iterations") != 1
            or request.get("recover_to_full") is not True
            or (parent is not None and not isinstance(parent, dict))
            or type(target_hp) not in (int, float)
            or not math.isfinite(target_hp) or target_hp <= 0
            or not scorer_command):
        raise ValueError("INVALID_NATIVE_SCORER_RANGE_REQUEST")
    source = json.loads(manifest.read_text())
    if not isinstance(source, dict) or not isinstance(source.get("entries"), list):
        raise ValueError("NATIVE_PREPARED_MANIFEST_INVALID")
    parent_sha = parent["source_request_sha256"] if parent else None
    parent_level = parent["level"] if parent else None
    if parent is not None and not _valid_sha(parent_sha):
        raise ValueError("INVALID_NATIVE_PARENT_SOURCE")
    selected = [entry for entry in source["entries"]
                if isinstance(entry, dict) and entry.get("level") == level
                and entry.get("parent_source_sha256") == parent_sha][:budget]

    refused: list[dict] = []
    candidates: dict[str, tuple[Path, dict, str, dict]] = {}
    for entry in selected:
        candidate_id = entry.get("id")
        if (not isinstance(candidate_id, str) or not candidate_id
                or not all(c.isascii() and (c.isalnum() or c in "-_")
                           for c in candidate_id) or candidate_id in candidates):
            refused.append(_refusal(entry, "INVALID_OR_DUPLICATE_NATIVE_CANDIDATE_ID"))
            continue
        try:
            prepared_path = manifest.parent / entry["prepared"]
            source_path = manifest.parent / entry["source_request"]
            prepared = json.loads(prepared_path.read_text())
            native_source_sha = _sha(source_path)
            actor = prepared["player"]
            if (prepared.get("request_sha256") != native_source_sha
                    or actor.get("class") != "ClassWarlock"
                    or actor.get("level") != level):
                raise ValueError("NATIVE_PREPARED_SOURCE_IDENTITY_MISMATCH")
            lineage: dict = {}
            if parent is not None:
                # This must be a separately emitted native source/continuity
                # receipt, NEVER a flag copied from the optimizer's parent.
                lineage = json.loads(
                    (manifest.parent / entry["native_continuity_receipt"]).read_text())
                if (lineage.get("source_request_sha256") != native_source_sha
                        or lineage.get("native_parent_source_sha256") != parent_sha
                        or lineage.get("native_continuity_from_level") != parent_level
                        or lineage.get("native_continuity_ack") is not True
                        or (level > parent_level + 1
                            and lineage.get("native_intermediate_levels_verified")
                            is not True)):
                    raise ValueError("NATIVE_SOURCE_CONTINUITY_NOT_RECORDED")
            candidates[candidate_id] = (prepared_path, prepared, native_source_sha, lineage)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            refused.append(_refusal(entry, "NATIVE_PREPARED_OR_CONTINUITY_REFUSAL:"
                                    + str(exc)[-180:], None))
    # Work1's comparator requires two distinct prepared alternatives. Paying a
    # single first-preparable candidate would be baseline work, not optimization.
    if len(candidates) < 2:
        return refused + [
            _refusal({"id": cid}, "NOT_COMPETITIVE_NATIVE_PREPARED_FRONTIER", src)
            for cid, (_, _, src, _) in candidates.items()
        ]

    artifact_dir.mkdir(parents=True, exist_ok=True)
    # Never reuse files from another invocation: a stale native JSON file must
    # not be mistaken for the scorer's just-executed full-resource ACK.
    import tempfile
    call_dir = Path(tempfile.mkdtemp(prefix=f"level-{level}-native-", dir=artifact_dir))
    command = [*scorer_command, "--binary", str(binary),
               "--level", str(level), "--mob-count", str(mobs),
               "--target-hp", str(target_hp), "--out", str(call_dir)]
    for cid, (path, _, _, _) in candidates.items():
        command.extend(["--prepared", f"{cid}={path}"])
    completed = run_command(command, capture_output=True, text=True,
                            timeout=1800, check=False)
    if completed.returncode:
        return refused + [
            _refusal({"id": cid}, "NATIVE_SCORER_EXIT_"
                     + str(completed.returncode) + ":" + completed.stderr[-200:], src)
            for cid, (_, _, src, _) in candidates.items()
        ]
    try:
        screen = json.loads(completed.stdout)
        measured = {row["candidate_id"]: row for row in screen["candidates"]}
        if len(measured) != len(screen["candidates"]):
            raise ValueError("duplicate source scorer candidate ID")
    except (KeyError, ValueError, TypeError) as exc:
        return refused + [
            _refusal({"id": cid}, "NATIVE_SCORER_PAYLOAD_INVALID:" + str(exc)[-150:], src)
            for cid, (_, _, src, _) in candidates.items()
        ]

    engine_sha = _sha(binary)
    rows: list[dict] = list(refused)
    for cid, (path, prepared, src, lineage) in candidates.items():
        comparison = measured.get(cid, {})
        try:
            if comparison.get("status") != "MEASURED_NATIVE_FULLY_RECOVERED":
                raise ValueError("NATIVE_SCORER_STATUS:"
                                 + str(comparison.get("status", "NOT_RECORDED")))
            if (comparison.get("prepared_sha256") != _sha(path)
                    or comparison.get("source_sha256") != src
                    or comparison.get("mob_count") != mobs
                    or comparison.get("rng_mode") != "balanced"
                    or comparison.get("iterations") != 1):
                raise ValueError("NATIVE_SCORER_SOURCE_OR_SCENARIO_MISMATCH")
            raw = json.loads((call_dir / f"{cid}.native.json").read_text())
            terminal = raw["native_terminal_recovery"]
            stats = prepared["player"]["stats"]
            start_ns, end_ns = terminal["start_clock_ns"], terminal["end_clock_ns"]
            elapsed = comparison["elapsed_seconds"]
            if (type(start_ns) is not int or type(end_ns) is not int
                    or end_ns < start_ns or not isinstance(elapsed, (int, float))
                    or not math.isfinite(elapsed)
                    or not math.isclose(elapsed, end_ns / 1e9, abs_tol=1e-6)
                    or raw.get("source_sha256") != src):
                raise ValueError("NATIVE_RECOVERY_SOURCE_OR_CLOCK_MISMATCH")
            rows.append({
                "status": comparison["status"], "candidate_id": cid,
                "level": level, "mob_count": mobs,
                "targets_killed": raw.get("world_targets_killed"),
                "rng_mode": "balanced", "iterations": 1,
                "native_prepared": True,
                "native_world_ack": raw.get("actual_2d_ack") is True,
                "source_request_sha256": src, "engine_binary_sha256": engine_sha,
                "native_full_recovery_paid": terminal.get("paid") is True
                    and terminal.get("native_clock_accounted") is True,
                "recover_to_full": True,
                "terminal_hp": terminal.get("health_after"),
                "terminal_max_hp": stats.get("Health"),
                "terminal_mana": terminal.get("mana_after"),
                "terminal_max_mana": stats.get("Mana"),
                "elapsed_seconds": elapsed,
                "terminal_recovery_seconds": (end_ns - start_ns) / 1e9,
                "native_parent_source_sha256":
                    lineage.get("native_parent_source_sha256"),
                "native_continuity_ack": lineage.get("native_continuity_ack"),
                "native_continuity_from_level":
                    lineage.get("native_continuity_from_level"),
                "native_intermediate_levels_verified":
                    lineage.get("native_intermediate_levels_verified"),
                "native_raw_receipt_file": str(call_dir / f"{cid}.native.json"),
                "prepared_file": str(path),
            })
        except (KeyError, ValueError, TypeError, OSError) as exc:
            rows.append(_refusal({"id": cid}, "NATIVE_SCORER_RECEIPT_REFUSAL:"
                                 + str(exc)[-180:], src))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--target-hp", type=float, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--scorer-command", required=True,
                        help="Work1's tools/wf_warlock_native_candidate_scoring.py command")
    args = parser.parse_args(argv)
    import shlex
    req = json.load(sys.stdin)
    result = evaluate_request(
        req, manifest=args.manifest, binary=args.binary, target_hp=args.target_hp,
        scorer_command=shlex.split(args.scorer_command), artifact_dir=args.artifact_dir)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
