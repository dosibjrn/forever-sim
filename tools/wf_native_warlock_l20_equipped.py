#!/usr/bin/env python3
"""Build an actually native-prepared Troll Warlock L20 equipped P3 source request.

The selected Rust item-options response supplies all proposed item IDs/slots.
Rust prepare alone accepts/refuses each attempted candidate. This is only a
request producer: the P3 native paid baseline/alternatives still decide VALID,
INVALID, UNSUPPORTED and measured DPS, within their existing 44-payment cap.
No Forever gameplay eligibility or stat heuristics are used.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations/mythicsim-rust"))

from native_p3_equipped import NATIVE_SLOT_POSITIONS, prepared_native_actor
from src.game.native_p3_item_options import query_native_p3_item_options
from tools.wf_gate_p3_live import _native_p3_equipped_slot_proposals


class NativeWarlockEquippedError(ValueError):
    """Cannot construct a verified native L20 actor with occupied source gear."""


def build_warlock_equipped_request(binary: str, template: dict,
                                  source_items: dict, *,
                                  preparer=prepared_native_actor) -> tuple[dict, dict]:
    """Probe up to three Rust-supplied IDs per structural slot via Rust prepare.

    PREPARED here is not a P3 paid score or a blanket legality certificate.
    The follow-up balanced native sim validates and scores each full build.
    """
    original = copy.deepcopy(template)
    try:
        player = original["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise NativeWarlockEquippedError("WARLOCK_L20_SOURCE_PLAYER_MISSING") from exc
    if (player.get("class") != "ClassWarlock" or player.get("race") != "RaceTroll"
            or player.get("level") not in (None, 20)):
        raise NativeWarlockEquippedError("WARLOCK_L20_SOURCE_ACTOR_MISMATCH")
    equipment = player.get("equipment")
    entries = equipment.get("items") if isinstance(equipment, dict) else None
    if not isinstance(entries, list) or len(entries) not in (0, 14, 15, 16, 17):
        raise NativeWarlockEquippedError("WARLOCK_L20_SOURCE_EQUIPMENT_INVALID")
    if any(not isinstance(row, dict) or type(row.get("id")) is not int
           or row["id"] < 0 for row in entries):
        raise NativeWarlockEquippedError("WARLOCK_L20_SOURCE_EQUIPMENT_INVALID")
    if not isinstance(source_items, dict) or not source_items.get("items"):
        raise NativeWarlockEquippedError("WARLOCK_L20_SOURCE_ITEM_OPTIONS_EMPTY")

    request = copy.deepcopy(original)
    gear = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    gear.extend({"id": 0} for _ in range(17 - len(gear)))
    selection = _native_p3_equipped_slot_proposals(source_items)["slots"]
    accepted = []
    refusals = []
    attempts = 0

    for slot, index in NATIVE_SLOT_POSITIONS:
        # Preserve any occupied slot supplied by the selected native source
        # fixture; never overwrite its equipment with a synthetic preference.
        if gear[index]["id"] > 0:
            accepted.append({"slot": slot, "item_id": gear[index]["id"],
                             "from_source_fixture": True})
            continue
        ids = (selection.get(slot) or {}).get("selected_ids") or []
        for item_id in ids[:3]:
            if type(item_id) is not int or item_id <= 0:
                continue
            candidate = copy.deepcopy(request)
            candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][index] = {
                "id": item_id}
            # Only the selected Rust actor can accept or refuse the candidate.
            prepared = preparer(binary, candidate, actor_level=20)
            attempts += 1
            if (isinstance(prepared, dict)
                    and prepared.get("status") == "PREPARED"
                    and prepared.get("actor_class") == "ClassWarlock"
                    and type(prepared.get("actor_level")) is int
                    and prepared["actor_level"] == 20):
                request = candidate
                gear = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
                accepted.append({"slot": slot, "item_id": item_id,
                                 "from_source_fixture": False})
                break
            refusals.append({"slot": slot, "item_id": item_id,
                             "status": prepared.get("status") if isinstance(prepared, dict)
                             else "NATIVE_PREPARE_ERROR",
                             "reason": (prepared.get("reason") if isinstance(prepared, dict)
                                        else "invalid native prepare response")})
    if not accepted:
        raise NativeWarlockEquippedError("WARLOCK_L20_NO_NATIVE_PREPARED_EQUIPMENT")

    # A previous PREPARED response only covers the preceding candidate. The
    # producer may also preserve every pre-equipped slot without invoking
    # prepare once. Require native confirmation of the *complete output request*
    # before handing it to the paid P3 evaluator; never infer compatibility
    # from individual item probes or a source fixture.
    final_prepared = preparer(binary, copy.deepcopy(request), actor_level=20)
    attempts += 1
    if (not isinstance(final_prepared, dict)
            or final_prepared.get("status") != "PREPARED"
            or final_prepared.get("actor_class") != "ClassWarlock"
            or type(final_prepared.get("actor_level")) is not int
            or final_prepared["actor_level"] != 20):
        outcome = (final_prepared if isinstance(final_prepared, dict)
                   else {"status": "NATIVE_PREPARE_ERROR"})
        raise NativeWarlockEquippedError(
            "WARLOCK_L20_FINAL_NATIVE_PREPARE_REFUSED:"
            + str(outcome.get("status"))
            + ":" + str(outcome.get("reason") or outcome.get("actor_class") or ""))

    # The source fixture (incl. its native APL, encounter, talents and race)
    # remains unchanged. P3 pays for one full baseline and separate gear swaps.
    return request, {
        "status": "NATIVE_WARLOCK_L20_EQUIPPED_REQUEST_PREPARED_NOT_PAID",
        "actor": "ClassWarlock", "race": "RaceTroll", "level": 20,
        "native_prepare_attempts": attempts, "occupied_slots": accepted,
        "final_native_prepared_actor": final_prepared,
        "native_prepare_refusals": refusals,
        "paid_p3_attempts": 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    source = json.loads(args.template.read_text(encoding="utf-8"))
    options = query_native_p3_item_options(
        args.binary, "warlock", 20, spec="unrestricted", slot="all")
    request, receipt = build_warlock_equipped_request(
        args.binary, source, options)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
