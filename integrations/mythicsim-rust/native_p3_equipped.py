"""Bounded real selected-Rust equipped-item P3 comparison.

The source-native item-options response supplies item proposals. The selected
native simulator alone decides whether a full equipped request is executable
and whether the item changes the paid objective. No Python game legality,
combat formula, synthetic stat witness, or gate PASS is produced here.
"""
from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
import subprocess
import time
from pathlib import Path

from native_executor import run, NativeExecutionError
from native_matrix import NativeCandidateRefusal, NativeUnscoredCandidate

# Structural slots in MythicSim's native equipment request (items.rs).
# Test weapon choices first: a genuine Rogue melee-DPS item difference is
# more likely to be observable than a ring/armor stat with this two-call cap.
# This is proposal ordering only; Rust alone decides equip legality/effects.
NATIVE_SLOT_POSITIONS = (
    ("weapon", 14), ("offhand", 15), ("ranged", 16),
    ("head", 0), ("neck", 1), ("shoulder", 2), ("back", 3),
    ("chest", 4), ("wrist", 5), ("hands", 6), ("waist", 7),
    ("legs", 8), ("feet", 9),
    ("ring1", 10), ("ring2", 11),
    ("trinket1", 12), ("trinket2", 13),
)


def _first_player(request):
    try:
        return request["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("P3_NATIVE_EQUIPPED_REQUEST_PLAYER_MISSING") from exc


def first_equipped_proposal(reference: dict, selection: dict, *, expected_class="ClassRogue"):
    """Select one *different* native-supplied item without Python equip rules."""
    player = _first_player(reference)
    if player.get("class") != expected_class:
        raise ValueError("P3_NATIVE_EQUIPPED_CLASS_MISMATCH")
    equipment = player.get("equipment")
    entries = equipment.get("items") if isinstance(equipment, dict) else None
    if not isinstance(entries, list) or len(entries) not in (15, 16, 17):
        raise ValueError("P3_NATIVE_EQUIPPED_REQUEST_SHAPE_UNAVAILABLE")
    for slot, index in NATIVE_SLOT_POSITIONS:
        if index >= len(entries):
            continue
        source = selection.get(slot)
        if not isinstance(source, dict):
            continue
        item_ids = source.get("selected_ids")
        if not isinstance(item_ids, list):
            continue
        previous = entries[index]
        if not isinstance(previous, dict):
            raise ValueError("P3_NATIVE_EQUIPPED_BASE_ITEM_INVALID")
        before_id = previous.get("id", 0)
        for item_id in item_ids[:2]:
            if type(item_id) is not int or item_id <= 0 or item_id == before_id:
                continue
            candidate = copy.deepcopy(reference)
            _first_player(candidate)["equipment"]["items"][index] = {"id": item_id}
            return candidate, {
                "slot": slot, "slot_index": index, "from_id": before_id,
                "to_id": item_id, "source": "SELECTED_NATIVE_P3_ITEM_OPTIONS",
            }
    return None, None


def prepared_native_actor(binary, reference: dict, *, runner=subprocess.run, go_rules=False):
    """Read the *executed engine's* prepared actor, not the request's level hint.

    A source request may say level 20 while an older Rust build still creates
    its player at level 60. Never spend the two paid P3 attempts on that proxy.
    """
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "native-p3-request.json"
        path.write_text(json.dumps(reference, separators=(",", ":")), encoding="utf-8")
        command = [str(binary), "prepare", "--request", str(path)]
        if go_rules:
            command.append("--go-rules")
        try:
            completed = runner(
                command, capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "NATIVE_PREPARE_ERROR", "reason": str(exc)[-500:]}
    try:
        prepared = json.loads(completed.stdout)
    except (TypeError, ValueError):
        prepared = None
    if completed.returncode != 0:
        refusal = prepared.get("refusal") if isinstance(prepared, dict) else None
        reason = (refusal.get("reason") or refusal.get("code")
                  if isinstance(refusal, dict) else None)
        return {"status": "NATIVE_PREPARE_REFUSED",
                "reason": str(reason or completed.stderr or completed.stdout)[-500:]}
    if not isinstance(prepared, dict) or not isinstance(prepared.get("player"), dict):
        return {"status": "NATIVE_PREPARED_ACTOR_MISSING"}
    player = prepared["player"]
    reference = prepared.get("reference")
    return {"status": "PREPARED", "actor_class": player.get("class"),
            "actor_level": player.get("level"),
            "engine_revision": (reference.get("engine_revision")
                                if isinstance(reference, dict) else None),
            "prepared_request_sha256": prepared.get("request_sha256")}


def compare_equipped_native(binary, reference: dict, selection: dict, *,
                            iterations: int = 5, seed: int = 914,
                            evaluator=run, seconds: float = 90.0,
                            preparer=prepared_native_actor, max_paid_attempts: int = 2,
                            class_key: str = "rogue", level: int = 20,
                            go_rules: bool = False):
    """Pay for both original and equipped build, with identical non-gear inputs.

    Any native INVALID/UNSUPPORTED/UNSCORED/ERROR is reported verbatim and
    debited, never substituted with a Python score or awarded gate credit.
    The same selected binary's prepared actor must match the requested class
    and level before a paid comparison can become gate evidence.
    """
    if (type(iterations) is not int or iterations < 1 or seconds <= 0
            or type(max_paid_attempts) is not int or not 2 <= max_paid_attempts <= 44):
        raise ValueError("P3_NATIVE_EQUIPPED_BUDGET_INVALID")
    expected_class = {"rogue": "ClassRogue", "druid": "ClassDruid", "mage": "ClassMage"}.get(class_key)
    if expected_class is None or type(level) is not int or level < 1:
        raise ValueError("P3_NATIVE_EQUIPPED_CHECKPOINT_INVALID")
    candidate, swap = first_equipped_proposal(
        reference, selection, expected_class=expected_class)
    if candidate is None:
        return {"status": "NO_DISTINCT_NATIVE_EQUIPPED_ALTERNATIVE",
                "paid_attempts": 0, "comparison": None, "swap": None}
    # Do not spend two native executions on a level-60/missing-level donor
    # and then mislabel its DPS as Rogue L20 checkpoint evidence. The source
    # request must carry the exact L20 actor; native decides if it is runnable.
    requested_level = _first_player(reference).get("level")
    # Source L60 fixtures may omit player.level; only the selected native
    # prepare response can establish the actual actor level (never a proxy).
    if requested_level != level and not (level == 60 and requested_level is None):
        return {
            "status": "NATIVE_REQUEST_CHECKPOINT_MISMATCH",
            "paid_attempts": 0, "comparison": None, "swap": swap,
            "actor_checkpoint_verified": False,
            "actor_requested_level": requested_level,
            "promotion": "NOT_P3_PASS_WITHOUT_MATCHED_NATIVE_L20_ACTOR",
        }
    # The request's level field is only a hint: the selected Rust engine can
    # prepare an L60 actor even from a level-20 request. Read the actual
    # prepared actor from that same binary before consuming paid evaluations.
    prepared = (preparer(binary, copy.deepcopy(reference), go_rules=True)
                if go_rules else preparer(binary, copy.deepcopy(reference)))
    if not isinstance(prepared, dict) or prepared.get("status") != "PREPARED":
        return {
            "status": (prepared.get("status", "NATIVE_PREPARE_ERROR")
                       if isinstance(prepared, dict) else "NATIVE_PREPARE_ERROR"),
            "reason": prepared.get("reason") if isinstance(prepared, dict) else None,
            "paid_attempts": 0, "comparison": None, "swap": swap,
            "actor_requested_level": requested_level,
            "native_prepared_actor": prepared,
            "actor_checkpoint_verified": False,
            "promotion": "NOT_P3_PASS_WITHOUT_MATCHED_NATIVE_L20_ACTOR",
        }
    actor_matched = (prepared.get("actor_class") == expected_class
                     and type(prepared.get("actor_level")) is int
                     and prepared["actor_level"] == level)
    if not actor_matched:
        return {
            "status": "NATIVE_ACTOR_CHECKPOINT_MISMATCH",
            "paid_attempts": 0, "comparison": None, "swap": swap,
            "actor_requested_level": requested_level,
            "native_prepared_actor": prepared,
            "actor_checkpoint_verified": False,
            "promotion": "NOT_P3_PASS_WITHOUT_MATCHED_NATIVE_L20_ACTOR",
        }
    original = copy.deepcopy(reference)
    deadline = time.monotonic() + seconds
    def score_request(label, request, item_swap=None):
        row = {"kind": label, "status": "ERROR", "score": None}
        if item_swap is not None:
            row["swap"] = item_swap
        try:
            score, _output, elapsed, payload_sha = evaluator(
                binary, copy.deepcopy(request), iterations, seed,
                "balanced", deadline, objective="DPS",
                **({"go_rules": True} if go_rules else {}))
            if not math.isfinite(score):
                raise ValueError("P3_NATIVE_EQUIPPED_NONFINITE_SCORE")
            row.update(status="VALID", score=score, native_elapsed_s=elapsed,
                       request_sha256=payload_sha)
        except NativeCandidateRefusal as exc:
            row.update(status=exc.status, reason=exc.reason,
                       request_sha256=exc.request_sha256)
        except NativeUnscoredCandidate as exc:
            row.update(status="UNSCORED", reason=str(exc),
                       request_sha256=exc.request_sha256)
        except (NativeExecutionError, OSError, ValueError, TimeoutError) as exc:
            row.update(status="ERROR", reason=str(exc)[-500:],
                       request_sha256=getattr(exc, "request_sha256", None))
        return row

    # One shared native baseline. Try the second Rust-supplied item for a
    # slot only when its first native evaluation was refused or unscored.
    # Each refusal consumes the same paid budget and remains in the receipt.
    rows = [score_request("baseline", reference)]
    requested_slots = []
    for slot, _index in NATIVE_SLOT_POSITIONS:
        source = selection.get(slot)
        ids = source.get("selected_ids") if isinstance(source, dict) else None
        if not isinstance(ids, list):
            continue
        alternatives = []
        # A native option may already be equipped in the reference. Skip it
        # without consuming one of P3's two *distinct* item alternatives.
        for item_id in ids:
            alternative, item_swap = first_equipped_proposal(
                reference, {slot: {"selected_ids": [item_id]}},
                expected_class=expected_class)
            if (alternative is not None and item_swap["to_id"] not in [
                    swap_row["to_id"] for _, swap_row in alternatives]):
                alternatives.append((alternative, item_swap))
                if len(alternatives) == 2:
                    break
        if not alternatives:
            continue
        requested_slots.append(slot)
        for alternative, item_swap in alternatives:
            if len(rows) >= max_paid_attempts:
                break
            row = score_request("equipped", alternative, item_swap)
            rows.append(row)
            if row["status"] == "VALID":
                break
    if reference != original:
        raise AssertionError("Native evaluation modified source reference")
    baseline_valid = rows[0]["status"] == "VALID"
    selected = next((row for row in rows[1:] if row["status"] == "VALID"), None)
    paired = baseline_valid and selected is not None
    delta = selected["score"] - rows[0]["score"] if paired else None
    native_slot_evaluations = [
        {"swap": row["swap"], "status": row["status"], "score": row["score"],
         "delta_dps": (row["score"] - rows[0]["score"]
                       if row["status"] == "VALID" and baseline_valid else None),
         **({"reason": row["reason"]} if "reason" in row else {}),
         **({"request_sha256": row["request_sha256"]}
            if "request_sha256" in row else {})}
        for row in rows[1:]]
    verified_slots = {row["swap"]["slot"] for row in rows[1:]
                      if row["status"] == "VALID"}
    attempted_slots = {row["swap"]["slot"] for row in rows[1:]}
    # Request occupancy is structural, NOT independent Warcraft gear legality.
    # A fifteen-entry Mage fixture has neither offhand nor ranged; those
    # unrepresented positions must not be invented as P3 obligations.
    original_items = _first_player(reference)["equipment"]["items"]
    source_occupied_slots = [
        slot for slot, index in NATIVE_SLOT_POSITIONS
        if index < len(original_items)
        and isinstance(original_items[index], dict)
        and type(original_items[index].get("id")) is int
        and original_items[index]["id"] > 0
    ]
    return {
        "status": ("PAID_NATIVE_DIFFERENCE" if paired and delta != 0
                   else "PAID_NATIVE_EQUAL" if paired else "PAID_NATIVE_REFUSAL"),
        "paid_attempts": len(rows), "swap": selected["swap"] if paired else swap,
        "evaluations": rows,
        "comparison": ({"delta_dps": delta, "baseline_dps": rows[0]["score"],
                        "equipped_dps": selected["score"]} if paired else None),
        "iterations": iterations, "seed": seed,
        "native_slot_evaluations": native_slot_evaluations,
        "native_slots_paid": len(native_slot_evaluations),
        "native_slots_valid": sum(row["status"] == "VALID" for row in rows[1:]),
        "native_slots_requested": len(requested_slots),
        "native_slots_verified": len(verified_slots),
        "native_slots_unscored": [slot for slot in requested_slots
                                  if slot not in verified_slots],
        "native_slots_unattempted": [slot for slot in requested_slots
                                     if slot not in attempted_slots],
        "native_slot_attempt_cap": max_paid_attempts,
        "source_occupied_slots": source_occupied_slots,
        "actor_requested_level": requested_level,
        "actor_checkpoint_verified": bool(actor_matched and paired),
        "native_prepared_actor": prepared,
        "promotion": (
            f"MATCHED_{class_key.upper()}_L{level}_NATIVE_SCORED_DIFFERENCE"
            if paired and delta != 0
            else f"MATCHED_{class_key.upper()}_L{level}_NATIVE_EQUAL" if paired
            else f"NOT_P3_PASS_WITHOUT_MATCHED_NATIVE_{class_key.upper()}_L{level}_ACTOR"),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--max-paid-attempts", type=int, default=2)
    parser.add_argument("--class-key", choices=("rogue", "druid", "mage"), default="rogue")
    parser.add_argument("--level", type=int, default=20)
    parser.add_argument("--go-rules", action="store_true")
    parser.add_argument("--current-client-profile", choices=("mage/arcane", "mage/fire"))
    args = parser.parse_args()
    selection = json.load(sys.stdin)
    reference = json.loads(args.request.read_text(encoding="utf-8"))
    if args.current_client_profile:
        # Reuse the selected, source-pinned client preset already used by
        # native_l60_matrix; never decode or validate talent rules in Python.
        from native_l60_matrix import (apply_current_client_talent_override,
                                       verify_current_client_engine_pin)
        verify_current_client_engine_pin(Path(__file__).resolve().parent / "engine")
        reference, _source_preset = apply_current_client_talent_override(
            args.current_client_profile, reference)
    result = compare_equipped_native(
        args.binary, reference, selection, max_paid_attempts=args.max_paid_attempts,
        class_key=args.class_key, level=args.level, go_rules=args.go_rules)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
