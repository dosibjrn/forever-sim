#!/usr/bin/env python3
"""Propose one adjacent-level Warlock source actor using pinned native options.

This is Forever candidate generation, not a Warcraft legality implementation.
The selected MythicSim binary supplies talent choices and authoritatively
prepares/refuses the resulting explicit actor. No Python combat model, spell
acquisition rules, or inferred route costs are used.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_paid_predecessor(*, route: Path, source: Path, from_level: int) -> dict:
    """Require a real paid prior-level receipt for automatic route extension.

    This matches only executed-world identity and the exact persisted request.
    Rust remains authoritative for the next actor and Warcraft legality.
    """
    previous = json.loads(route.read_text())
    if previous.get("class") != "warlock" or not isinstance(previous.get("observations"), list):
        raise ValueError("predecessor must be a Warlock native route report")
    levels = previous.get("measured_levels")
    if (not isinstance(levels, list) or not levels
            or any(type(l) is not int for l in levels) or max(levels) != from_level):
        raise ValueError("predecessor must end at the last paid measured level")
    fingerprint = sha256(source)
    matches = [
        row for row in previous["observations"]
        if isinstance(row, dict)
        and row.get("level") == from_level
        and row.get("status") == "measured_native_chain"
        and row.get("source_request_sha256") == fingerprint
        and row.get("native_world_ack") is True
        and row.get("paid_native_recovery") is True
        and row.get("targets_requested") == 100
        and row.get("targets_killed") == 100
        and isinstance(row.get("native_actor"), dict)
        and row["native_actor"].get("level") == from_level
        and row["native_actor"].get("class") == "ClassWarlock"
    ]
    if not matches:
        raise ValueError("source request has no matching completed paid native predecessor")
    return {"level": from_level, "observation_id": matches[0]["id"],
            "source_request_sha256": fingerprint}


def propose(*, binary: Path, source: Path, out: Path, from_level: int = 20,
            to_level: int = 21, max_proposals: int = 30,
            predecessor_route: Path | None = None) -> dict:
    if to_level != from_level + 1 or not 10 <= from_level < 60:
        raise ValueError("source proposals require exactly one adjacent level in 10..60")
    if max_proposals < 1:
        raise ValueError("max_proposals must be positive")
    if not binary.is_file() or not source.is_file():
        raise ValueError("native binary and original source request are required")
    predecessor = (verified_paid_predecessor(
        route=predecessor_route, source=source, from_level=from_level)
        if predecessor_route is not None else None)
    original = json.loads(source.read_text())
    actor = original["raid"]["parties"][0]["players"][0]
    if actor.get("class") != "ClassWarlock":
        raise ValueError("expected original Warlock actor")
    encounter_level = original["encounter"]["targets"][0].get("level")
    if encounter_level != from_level:
        raise ValueError("original source target level differs from from_level")
    allocations = actor["talentsString"].split("-")
    if len(allocations) != 3 or any(
            not token or not token.isascii() or not token.isdigit()
            for token in allocations):
        raise ValueError("source actor has unsupported talent allocation serialization")

    # The level point budget and each possible rank come from the selected
    # Rust binary. Forever only proposes a one-rank mutation; Rust decides
    # whether the proposed actor can be prepared and executed.
    options_call = subprocess.run(
        [str(binary.resolve()), "options", "--class", "warlock",
         "--level", str(to_level)],
        capture_output=True, text=True, timeout=60, check=False)
    if options_call.returncode:
        raise RuntimeError("NATIVE_OPTIONS_REFUSAL: " +
                           (options_call.stderr or options_call.stdout)[-2000:])
    options = json.loads(options_call.stdout)
    talents = options.get("talents", {})
    trees = talents.get("trees")
    source_points = sum(int(ch) for token in allocations for ch in token)
    native_budget = talents.get("points_available")
    # A Rust-prepared prior level may deliberately bank a point when no new
    # talent candidate was legal with its source gear. Requiring exactly one
    # unspent point would strand all later levels after that real L21 outcome.
    # Query native options and submit a one-rank proposal; ONLY Rust prepare
    # decides whether the resulting allocation and actor are executable.
    if (options.get("level") != to_level or
            talents.get("status") != "ok" or
            type(native_budget) is not int or native_budget <= source_points or
            not isinstance(trees, list) or len(trees) != 3):
        raise ValueError("native options cannot advance this exact source allocation one point")

    out.mkdir(parents=True, exist_ok=True)
    attempts_dir = out / "candidate_attempts"
    attempts_dir.mkdir(exist_ok=True)
    rejected = []
    # Try existing invested ranks first, then native-listed new ranks. This is
    # deterministic proposal order, not a simulated strength/legality ranking.
    alternatives = []
    for ti, tree in enumerate(trees):
        for entry in tree["talents"]:
            index, cap = entry["index"], entry["max_rank"]
            if type(index) is not int or type(cap) is not int or cap < 1:
                raise ValueError("malformed native talent option")
            current = int(allocations[ti][index]) if index < len(allocations[ti]) else 0
            if current < cap:
                alternatives.append((current == 0, -sum(map(int, allocations[ti])),
                                     ti, index, entry["field_name"]))
    alternatives.sort()
    for number, (_new_rank, _investment, ti, index, field) in enumerate(
            alternatives[:max_proposals], start=1):
        mutated = copy.deepcopy(original)
        slots = list(allocations[ti])
        if len(slots) <= index:
            slots.extend(["0"] * (index + 1 - len(slots)))
        slots[index] = str(int(slots[index]) + 1)
        pieces = list(allocations)
        pieces[ti] = "".join(slots)
        mutated["raid"]["parties"][0]["players"][0]["talentsString"] = "-".join(pieces)
        # The submitted actor and target must refer to the same next-level encounter.
        mutated["raid"]["parties"][0]["players"][0]["level"] = to_level
        mutated["encounter"]["targets"][0]["level"] = to_level
        request_file = attempts_dir / f"candidate_{number:02d}.json"
        prepared_file = attempts_dir / f"candidate_{number:02d}.prepared.json"
        request_file.write_text(json.dumps(mutated, indent=2) + "\n")
        result = subprocess.run(
            [str(binary.resolve()), "prepare", "--request",
             str(request_file.resolve()), "--actor-level", str(to_level),
             "--outfile", str(prepared_file.resolve())],
            capture_output=True, text=True, timeout=60, check=False)
        if result.returncode:
            raw = (result.stderr or result.stdout)[-1200:]
            try:
                native_refusal = json.loads(raw).get("refusal")
            except (ValueError, AttributeError):
                native_refusal = None
            code = (native_refusal.get("code") if isinstance(native_refusal, dict)
                    else None)
            rejected.append({"field_name": field, "tree_index": ti,
                             "reason": raw, "native_refusal_code": code})
            if code == "actor_level_source":
                # This exact native source refusal is about missing level/race
                # base stats, not the candidate's talent choice. Do not pay
                # for another 29 identical native preparations or fake L21.
                receipt = {
                    "kind": "adjacent_native_warlock_candidate",
                    "status": "NATIVE_ACTOR_LEVEL_UNSUPPORTED",
                    "from_level": from_level, "to_level": to_level,
                    "original_source_sha256": sha256(source),
                    "native_binary_sha256": sha256(binary),
                    "native_options_source_revision": options.get("source_revision"),
                    "attempted": number, "native_refusals": rejected,
                }
                (out / "proposal.json").write_text(json.dumps(receipt, indent=2) + "\n")
                return receipt
            continue
        try:
            prepared_actor = json.loads(prepared_file.read_text())["player"]
        except (ValueError, KeyError, OSError):
            rejected.append({"field_name": field, "tree_index": ti,
                             "reason": "NATIVE_PREPARED_ACTOR_MISSING"})
            continue
        if (prepared_actor.get("level") != to_level
                or prepared_actor.get("class") != "ClassWarlock"):
            rejected.append({"field_name": field, "tree_index": ti,
                             "reason": "NATIVE_PREPARED_ACTOR_LEVEL_OR_CLASS_MISMATCH"})
            continue
        selected = out / "source_request.json"
        selected.write_bytes(request_file.read_bytes())
        receipt = {
            "kind": "adjacent_native_warlock_candidate",
            "status": "NATIVE_PREPARED_NOT_YET_PAID",
            "from_level": from_level, "to_level": to_level,
            "original_source_sha256": sha256(source),
            "native_binary_sha256": sha256(binary),
            "selected_source_sha256": sha256(selected),
            "native_prepared_sha256": sha256(prepared_file),
            "native_options_source_revision": options.get("source_revision"),
            "source_talents": actor["talentsString"],
            "candidate_talents": mutated["raid"]["parties"][0]["players"][0]["talentsString"],
            "field_name": field, "tree_index": ti,
            "attempted": number, "native_refusals_before_selection": rejected,
            "next_step": "execute actual retained-actor hostile 100-kill native/gsim chain",
        }
        (out / "proposal.json").write_text(json.dumps(receipt, indent=2) + "\n")
        return receipt
    # A full source loadout can become unpreparable on the next level even
    # when its prior actor was native-accepted (e.g. missing rating conversions).
    # After trying native-supplied talent alternatives, test carrying forward
    # the *unchanged* talents with native-prepared equipment subsets. This is
    # candidate search, not a Python decision about item or talent legality.
    source_items = actor.get("equipment", {}).get("items")
    native_gear_refusals = []
    if isinstance(source_items, list) and source_items:
        frozen = copy.deepcopy(original)
        frozen_actor = frozen["raid"]["parties"][0]["players"][0]
        frozen_actor["level"] = to_level
        frozen["encounter"]["targets"][0]["level"] = to_level
        original_items = copy.deepcopy(source_items)
        frozen_actor["equipment"]["items"] = [{"id": 0} for _ in original_items]

        def try_native_gear(tag: str) -> tuple[bool, str, Path, Path]:
            request = attempts_dir / f"fallback_{tag}.json"
            prepared = attempts_dir / f"fallback_{tag}.prepared.json"
            request.write_text(json.dumps(frozen, indent=2) + "\n")
            response = subprocess.run(
                [str(binary.resolve()), "prepare", "--request",
                 str(request.resolve()), "--actor-level", str(to_level),
                 "--outfile", str(prepared.resolve())],
                capture_output=True, text=True, timeout=60, check=False)
            if response.returncode:
                return False, (response.stderr or response.stdout)[-1200:], request, prepared
            try:
                native_actor = json.loads(prepared.read_text())["player"]
            except (ValueError, KeyError, OSError):
                return False, "NATIVE_PREPARED_ACTOR_MISSING", request, prepared
            if (native_actor.get("level") != to_level or
                    native_actor.get("class") != "ClassWarlock"):
                return False, "NATIVE_PREPARED_ACTOR_LEVEL_OR_CLASS_MISMATCH", request, prepared
            return True, "", request, prepared

        empty_ok, empty_reason, _, _ = try_native_gear("empty")
        if empty_ok:
            kept = []
            for index, item in enumerate(original_items):
                if isinstance(item, dict) and item.get("id") in (None, 0):
                    continue
                frozen_actor["equipment"]["items"][index] = copy.deepcopy(item)
                item_ok, item_reason, _, _ = try_native_gear(f"slot_{index:02d}")
                if item_ok:
                    kept.append({"slot": index, "id": item.get("id") if isinstance(item, dict) else None})
                else:
                    frozen_actor["equipment"]["items"][index] = {"id": 0}
                    native_gear_refusals.append({
                        "slot": index, "id": item.get("id") if isinstance(item, dict) else None,
                        "reason": item_reason,
                    })
            final_ok, final_reason, final_request, final_prepared = try_native_gear("final")
            if final_ok:
                selected = out / "source_request.json"
                selected.write_bytes(final_request.read_bytes())
                receipt = {
                    "kind": "adjacent_native_warlock_candidate",
                    "status": "NATIVE_PREPARED_NOT_YET_PAID",
                    "from_level": from_level, "to_level": to_level,
                    "original_source_sha256": sha256(source),
                    "native_binary_sha256": sha256(binary),
                    "selected_source_sha256": sha256(selected),
                    "native_prepared_sha256": sha256(final_prepared),
                    "native_options_source_revision": options.get("source_revision"),
                    "source_talents": actor["talentsString"],
                    "candidate_talents": frozen_actor["talentsString"],
                    "selection": "native_prepared_carry_forward_with_item_probes",
                    "talent_points_newly_spent": 0,
                    "native_gear_kept": kept,
                    "native_gear_refusals": native_gear_refusals,
                    "attempted": len(rejected),
                    "native_refusals_before_selection": rejected,
                    "next_step": "execute actual retained-actor hostile 100-kill native/gsim chain",
                }
                (out / "proposal.json").write_text(json.dumps(receipt, indent=2) + "\n")
                return receipt
            native_gear_refusals.append({"phase": "final", "reason": final_reason})
        else:
            native_gear_refusals.append({"phase": "empty", "reason": empty_reason})

    receipt = {"kind": "adjacent_native_warlock_candidate",
               "status": "NATIVE_PREPARE_REFUSED_ALL_PROPOSALS",
               "from_level": from_level, "to_level": to_level,
               "original_source_sha256": sha256(source),
               "native_binary_sha256": sha256(binary),
               "native_refusals": rejected,
               "native_gear_refusals": native_gear_refusals}
    (out / "proposal.json").write_text(json.dumps(receipt, indent=2) + "\n")
    raise RuntimeError("native refused all proposed adjacent-level Warlock actors")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--from-level", type=int, default=20)
    parser.add_argument("--to-level", type=int, default=21)
    parser.add_argument("--max-proposals", type=int, default=30)
    parser.add_argument("--predecessor-route", type=Path,
                        help="Require exact executed paid previous-level source receipt")
    args = parser.parse_args()
    result = propose(**vars(args))
    print(json.dumps(result, indent=2))
    if result["status"] != "NATIVE_PREPARED_NOT_YET_PAID":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
