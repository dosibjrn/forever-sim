#!/usr/bin/env python3
"""P7.3 preflight: enforce frozen reference dimensions; not a talent generator."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

REFERENCE_DPS = 728.1936126415858
PINNED_RUST_REVISION = "666fe17a42682068a3c8497d88d5fa3732cbdfb9"

def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def player(req):
    return req["raid"]["parties"][0]["players"][0]

def validate_reference(req):
    p = player(req)
    assert p.get("talentsString", p.get("talents")) == "5532220115501351--505", "incorrect saved reference talents"
    items = p["equipment"].get("items", []) if isinstance(p["equipment"], dict) else p["equipment"]
    assert len(items) == 16, "reference equipment must have sixteen slots"
    assert len(p["rotation"]["priorityList"]) == 10, "reference APL must contain ten priority entries"
    assert req["simOptions"]["iterations"] >= 1000, "insufficient baseline iteration count"
    return {"request_sha256": digest(req), "gear_sha256": digest(p["equipment"]),
            "apl_sha256": digest(p["rotation"]), "reference_dps": REFERENCE_DPS,
            "rust_revision": PINNED_RUST_REVISION}

def validate_candidate(reference, candidate):
    base = copy.deepcopy(reference)
    cand = copy.deepcopy(candidate)
    assert player(cand).get("talentsString", player(cand).get("talents")) != player(base).get("talentsString", player(base).get("talents")), "reference talents cannot seed search"
    assert player(cand)["equipment"] == player(base)["equipment"], "P7.3 equipment must remain frozen"
    assert player(cand)["rotation"] == player(base)["rotation"], "P7.3 APL must remain frozen"
    key = "talentsString" if "talentsString" in player(base) else "talents"
    player(cand)[key] = player(base)[key]
    assert cand == base, "P7.3 candidate changed another frozen request field"
    return {"talents": player(candidate).get("talentsString", player(candidate).get("talents")), "candidate_sha256": digest(candidate)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    ref = json.loads(args.reference.read_text())
    result = validate_reference(ref)
    if args.candidate:
        result["candidate"] = validate_candidate(ref, json.loads(args.candidate.read_text()))
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
