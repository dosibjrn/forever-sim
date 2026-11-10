#!/usr/bin/env python3
"""Propose a same-level Warlock source actor using actual Rust prepare receipts.

The existing L20 winner fixture can contain gear the selected native level
source refuses. Do not interpret item stats in Python: try the original actor,
then native-prepare an empty loadout and greedily re-add equipped slots. The
Rust prepare verdict, not a Python item database, decides every candidate.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import subprocess
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_prepared_source(*, binary: Path, source: Path, out: Path,
                           actor_level: int = 20, mob_count: int | None = None,
                           target_hp: float | None = None,
                           max_scored_candidates: int = 4) -> dict:
    """Prepare a source candidate, or score distinct native preparations when opted in.

    Paid mode never returns an unmeasured first-preparable build as a winner.
    The source-native scorer, not equipment order or 30-second DPS, selects
    by the real world ACK clock including terminal full-resource recovery.
    """
    if not 10 <= actor_level <= 60 or not binary.is_file() or not source.is_file():
        raise ValueError("existing native binary/source and actor level 10..60 required")
    if mob_count is None:
        if target_hp is not None:
            raise ValueError("target_hp requires mob_count")
    elif (type(mob_count) is not int or not 2 <= mob_count <= 100
          or type(target_hp) not in (int, float)
          or not math.isfinite(target_hp) or target_hp <= 0
          or type(max_scored_candidates) is not int
          or not 2 <= max_scored_candidates <= 16):
        raise ValueError("paid mode requires 2..100 mobs, positive native target HP and 2..16 candidates")
    original = json.loads(source.read_text())
    actor = original["raid"]["parties"][0]["players"][0]
    if (actor.get("class") != "ClassWarlock"
            or actor.get("race") != "RaceTroll"
            or original["encounter"]["targets"][0].get("level") != actor_level):
        raise ValueError("source actor class/race/encounter level mismatch")
    items = actor.get("equipment", {}).get("items")
    if not isinstance(items, list):
        raise ValueError("native source request lacks occupied-slot proposals")
    out.mkdir(parents=True, exist_ok=True)
    attempts = out / "native_prepare_attempts"
    attempts.mkdir(exist_ok=True)
    refusals: list[dict] = []
    accepted = []
    accepted_request_paths: dict[str, Path] = {}
    accepted_prepared_paths: dict[str, Path] = {}

    def ask_native(tag: str, equipment: list[dict]) -> Path | None:
        request = copy.deepcopy(original)
        request["raid"]["parties"][0]["players"][0]["equipment"]["items"] = (
            copy.deepcopy(equipment))
        request_path = attempts / f"{tag}.json"
        prepared_path = attempts / f"{tag}.prepared.json"
        request_path.write_text(json.dumps(request, indent=2) + "\n")
        process = subprocess.run(
            # Explicitly forward the selected level to the repaired native
            # Rust prepare CLI. The engine verifies it agrees with the source
            # player level; do not silently prepare a default L60 actor.
            [str(binary.resolve()), "prepare", "--request",
             str(request_path.resolve()), "--actor-level", str(actor_level),
             "--outfile", str(prepared_path.resolve())],
            capture_output=True, text=True, timeout=60, check=False)
        if process.returncode:
            refusals.append({"candidate": tag, "status": "NATIVE_PREPARE_REFUSED",
                             "reason": (process.stderr or process.stdout)[-1500:]})
            return None
        try:
            prepared = json.loads(prepared_path.read_text())["player"]
        except (OSError, ValueError, KeyError, TypeError):
            refusals.append({"candidate": tag,
                             "status": "NATIVE_PREPARED_ACTOR_MISSING"})
            return None
        if (prepared.get("class") != "ClassWarlock"
                or prepared.get("race") != "RaceTroll"
                or prepared.get("level") != actor_level):
            refusals.append({"candidate": tag,
                             "status": "NATIVE_PREPARED_ACTOR_IDENTITY_MISMATCH"})
            return None
        accepted.append({"candidate": tag, "request_sha256": _sha256(request_path),
                         "prepared_sha256": _sha256(prepared_path)})
        accepted_request_paths[tag] = request_path
        accepted_prepared_paths[tag] = prepared_path
        return request_path

    selected = ask_native("full", items)
    kept_slots: list[int] = list(range(len(items))) if selected else []
    if selected is None:
        # Rust, not Forever, decides whether even the gearless source can be
        # prepared. An empty-source refusal must remain an explicit refusal.
        chosen = [{"id": 0} for _ in items]
        selected = ask_native("empty", chosen)
        if selected is not None:
            for index, item in enumerate(items):
                proposal = copy.deepcopy(chosen)
                proposal[index] = copy.deepcopy(item)
                native_selected = ask_native(f"slot_{index:02d}", proposal)
                if native_selected is not None:
                    chosen = proposal
                    selected = native_selected
                    kept_slots.append(index)

    # The older source-only path retains its no-payment behavior. Explicit
    # scored mode must explore competitors even when "full" was preparable:
    # first preparable is a baseline, never evidence of fastest leveling.
    if mob_count is not None and "full" in accepted_request_paths:
        ask_native("empty", [{"id": 0} for _ in items])
        for index, item in enumerate(items):
            if len(accepted_prepared_paths) >= max_scored_candidates + 2:
                break
            if item.get("id", 0) == 0:
                continue
            reduced = copy.deepcopy(items)
            reduced[index] = {"id": 0}
            ask_native(f"without_slot_{index:02d}", reduced)

    paid_comparison = None
    selected_candidate_id = None
    if mob_count is not None and accepted_prepared_paths:
        # Favor broad baselines and the latest source-accepted gear mutation.
        # The native scorer separately rejects duplicate preparations/refusals.
        priority = ["full", "empty", *reversed(accepted_prepared_paths)]
        shortlist: dict[str, Path] = {}
        for tag in priority:
            if tag in accepted_prepared_paths and tag not in shortlist:
                shortlist[tag] = accepted_prepared_paths[tag]
            if len(shortlist) >= max_scored_candidates:
                break
        from tools.wf_warlock_native_candidate_scoring import compare_prepared_candidates
        paid_comparison = compare_prepared_candidates(
            binary=binary, prepared_paths=shortlist, actor_level=actor_level,
            mob_count=mob_count, target_hp=float(target_hp),
            artifact_dir=out / "native_paid")
        measured = sorted(
            (row for row in paid_comparison["candidates"]
             if row.get("status") == "MEASURED_NATIVE_FULLY_RECOVERED"
             and row.get("elapsed_seconds") is not None),
            key=lambda row: (row["elapsed_seconds"], row["candidate_id"]))
        # One measured actor may be a usable baseline, not an optimized winner.
        # No measured native terminal recovery means no publishable selection.
        if measured:
            selected_candidate_id = measured[0]["candidate_id"]
            selected = accepted_request_paths[selected_candidate_id]
            selected_items = json.loads(selected.read_text())[
                "raid"]["parties"][0]["players"][0]["equipment"]["items"]
            kept_slots = [
                index for index, item in enumerate(items)
                if item.get("id", 0) and selected_items[index] == item]
        else:
            selected = None

    status = ("NATIVE_PREPARED_NOT_YET_PAID" if selected else
              "NATIVE_PREPARE_REFUSED_ALL_SOURCES")
    if mob_count is not None and accepted_prepared_paths:
        status = ("NATIVE_PAID_BOUNDED_COMPARISON" if paid_comparison[
            "comparable_candidates"] >= 2 else
                  "NATIVE_PAID_SINGLE_BASELINE" if selected is not None else
                  "NATIVE_PAID_NO_FULLY_RECOVERED_CANDIDATE")

    receipt = {
        "kind": "warlock_native_same_level_equipment_proposal",
        "status": status,
        "actor_level": actor_level,
        "native_binary_sha256": _sha256(binary),
        "original_source_sha256": _sha256(source),
        "proposals_prepared": len(accepted),
        "proposals_refused": len(refusals),
        "kept_equipment_slots": kept_slots,
        "native_refusals": refusals,
        "native_accepted": accepted,
    }
    if mob_count is not None:
        receipt.update(mob_count=mob_count, target_hp=target_hp,
                       rng_mode="balanced", iterations=1,
                       recover_to_full=True,
                       max_scored_candidates=max_scored_candidates,
                       selected_candidate_id=selected_candidate_id,
                       native_paid_comparison=paid_comparison)
    if selected is not None:
        final = out / "source_request.json"
        final.write_bytes(selected.read_bytes())
        receipt["selected_source_sha256"] = _sha256(final)
        receipt["next_step"] = (
            "reuse original recovered native candidate receipts in range optimizer"
            if mob_count is not None else
            "evaluate source-prepared candidate using hostile native world scorer")
    (out / "proposal.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--actor-level", type=int, default=20)
    parser.add_argument("--mob-count", type=int,
                        help="Opt into real native 2..100 hostile ACK scoring")
    parser.add_argument("--target-hp", type=float,
                        help="Native world target HP for charged candidate comparison")
    parser.add_argument("--max-scored-candidates", type=int, default=4)
    args = parser.parse_args()
    receipt = select_prepared_source(
        binary=args.binary, source=args.source, out=args.out,
        actor_level=args.actor_level, mob_count=args.mob_count,
        target_hp=args.target_hp,
        max_scored_candidates=args.max_scored_candidates)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if receipt["status"] in {
        "NATIVE_PREPARED_NOT_YET_PAID", "NATIVE_PAID_BOUNDED_COMPARISON",
        "NATIVE_PAID_SINGLE_BASELINE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
