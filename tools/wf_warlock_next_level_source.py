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
import math
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_paid_predecessor(*, route: Path, source: Path, binary: Path,
                              from_level: int,
                              predecessor_binary_sha256: str | None = None) -> dict:
    """Require a real paid prior-level receipt for automatic route extension.

    This matches an executed native actor to the exact persisted request
    and selected executable. A route may also contain later, incompatible
    historical levels; they must not veto a real paid predecessor or confer
    a fabricated transition. Rust still owns Warcraft legality.
    """
    previous = json.loads(route.read_text())
    if previous.get("class") != "warlock" or not isinstance(previous.get("observations"), list):
        raise ValueError("predecessor must be a Warlock native route report")
    levels = previous.get("measured_levels")
    if (not isinstance(levels, list) or not levels
            or any(type(l) is not int for l in levels) or from_level not in levels):
        raise ValueError("predecessor does not include the paid source level")
    fingerprint = sha256(source)
    # An adjacent native source upgrade can retain a genuinely paid prior
    # request while executing the successor on a different pinned binary.
    # Require an explicit original binary digest, never silently equate them.
    if predecessor_binary_sha256 is not None and (
            len(predecessor_binary_sha256) != 64 or any(
                char not in "0123456789abcdef" for char in predecessor_binary_sha256)):
        raise ValueError("predecessor binary digest must be 64 lowercase hex characters")
    engine_fingerprint = predecessor_binary_sha256 or sha256(binary)
    matches = [
        row for row in previous["observations"]
        if isinstance(row, dict)
        and row.get("level") == from_level
        and row.get("status") == "measured_native_chain"
        and row.get("source_request_sha256") == fingerprint
        and row.get("engine_binary_sha256") == engine_fingerprint
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
            "source_request_sha256": fingerprint,
            "engine_binary_sha256": engine_fingerprint,
            "successor_engine_binary_sha256": sha256(binary),
            "cross_engine_source_transition": engine_fingerprint != sha256(binary)}


