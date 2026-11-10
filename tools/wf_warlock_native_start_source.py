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
import subprocess
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_prepared_source(*, binary: Path, source: Path, out: Path,
                           actor_level: int = 20) -> dict:
    if not 10 <= actor_level <= 60 or not binary.is_file() or not source.is_file():
        raise ValueError("existing native binary/source and actor level 10..60 required")
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

    def ask_native(tag: str, equipment: list[dict]) -> Path | None:
        request = copy.deepcopy(original)
        request["raid"]["parties"][0]["players"][0]["equipment"]["items"] = (
            copy.deepcopy(equipment))
        request_path = attempts / f"{tag}.json"
        prepared_path = attempts / f"{tag}.prepared.json"
        request_path.write_text(json.dumps(request, indent=2) + "\n")
        process = subprocess.run(
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

    receipt = {
        "kind": "warlock_native_same_level_equipment_proposal",
        "status": ("NATIVE_PREPARED_NOT_YET_PAID" if selected else
                   "NATIVE_PREPARE_REFUSED_ALL_SOURCES"),
        "actor_level": actor_level,
        "native_binary_sha256": _sha256(binary),
        "original_source_sha256": _sha256(source),
        "proposals_prepared": len(accepted),
        "proposals_refused": len(refusals),
        "kept_equipment_slots": kept_slots,
        "native_refusals": refusals,
        "native_accepted": accepted,
    }
    if selected is not None:
        final = out / "source_request.json"
        final.write_bytes(selected.read_bytes())
        receipt["selected_source_sha256"] = _sha256(final)
        receipt["next_step"] = "execute actual hostile retained 100-target native/gsim chain"
    (out / "proposal.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--actor-level", type=int, default=20)
    args = parser.parse_args()
    receipt = select_prepared_source(binary=args.binary, source=args.source,
                                     out=args.out, actor_level=args.actor_level)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0 if receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID" else 2


if __name__ == "__main__":
    raise SystemExit(main())
