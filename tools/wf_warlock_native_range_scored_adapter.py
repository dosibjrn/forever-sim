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


def _requested_source_build(source_path: Path) -> dict:
    """Forward original native-request choices, never infer game legality.

    Source SHA and prepared actor identity are checked by the caller before
    these requested (not independently verified as executed) fields are used.
    Historical minimal source fixtures may not include a full raid/player.
    """
    source = json.loads(source_path.read_text())
    try:
        actor = source["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError):
        return {}
    if not isinstance(actor, dict):
        return {}
    warlock = actor.get("warlock")
    options = warlock.get("options") if isinstance(warlock, dict) else None
    class_options = options.get("classOptions") if isinstance(options, dict) else None
    return {
        "talents": actor.get("talentsString"),
        "pet": class_options.get("summon") if isinstance(class_options, dict) else None,
        "gear": actor.get("equipment"),
        "apl": actor.get("rotation"),
    }


def evaluate_request(
    request: dict, *, manifest: Path, binary: Path, target_hp: float,
    scorer_command: list[str], artifact_dir: Path,
    paid_cache_dir: Path | None = None,
    run_command: Callable[..., Any] = subprocess.run,
    run_native_single: Callable[..., Any] | None = None,
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
    # Live Rust source/prepare reports its exact executable identity. Do not
    # spend native world combat with a different binary than the one that
    # prepared these candidates. Older prebuilt manifests without this field
    # remain supported; the live producer always supplies it.
    producer_engine = source.get("native_binary_sha256")
    if producer_engine is not None and (
            not _valid_sha(producer_engine)
            or not binary.is_file()
            or producer_engine != _sha(binary)):
        raise ValueError("NATIVE_FRONTIER_SCORER_ENGINE_MISMATCH")
    parent_sha = parent["source_request_sha256"] if parent else None
    parent_level = parent["level"] if parent else None
    if parent is not None and not _valid_sha(parent_sha):
        raise ValueError("INVALID_NATIVE_PARENT_SOURCE")
    native_refusals = source.get("refusals", [])
    if not isinstance(native_refusals, list) or any(
            not isinstance(row, dict) for row in native_refusals):
        raise ValueError("NATIVE_PREPARED_MANIFEST_REFUSALS_INVALID")
    # Reusable manifests may combine several sampled levels or different
    # continuing parents. A refusal spends only the request that produced it,
    # just as a prepared entry does. Historical single-request manifests omit
    # row scope; inherit the manifest scope (or this request as a legacy case).
    # Newly produced native refusals carry both fields explicitly.
    scoped_refusals = [
        row for row in native_refusals
        if row.get("level", source.get("level", level)) == level
        and row.get("parent_source_sha256",
                    source.get("parent_source_sha256", parent_sha)) == parent_sha
    ]
    if len(scoped_refusals) > budget:
        raise ValueError("NATIVE_FRONTIER_EXCEEDS_CANDIDATE_BUDGET")
    # Count every already-prepared matching attempt, never silently slice it.
    # Unrelated levels/parents in a reusable manifest do not spend this budget.
    selected = [entry for entry in source["entries"]
                if isinstance(entry, dict) and entry.get("level") == level
                and entry.get("parent_source_sha256") == parent_sha]
    if len(selected) + len(scoped_refusals) > budget:
        raise ValueError("NATIVE_FRONTIER_EXCEEDS_CANDIDATE_BUDGET")

    # A native producer can fail to prepare a proposal before the paid scorer
    # sees it. Preserve that exact refusal as a budgeted attempt; never drop it
    # or upgrade it into a paid candidate.
    refused: list[dict] = [
        {"status": row.get("status", "NATIVE_FRONTIER_REFUSED"),
         "candidate_id": row.get("candidate_id"), "native_prepared": False,
         "native_refusal": row.get("native_refusal"),
         "source_request_sha256": row.get("source_request_sha256")}
        for row in scoped_refusals
    ]
    candidates: dict[str, tuple[Path, dict, str, dict]] = {}
    requested_builds: dict[str, dict] = {}
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
                # This must be a separately recorded native-prepared source
                # chain, NEVER a flag copied from the optimizer's parent.
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
                if lineage.get("scope") == (
                        "source-native prepared build lineage, not world XP/travel"):
                    # Re-read the Rust prepare artifacts; a manifest boolean
                    # or skipped intermediate file cannot authorize a paid edge.
                    if (lineage.get("native_engine_binary_sha256") != _sha(binary)
                            or lineage.get("native_parent_raw_receipt_sha256")
                            != _sha(Path(parent["native_raw_receipt_file"]))):
                        raise ValueError("NATIVE_SOURCE_CHAIN_PARENT_OR_ENGINE_MISMATCH")
                    trail = lineage.get("infill")
                    if (not isinstance(trail, list)
                            or [step.get("level") for step in trail
                                if isinstance(step, dict)]
                            != list(range(parent_level + 1, level))):
                        raise ValueError("NATIVE_SOURCE_CHAIN_INCOMPLETE_LEVELS")
                    for step in trail:
                        request_path = Path(step["source_request"])
                        prepared_step_path = Path(step["prepared"])
                        if (_sha(request_path) != step.get("source_request_sha256")
                                or _sha(prepared_step_path) != step.get("prepared_sha256")):
                            raise ValueError("NATIVE_SOURCE_CHAIN_FILE_IDENTITY_MISMATCH")
                        prepared_step = json.loads(prepared_step_path.read_text())
                        source_step = json.loads(request_path.read_text())
                        if (prepared_step.get("request_sha256")
                                != step["source_request_sha256"]
                                or prepared_step["player"].get("class") != "ClassWarlock"
                                or prepared_step["player"].get("level") != step["level"]
                                or source_step["raid"]["parties"][0]["players"][0].get("level")
                                != step["level"]
                                or source_step["encounter"]["targets"][0].get("level")
                                != step["level"]):
                            raise ValueError("NATIVE_SOURCE_CHAIN_PREPARE_IDENTITY_MISMATCH")
            requested_builds[candidate_id] = _requested_source_build(source_path)
            candidates[candidate_id] = (prepared_path, prepared, native_source_sha, lineage)
        except (KeyError, ValueError, TypeError, OSError) as exc:
            refused.append(_refusal(entry, "NATIVE_PREPARED_OR_CONTINUITY_REFUSAL:"
                                    + str(exc)[-180:], None))
    # Independent anchors may have only one Rust-preparable build after
    # alternative native refusals. Score that bounded anchor, but leave it
    # noncompetitive/provisional instead of silently losing its measurement.
    # Continuing root bootstrap still requires genuine alternatives.
    if not candidates or (len(candidates) == 1 and parent is None
                          and request.get("search_mode") != "independent"):
        return refused + [
            _refusal({"id": cid}, "NOT_COMPETITIVE_NATIVE_PREPARED_FRONTIER", src)
            for cid, (_, _, src, _) in candidates.items()
        ]

    artifact_dir.mkdir(parents=True, exist_ok=True)
    # Never reuse files from another invocation: a stale native JSON file must
    # not be mistaken for the scorer's just-executed full-resource ACK.
    import tempfile
    call_dir = Path(tempfile.mkdtemp(prefix=f"level-{level}-native-", dir=artifact_dir))
    if len(candidates) == 1:
        # A single source-prepared independent anchor still pays native
        # combat, but must share the same exact ACK cache as multi-candidate
        # frontiers. No second, uncached native runner for this case.
        from tools.wf_warlock_native_candidate_scoring import compare_prepared_candidates
        cid, (path, _, _, _) = next(iter(candidates.items()))
        screen = compare_prepared_candidates(
            binary=binary, prepared_paths={cid: path}, actor_level=level,
            mob_count=mobs, target_hp=target_hp, run_native=run_native_single,
            artifact_dir=call_dir, paid_cache_dir=paid_cache_dir)
        measured = {row["candidate_id"]: row for row in screen["candidates"]}
    else:
        command = [*scorer_command, "--binary", str(binary),
                   "--level", str(level), "--mob-count", str(mobs),
                   "--target-hp", str(target_hp), "--out", str(call_dir)]
        for cid, (path, _, _, _) in candidates.items():
            command.extend(["--prepared", f"{cid}={path}"])
        if paid_cache_dir is not None:
            command.extend(["--paid-cache-dir", str(paid_cache_dir)])
        try:
            completed = run_command(command, capture_output=True, text=True,
                                    timeout=1800, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return refused + [
                _refusal({"id": cid}, "NATIVE_SCORER_TRANSPORT_ERROR:"
                         + str(exc)[-200:], src)
                for cid, (_, _, src, _) in candidates.items()
            ]
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
                _refusal({"id": cid}, "NATIVE_SCORER_PAYLOAD_INVALID:"
                         + str(exc)[-150:], src)
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
            # Work1 may reuse an exact paid receipt under its original label
            # rather than write a duplicate file in this invocation's call_dir.
            # Honor that original only when its scorer-supplied digest matches
            # the actual immutable paid bytes; otherwise refuse to rank it.
            original_file = comparison.get("native_raw_receipt_file")
            if original_file is not None:
                if not isinstance(original_file, str) or not original_file:
                    raise ValueError("NATIVE_SCORER_ORIGINAL_RECEIPT_PATH_INVALID")
                raw_path = Path(original_file)
                digest = comparison.get("native_raw_receipt_sha256")
                if not _valid_sha(digest) or digest != _sha(raw_path):
                    raise ValueError("NATIVE_SCORER_ORIGINAL_RECEIPT_DIGEST_MISMATCH")
            else:
                # Historical scorers only returned a same-invocation file.
                raw_path = call_dir / f"{cid}.native.json"
            raw = json.loads(raw_path.read_text())
            terminal = raw["native_terminal_recovery"]
            start_ns, end_ns = terminal["start_clock_ns"], terminal["end_clock_ns"]
            elapsed = comparison["elapsed_seconds"]
            # Never relabel prepared base stats as full live resources: source
            # buffs and effects can change the actual Rust actor capacities.
            max_hp, max_mana = terminal.get("max_health"), terminal.get("max_mana")
            if (type(start_ns) is not int or type(end_ns) is not int
                    or end_ns < start_ns or not isinstance(elapsed, (int, float))
                    or not math.isfinite(elapsed)
                    or not math.isclose(elapsed, end_ns / 1e9, abs_tol=1e-6)
                    or raw.get("source_sha256") != src):
                raise ValueError("NATIVE_RECOVERY_SOURCE_OR_CLOCK_MISMATCH")
            if (any(type(n) not in (int, float) or not math.isfinite(n)
                    or n <= 0 for n in (max_hp, max_mana))
                    or not all(type(terminal.get(key)) in (int, float)
                               and math.isfinite(terminal[key]) for key in
                               ("health_after", "mana_after"))
                    or not math.isclose(terminal["health_after"], max_hp, abs_tol=1e-6)
                    or not math.isclose(terminal["mana_after"], max_mana, abs_tol=1e-6)):
                raise ValueError("NATIVE_TERMINAL_CAPACITY_NOT_FULL")
            rows.append({
                "status": comparison["status"], "candidate_id": cid,
                # Exact requested build, preserved from the hash-matched native
                # source rather than silently published as unknown/null.
                **requested_builds[cid],
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
                "terminal_max_hp": max_hp,
                "terminal_mana": terminal.get("mana_after"),
                "terminal_max_mana": max_mana,
                "elapsed_seconds": elapsed,
                "terminal_recovery_seconds": (end_ns - start_ns) / 1e9,
                "native_parent_source_sha256":
                    lineage.get("native_parent_source_sha256"),
                "native_continuity_ack": lineage.get("native_continuity_ack"),
                "native_continuity_from_level":
                    lineage.get("native_continuity_from_level"),
                "native_intermediate_levels_verified":
                    lineage.get("native_intermediate_levels_verified"),
                "native_raw_receipt_file": str(raw_path),
                "native_raw_receipt_sha256": _sha(raw_path),
                "reused_exact_native_paid_receipt":
                    comparison.get("reused_exact_native_paid_receipt") is True,
                "prepared_file": str(path),
                "source_request_file": str(
                    (manifest.parent / next(
                        entry["source_request"] for entry in selected
                        if entry["id"] == cid)).resolve()),
            })
        except (KeyError, ValueError, TypeError, OSError) as exc:
            refusal = _refusal({"id": cid}, "NATIVE_SCORER_RECEIPT_REFUSAL:"
                               + str(exc)[-180:], src)
            if comparison.get("refusal") is not None:
                refusal["native_refusal"] = str(comparison["refusal"])[-1500:]
            rows.append(refusal)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--target-hp", type=float, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--paid-cache-dir", type=Path,
                        help="Shared exact-input cache for repeat frontier calls")
    parser.add_argument("--scorer-command", required=True,
                        help="Work1's tools/wf_warlock_native_candidate_scoring.py command")
    args = parser.parse_args(argv)
    import shlex
    req = json.load(sys.stdin)
    result = evaluate_request(
        req, manifest=args.manifest, binary=args.binary, target_hp=args.target_hp,
        scorer_command=shlex.split(args.scorer_command), artifact_dir=args.artifact_dir,
        paid_cache_dir=args.paid_cache_dir)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