def propose(*, binary: Path, source: Path, out: Path, from_level: int = 20,
            to_level: int = 21, max_proposals: int = 30,
            predecessor_route: Path | None = None,
            predecessor_binary_sha256: str | None = None,
            native_paid_shortlist: bool = False) -> dict:
    if to_level != from_level + 1 or not 10 <= from_level < 60:
        raise ValueError("source proposals require exactly one adjacent level in 10..60")
    if max_proposals < 1:
        raise ValueError("max_proposals must be positive")
    if not binary.is_file() or not source.is_file():
        raise ValueError("native binary and original source request are required")
    if predecessor_binary_sha256 is not None and predecessor_route is None:
        raise ValueError("cross-engine predecessor requires an exact paid route receipt")
    predecessor = (verified_paid_predecessor(
        route=predecessor_route, source=source, binary=binary,
        from_level=from_level,
        predecessor_binary_sha256=predecessor_binary_sha256)
        if predecessor_route is not None else None)
    original = json.loads(source.read_text())
    actor = original["raid"]["parties"][0]["players"][0]
    if actor.get("class") != "ClassWarlock":
        raise ValueError("expected original Warlock actor")
    # An adjacent-level transition must start from the actual predecessor actor,
    # not merely a target fixture labeled as that level. This is request
    # provenance/forwarding integrity; native prepare still owns game legality.
    if type(actor.get("level")) is not int or actor["level"] != from_level:
        raise ValueError("source actor level differs from from_level")
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
    # A reused output directory must never present a previous run\'s selected
    # actor or receipt as belonging to this native invocation.
    out.mkdir(parents=True, exist_ok=True)
    (out / "source_request.json").unlink(missing_ok=True)
    (out / "proposal.json").unlink(missing_ok=True)
    (out / "native_paid_shortlist.json").unlink(missing_ok=True)
    options_call = subprocess.run(
        [str(binary.resolve()), "options", "--class", "warlock",
         "--level", str(to_level)],
        capture_output=True, text=True, timeout=60, check=False)
    if options_call.returncode:
        # Preserve the real native error as an unmeasured route result. The
        # caller's refusal-publication step needs this file even when no actor
        # proposal could be prepared.
        reason = (options_call.stderr or options_call.stdout or
                  "native options returned no diagnostics")[-2000:]
        try:
            native_refusal = json.loads(reason).get("refusal")
        except (ValueError, AttributeError):
            native_refusal = None
        receipt = {
            "kind": "adjacent_native_warlock_candidate",
            "status": "NATIVE_OPTIONS_REFUSED",
            "from_level": from_level, "to_level": to_level,
            "original_source_sha256": sha256(source),
            "native_binary_sha256": sha256(binary),
            "paid_predecessor": predecessor,
            "attempted": 0,
            "native_refusals": [{
                "stage": "options", "reason": reason,
                "native_refusal_code": (
                    native_refusal.get("code") if isinstance(native_refusal, dict)
                    else None),
            }],
        }
        out.mkdir(parents=True, exist_ok=True)
        (out / "proposal.json").write_text(json.dumps(receipt, indent=2) + "\n")
        raise RuntimeError("NATIVE_OPTIONS_REFUSAL: " + reason)
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
    if native_paid_shortlist:
        # Do not let first-invested ordering monopolize a paid comparison.
        # Trees and per-rank proposals still come exclusively from Rust options.
        by_tree = [[entry for entry in alternatives if entry[2] == tree_index]
                   for tree_index in range(len(trees))]
        ordered = []
        for depth in range(max(map(len, by_tree), default=0)):
            for bucket in by_tree:
                if depth < len(bucket):
                    ordered.append(bucket[depth])
        attempts = ordered[:max_proposals]
    else:
        attempts = alternatives[:max_proposals]
    shortlist = []
    for number, (_new_rank, _investment, ti, index, field) in enumerate(
            attempts, start=1):
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
        paid_file = attempts_dir / f"candidate_{number:02d}.paid.json"
        request_file.write_text(json.dumps(mutated, indent=2) + "\n")
        if native_paid_shortlist:
            # A refused prepare must not leave an older paid screen on disk.
            paid_file.unlink(missing_ok=True)
        # A short native DPS screen is only a routing heuristic. Preserve the
        # untouched full-world candidate request for later real 100-target runs.
        screen_request = request_file
        if native_paid_shortlist:
            screen = copy.deepcopy(mutated)
            screen.setdefault("simOptions", {}).update({
                "iterations": 8, "randomSeed": "4242",
                "debugFirstIteration": False,
            })
            screen["encounter"]["duration"] = 30
            screen_request = attempts_dir / f"candidate_{number:02d}.screen.json"
            screen_request.write_text(json.dumps(screen, indent=2) + "\n")
        # A successful exit without a newly written prepared actor is not proof
        # of preparation; remove any artifact from an earlier run first.
        prepared_file.unlink(missing_ok=True)
        result = subprocess.run(
            [str(binary.resolve()), "prepare", "--request",
             str(screen_request.resolve()), "--actor-level", str(to_level),
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
            source_level_reason = (
                native_refusal.get("reason") if isinstance(native_refusal, dict)
                else None
            )
            source_level_unavailable = (
                code == "level"
                and isinstance(source_level_reason, str)
                and source_level_reason.startswith(
                    f"player level {to_level} is unsupported: "
                    "no source-backed native preparation"
                )
            )
            if code == "actor_level_source" or source_level_unavailable:
                # The native engine explicitly refuses this actor level/source,
                # independent of talents or gear. Preserve its original code
                # and stop rather than paying for repeated equivalent prepares.
                receipt = {
                    "kind": "adjacent_native_warlock_candidate",
                    "status": "NATIVE_ACTOR_LEVEL_UNSUPPORTED",
                    "from_level": from_level, "to_level": to_level,
                    "original_source_sha256": sha256(source),
                    "native_binary_sha256": sha256(binary),
            "paid_predecessor": predecessor,
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
        if native_paid_shortlist:
            screen_result = {
                "tree_index": ti, "field_name": field,
                "candidate_talents": mutated["raid"]["parties"][0]["players"][0]["talentsString"],
                "source_request": str(request_file.relative_to(out)),
                "source_request_sha256": sha256(request_file),
                "native_prepared_sha256": sha256(prepared_file),
                "native_screen_request_sha256": sha256(screen_request),
                "screen_status": "NATIVE_SCREEN_REFUSED",
                "screen_dps_30s": None,
            }
            try:
                paid = subprocess.run(
                    [str(binary.resolve()), "sim", "--infile",
                     str(prepared_file.resolve()), "--rng-mode", "balanced",
                     "--outfile", str(paid_file.resolve())],
                    capture_output=True, text=True, timeout=120, check=False)
                if paid.returncode:
                    raise RuntimeError((paid.stderr or paid.stdout or
                                        "native screen refused")[-1200:])
                actual = json.loads(paid_file.read_text())["result"]
                dps = actual["raidMetrics"]["parties"][0]["players"][0]["dps"]["avg"]
                if type(dps) not in (int, float) or not math.isfinite(dps):
                    raise ValueError("native screen returned nonfinite DPS")
                screen_result.update(screen_status="NATIVE_SCREEN_PAID",
                                     screen_dps_30s=float(dps),
                                     native_paid_receipt_sha256=sha256(paid_file))
            except (OSError, ValueError, KeyError, RuntimeError,
                    subprocess.TimeoutExpired) as exc:
                screen_result["screen_refusal"] = str(exc)[-1200:]
            shortlist.append(screen_result)
            continue
        selected = out / "source_request.json"
        selected.write_bytes(request_file.read_bytes())
        receipt = {
            "kind": "adjacent_native_warlock_candidate",
            "status": "NATIVE_PREPARED_NOT_YET_PAID",
            "from_level": from_level, "to_level": to_level,
            "original_source_sha256": sha256(source),
            "native_binary_sha256": sha256(binary),
            "paid_predecessor": predecessor,
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
    if native_paid_shortlist:
        # Never fall through into the legacy first-preparable gear/banked-point
        # selection. Even when every ranked talent proposal is refused by
        # Rust, opt-in comparison mode cannot silently choose an unmeasured
        # successor. The continuity fallback remains available in default mode.
        status = ("NATIVE_SCREENED_NOT_WORLD_PAID" if shortlist else
                  "NATIVE_SHORTLIST_NO_PREPARABLE_CANDIDATES")
        receipt = {
            "kind": "adjacent_native_warlock_candidate",
            "status": status,
            "from_level": from_level, "to_level": to_level,
            "original_source_sha256": sha256(source),
            "native_binary_sha256": sha256(binary),
            "paid_predecessor": predecessor,
            "native_options_source_revision": options.get("source_revision"),
            "source_talents": actor["talentsString"],
            "attempted": len(attempts),
            "candidates": shortlist,
            "native_refusals": rejected,
            "world_winner": None,
            "next_step": (
                "pay authentic retained-actor hostile 100-target worlds for competing source-native builds"
                if shortlist else
                "no ranked actor prepared; inspect native refusals or run the separate continuity policy"
            ),
        }
        serialized = json.dumps(receipt, indent=2) + "\n"
        (out / "native_paid_shortlist.json").write_text(serialized)
        (out / "proposal.json").write_text(serialized)
        return receipt
    # A full source loadout can become unpreparable on the next level even
    # when its prior actor was native-accepted (e.g. missing rating conversions).
    # After trying native-supplied talent alternatives, test carrying forward
    # the *unchanged* talents with native-prepared equipment subsets. This is
    # candidate search, not a Python decision about item or talent legality.
    source_items = actor.get("equipment", {}).get("items")
    native_gear_refusals = []
    # An explicitly empty native equipment list is still a valid candidate:
    # when every new rank is refused, ask Rust whether the same banked talents
    # prepare at the next level. Do not require an inherited item to try this.
    if isinstance(source_items, list):
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
            prepared.unlink(missing_ok=True)
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
                # A bad inherited item must not force us to bank an otherwise
                # native-preparable talent point. Retry the same Rust-supplied
                # mutations on the equipment subset Rust just accepted.
                # Neither candidate order nor item probing decides legality.
                recovered_refusals = []
                for retry, (_new_rank, _investment, ti, index, field) in enumerate(
                        alternatives[:max_proposals], start=1):
                    candidate = copy.deepcopy(frozen)
                    candidate_actor = candidate["raid"]["parties"][0]["players"][0]
                    slots = list(allocations[ti])
                    if len(slots) <= index:
                        slots.extend(["0"] * (index + 1 - len(slots)))
                    slots[index] = str(int(slots[index]) + 1)
                    pieces = list(allocations)
                    pieces[ti] = "".join(slots)
                    candidate_actor["talentsString"] = "-".join(pieces)
                    request = attempts_dir / f"recovered_talent_{retry:02d}.json"
                    prepared = attempts_dir / f"recovered_talent_{retry:02d}.prepared.json"
                    request.write_text(json.dumps(candidate, indent=2) + "\n")
                    prepared.unlink(missing_ok=True)
                    response = subprocess.run(
                        [str(binary.resolve()), "prepare", "--request",
                         str(request.resolve()), "--actor-level", str(to_level),
                         "--outfile", str(prepared.resolve())],
                        capture_output=True, text=True, timeout=60, check=False)
                    if response.returncode:
                        recovered_refusals.append({
                            "field_name": field, "tree_index": ti,
                            "reason": (response.stderr or response.stdout)[-1200:]})
                        continue
                    try:
                        prepared_actor = json.loads(prepared.read_text())["player"]
                    except (ValueError, KeyError, OSError):
                        recovered_refusals.append({
                            "field_name": field, "tree_index": ti,
                            "reason": "NATIVE_PREPARED_ACTOR_MISSING"})
                        continue
                    if (prepared_actor.get("level") != to_level
                            or prepared_actor.get("class") != "ClassWarlock"):
                        recovered_refusals.append({
                            "field_name": field, "tree_index": ti,
                            "reason": "NATIVE_PREPARED_ACTOR_LEVEL_OR_CLASS_MISMATCH"})
                        continue
                    selected = out / "source_request.json"
                    selected.write_bytes(request.read_bytes())
                    receipt = {
                        "kind": "adjacent_native_warlock_candidate",
                        "status": "NATIVE_PREPARED_NOT_YET_PAID",
                        "from_level": from_level, "to_level": to_level,
                        "original_source_sha256": sha256(source),
                        "native_binary_sha256": sha256(binary),
                        "paid_predecessor": predecessor,
                        "selected_source_sha256": sha256(selected),
                        "native_prepared_sha256": sha256(prepared),
                        "native_options_source_revision": options.get("source_revision"),
                        "source_talents": actor["talentsString"],
                        "candidate_talents": candidate_actor["talentsString"],
                        "selection": "native_prepared_talent_after_gear_recovery",
                        "talent_points_newly_spent": 1,
                        "field_name": field, "tree_index": ti,
                        "native_gear_kept": kept,
                        "native_gear_refusals": native_gear_refusals,
                        "attempted": len(rejected) + retry,
                        "native_refusals_before_selection": rejected,
                        "native_refusals_after_gear_recovery": recovered_refusals,
                        "next_step": "execute actual retained-actor hostile 100-kill native/gsim chain",
                    }
                    (out / "proposal.json").write_text(json.dumps(receipt, indent=2) + "\n")
                    return receipt
                selected = out / "source_request.json"
                selected.write_bytes(final_request.read_bytes())
                receipt = {
                    "kind": "adjacent_native_warlock_candidate",
                    "status": "NATIVE_PREPARED_NOT_YET_PAID",
                    "from_level": from_level, "to_level": to_level,
                    "original_source_sha256": sha256(source),
                    "native_binary_sha256": sha256(binary),
            "paid_predecessor": predecessor,
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
            "paid_predecessor": predecessor,
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
    parser.add_argument("--native-paid-shortlist", action="store_true",
                        help="Opt-in bounded cross-tree Rust prepare + balanced 30s paid screens; "
                             "does NOT select a 100-mob winner or change the default route")
    parser.add_argument("--predecessor-route", type=Path,
                        help="Require exact executed paid previous-level source receipt")
    parser.add_argument("--predecessor-binary-sha256",
                        help="Exact paid predecessor binary SHA256 when changing native engine; "
                             "requires --predecessor-route and never implies same-engine continuity")
    args = parser.parse_args()
    result = propose(**vars(args))
    print(json.dumps(result, indent=2))
    if result["status"] not in ("NATIVE_PREPARED_NOT_YET_PAID",
                               "NATIVE_SCREENED_NOT_WORLD_PAID"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
