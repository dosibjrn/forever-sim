#!/usr/bin/env python3
"""Live Rust-owned Warlock proposals for the one-call native range optimizer.

The source binary provides options and prepares each same-level talent proposal.
A prepared actor is not evidence of cross-level continuity: until native
continuation is proved, non-root requests return an explicit refusal.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _variants(seed: str, trees: list[dict]):
    """Propose rank transfers among Rust-listed slots; Rust judges legality."""
    fields = seed.split("-")
    if len(fields) != 3 or not all(s.isascii() and s.isdigit() for s in fields):
        raise ValueError("source talents are not three numeric trees")
    yield seed
    seen = {seed}
    for tree_index, tree in enumerate(trees):
        slots = tree.get("talents")
        if not isinstance(slots, list):
            raise ValueError("native options lack tree slots")
        for from_slot in slots:
            src = from_slot.get("index")
            if type(src) is not int or src < 0:
                raise ValueError("native option source index invalid")
            before = int(fields[tree_index][src]) if src < len(fields[tree_index]) else 0
            if before == 0:
                continue
            for to_slot in slots:
                dst, cap = to_slot.get("index"), to_slot.get("max_rank")
                if (type(dst) is not int or type(cap) is not int or dst < 0
                        or cap < 1 or dst == src):
                    continue
                current = int(fields[tree_index][dst]) if dst < len(fields[tree_index]) else 0
                if current >= cap:
                    continue
                mutated = list(fields)
                digits = list(mutated[tree_index])
                digits.extend("0" for _ in range(max(src, dst) + 1 - len(digits)))
                digits[src] = str(before - 1)
                digits[dst] = str(current + 1)
                mutated[tree_index] = "".join(digits)
                candidate = "-".join(mutated)
                if candidate not in seen:
                    seen.add(candidate)
                    yield candidate


def produce_frontier(
    request: dict[str, Any], *, binary: Path, seed_source: Path, out: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Return exact native-prepared files, or native continuation refusal."""
    level, budget = request.get("level"), request.get("budget")
    if (type(level) is not int or not 10 <= level <= 60
            or type(budget) is not int or budget < 1
            or request.get("rng_mode") != "balanced"
            or request.get("iterations") != 1
            or request.get("recover_to_full") is not True
            or type(request.get("mob_count")) is not int
            or not 1 <= request["mob_count"] <= 100):
        raise ValueError("INVALID_NATIVE_FRONTIER_REQUEST")
    if request.get("parent") is not None:
        # No guess at skipped-level talent/actor ancestry. An actual native
        # source continuation ACK must precede paying this path.
        return {"entries": [], "refusals": [{
            "candidate_id": None, "status": "NATIVE_CONTINUITY_NOT_ATTESTED",
            "native_refusal": "native source/actor continuation receipt is required",
            "native_prepared": False, "level": level,
        }]}
    if not binary.is_file() or not seed_source.is_file():
        raise ValueError("PINNED_NATIVE_BINARY_OR_SOURCE_MISSING")
    seed = json.loads(seed_source.read_text())
    actor = seed["raid"]["parties"][0]["players"][0]
    if (actor.get("class") != "ClassWarlock" or actor.get("level") != level
            or seed["encounter"]["targets"][0].get("level") != level):
        raise ValueError("NATIVE_SOURCE_ROOT_ACTOR_OR_TARGET_LEVEL_MISMATCH")
    options_result = runner([
        str(binary.resolve()), "options", "--class", "warlock", "--level", str(level),
    ], capture_output=True, text=True, timeout=60, check=False)
    if options_result.returncode:
        return {"entries": [], "refusals": [{
            "candidate_id": None, "status": "NATIVE_OPTIONS_REFUSED",
            "native_refusal": (options_result.stderr or options_result.stdout)[-1500:],
            "native_prepared": False, "level": level,
        }]}
    options = json.loads(options_result.stdout)
    talents = options.get("talents", {})
    trees = talents.get("trees")
    if (options.get("level") != level or talents.get("status") != "ok"
            or not isinstance(trees, list) or len(trees) != 3):
        raise ValueError("NATIVE_OPTIONS_INCOMPLETE_FOR_SOURCE_PROPOSALS")

    out.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    refusals: list[dict] = []
    # Accepted proposals and native prepare refusals share the supplied
    # candidate budget. No extra unpaid attempts are hidden from the caller.
    for index, talents_string in enumerate(_variants(actor["talentsString"], trees)):
        if index >= budget:
            break
        cid = f"source_{index:03d}"
        proposal = copy.deepcopy(seed)
        proposal["raid"]["parties"][0]["players"][0]["talentsString"] = talents_string
        source_path = out / f"{cid}.source.json"
        prepared_path = out / f"{cid}.prepared.json"
        source_path.write_text(json.dumps(proposal, sort_keys=True) + "\n")
        prepared_path.unlink(missing_ok=True)
        try:
            result = runner([
                str(binary.resolve()), "prepare", "--request", str(source_path.resolve()),
                "--actor-level", str(level), "--outfile", str(prepared_path.resolve()),
            ], capture_output=True, text=True, timeout=60, check=False)
            if result.returncode:
                raise ValueError((result.stderr or result.stdout)[-1500:])
            prepared = json.loads(prepared_path.read_text())
            player = prepared["player"]
            if (prepared.get("request_sha256") != _sha256(source_path)
                    or player.get("class") != "ClassWarlock"
                    or player.get("level") != level):
                raise ValueError("prepared native source/actor identity mismatch")
        except (KeyError, ValueError, TypeError, OSError, subprocess.TimeoutExpired) as exc:
            refusals.append({"candidate_id": cid, "status": "NATIVE_PREPARE_REFUSED",
                             "native_prepared": False, "native_refusal": str(exc)[-1500:]})
            continue
        entries.append({"id": cid, "level": level, "parent_source_sha256": None,
                        "source_request": str(source_path.resolve()),
                        "prepared": str(prepared_path.resolve())})
    return {"entries": entries, "refusals": refusals,
            "native_binary_sha256": _sha256(binary), "level": level,
            "source_root_sha256": _sha256(seed_source)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--seed-source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    request = json.load(sys.stdin)
    result = produce_frontier(request, binary=args.binary, seed_source=args.seed_source,
                              out=args.out / f"L{request['level']}")
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
