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


def first_equipped_proposal(reference: dict, selection: dict):
    """Select one *different* native-supplied item without Python equip rules."""
    player = _first_player(reference)
    if player.get("class") != "ClassRogue":
        raise ValueError("P3_NATIVE_EQUIPPED_CLASS_MISMATCH")
    equipment = player.get("equipment")
    entries = equipment.get("items") if isinstance(equipment, dict) else None
    if not isinstance(entries, list) or len(entries) not in (16, 17):
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


def compare_equipped_native(binary, reference: dict, selection: dict, *,
                            iterations: int = 5, seed: int = 914,
                            evaluator=run, seconds: float = 90.0):
    """Pay for both original and equipped build, with identical non-gear inputs.

    Any native INVALID/UNSUPPORTED/UNSCORED/ERROR is reported verbatim and
    debited, never substituted with a Python score or awarded gate credit.
    The selected request's checkpoint/actor identity must be established by
    the gate caller before any P3 promotion; this helper does not infer it.
    """
    if type(iterations) is not int or iterations < 1 or seconds <= 0:
        raise ValueError("P3_NATIVE_EQUIPPED_BUDGET_INVALID")
    candidate, swap = first_equipped_proposal(reference, selection)
    if candidate is None:
        return {"status": "NO_DISTINCT_NATIVE_EQUIPPED_ALTERNATIVE",
                "paid_attempts": 0, "comparison": None, "swap": None}
    original = copy.deepcopy(reference)
    deadline = time.monotonic() + seconds
    rows = []
    for label, request in (("baseline", reference), ("equipped", candidate)):
        row = {"kind": label, "status": "ERROR", "score": None}
        try:
            score, _output, elapsed, payload_sha = evaluator(
                binary, copy.deepcopy(request), iterations, seed,
                "balanced", deadline, objective="DPS")
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
        rows.append(row)
    if reference != original:
        raise AssertionError("Native evaluation modified source reference")
    paired = all(row["status"] == "VALID" for row in rows)
    delta = rows[1]["score"] - rows[0]["score"] if paired else None
    return {
        "status": ("PAID_NATIVE_DIFFERENCE" if paired and delta != 0
                   else "PAID_NATIVE_EQUAL" if paired else "PAID_NATIVE_REFUSAL"),
        "paid_attempts": len(rows), "swap": swap, "evaluations": rows,
        "comparison": ({"delta_dps": delta, "baseline_dps": rows[0]["score"],
                        "equipped_dps": rows[1]["score"]} if paired else None),
        "iterations": iterations, "seed": seed,
        "actor_checkpoint_verified": False,
        "promotion": "NOT_P3_PASS_WITHOUT_MATCHED_NATIVE_L20_ACTOR",
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    selection = json.load(sys.stdin)
    reference = json.loads(args.request.read_text(encoding="utf-8"))
    result = compare_equipped_native(args.binary, reference, selection)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
