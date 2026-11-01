#!/usr/bin/env python3
"""Rust-only L60 28-profile diagnostic matrix (not PROCESS certification).

Uses the checkpoint registry, known pinned source requests and *only* the real
native Rust CLI for any reported score. The first breadth pass searches APL
only while gear/talent legality adapters remain unverified. This is labeled
PARTIAL_DIMENSIONS, never JOINT or P7 PASS.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from apl_mutation import mutate_apl
from native_matrix import enumerate_l60_profiles, search_native, next_budget
from p73_talent_search_v2 import run

ROOT = Path(__file__).resolve().parents[2]
P = "fixtures/mage/prepared-v2/"
V = "validation/2026-10-06-multi-target-"
W = "validation/2026-10-05-multi-target-references/"
H = "validation/2026-10-04-hunter-preset-matrix/variants/"

# These paths have been inspected in the PINNED source tree. Each external
# fixture is a smoke candidate, NOT a saved MythicSim ranking reference.
SOURCES = {
    "druid/balance": ("gsim", "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"),
    "druid/feral_cat": ("engine", V+"paladin-druid-references/feral-druid-2-targets.request.json"),
    "druid/feral_bear": ("engine", V+"paladin-druid-references/feral-bear-druid-2-targets.request.json"),
    "druid/restoration": ("engine", "fixtures/healers/restoration-druid.request.json"),
    "mage/arcane": ("engine", P+"arcane-reference.request.json"),
    "mage/fire": ("engine", P+"fire-reference.request.json"),
    "mage/frost": ("engine", P+"frost-reference.request.json"),
    "hunter/beast_mastery": ("engine", H+"preset-bm-bm-launch.request.json"),
    "hunter/marksmanship": ("engine", H+"preset-mm-mm-launch.request.json"),
    "hunter/survival": ("engine", H+"preset-sv-sv-launch.request.json"),
    "shaman/elemental": ("engine", V+"warrior-shaman-references/elemental-shaman-2-targets.request.json"),
    "shaman/enhancement": ("engine", V+"warrior-shaman-references/enhancement-shaman-2-targets.request.json"),
    "shaman/restoration": ("engine", "fixtures/healers/restoration-shaman.request.json"),
    "warrior/arms": ("engine", V+"warrior-shaman-references/arms-warrior-2-targets.request.json"),
    "warrior/fury": ("engine", P+"fury-warrior-battlegear-of-might-sapper.request.json"),
    "warrior/protection": ("engine", V+"warrior-shaman-references/protection-warrior-2-targets.request.json"),
    "rogue/assassination": ("engine", W+"assassination-rogue-2-targets.request.json"),
    "rogue/combat": ("engine", W+"combat-rogue-2-targets.request.json"),
    "rogue/subtlety": ("engine", W+"subtlety-rogue-2-targets.request.json"),
    # Smite Priest may use Discipline points but is NOT a verified Disc profile.
    "priest/discipline": ("engine", P+"production-smite-priest.request.json"),
    "priest/holy": ("engine", "fixtures/healers/holy-priest.request.json"),
    "priest/shadow": ("engine", W+"shadow-priest-2-targets.request.json"),
    "warlock/affliction": ("engine", "validation/2026-10-06-mage-warlock-multi-target-references/affliction-warlock-2-targets.request.json"),
    "warlock/demonology": ("engine", "validation/2026-10-06-mage-warlock-multi-target-references/demonology-warlock-2-targets.request.json"),
    "warlock/destruction": ("engine", "validation/2026-10-06-mage-warlock-multi-target-references/destruction-warlock-2-targets.request.json"),
    "paladin/holy": ("engine", P+"holy-paladin-healing.request.json"),
    "paladin/protection": ("engine", V+"paladin-druid-references/protection-paladin-2-targets.request.json"),
    "paladin/retribution": ("engine", V+"paladin-druid-references/retribution-paladin-2-targets.request.json"),
}
HEAL = {"druid/restoration", "shaman/restoration", "priest/holy", "paladin/holy"}
TANK = {"druid/feral_bear", "warrior/protection", "paladin/protection"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(obj) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def player(request):
    return request["raid"]["parties"][0]["players"][0]


def legal_apl_only_request(reference: dict, candidate: dict) -> bool:
    """Freeze every non-APL native field and source-bound cast identities.

    The APL grammar may reorder, insert source-backed casts and tune source
    predicates. It may not introduce another spell/item/other oneof, change an
    opaque native non-cast action, or silently mutate raid/encounter/talents/
    gear/simOptions. This is a legality guard, not a JOINT search adapter.
    """
    try:
        original = player(reference)["rotation"]["priorityList"]
        actions = player(candidate)["rotation"]["priorityList"]
        if not isinstance(original, list) or not original or not isinstance(actions, list) or not actions:
            return False
        def key(obj):
            return json.dumps(obj, sort_keys=True, separators=(",", ":"))
        casts = {
            key(a["action"]["castSpell"]["spellId"])
            for a in original if "castSpell" in a.get("action", {})
        }
        opaque = {
            key(a["action"]) for a in original
            if "castSpell" not in a.get("action", {})
        }
        for a in actions:
            action = a["action"]
            if "castSpell" in action:
                if key(action["castSpell"]["spellId"]) not in casts:
                    return False
            elif key(action) not in opaque:
                return False
        masked = copy.deepcopy(candidate)
        player(masked)["rotation"]["priorityList"] = copy.deepcopy(original)
        return masked == reference
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        return False


def entry(profile, source_kind, source):
    kind = "PINNED_RANKING_REFERENCE" if source_kind == "gsim" else "SMOKE_FIXTURE_ONLY"
    return {
        "profile_id": profile,
        "source_type": kind,
        "source_path": source,
        "source_sha256": None,
        "status": "BLOCKED_REFERENCE_MISSING",
        "dimensions_searched": [],
        "dimensions_blocked": ["gear", "talents"],
        "native_paid": 0,
        "baseline": None,
        "best": None,
        "delta": None,
        "objective": "HPS" if profile in HEAL else ("TPS" if profile in TANK else "DPS"),
        "blocker": "Source file not loaded",
    }



def load_native_item_index(engine_src: Path) -> dict[int, dict]:
    """Index pinned Rust items.jsonl, never an older gsim/Wowhead catalogue.

    These are native item identities, NOT a proof of class equip legality.
    Scaling options and effects remain owned by the Rust engine.
    """
    path = engine_src / "data/items.jsonl"
    items: dict[int, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid native item JSON") from exc
            item_id = item.get("id")
            if not isinstance(item_id, int) or item_id <= 0:
                raise ValueError(f"{path}:{line_number}: invalid native item ID {item_id!r}")
            if item_id in items:
                raise ValueError(f"{path}:{line_number}: duplicate native item ID {item_id}")
            items[item_id] = {
                key: item.get(key)
                for key in ("name", "type", "armor_type", "weapon_type", "hand_type",
                            "ranged_weapon_type", "class_allowlist", "required_level",
                            "unique", "limit_category", "required_profession", "phase")
            }
    if not items:
        raise ValueError(f"Native item catalogue empty: {path}")
    return items


def describe_native_gear(equipment: dict, item_index: dict[int, dict]) -> tuple[list[dict], list[int]]:
    """Audit source gear against native item identities, without inventing rules."""
    details: list[dict] = []
    missing: set[int] = set()
    for slot_index, entry in enumerate(equipment.get("items", [])):
        item_id = entry.get("id", 0)
        if not isinstance(item_id, int) or item_id < 0:
            raise ValueError(f"Invalid fixture item ID at slot index {slot_index}: {item_id!r}")
        if item_id == 0:
            continue  # Native equipment permits empty positions.
        record = {"source_slot_index": slot_index, "id": item_id,
                  "native_db_present": item_id in item_index}
        if item_id in item_index:
            record.update(item_index[item_id])
        else:
            missing.add(item_id)
        details.append(record)
    return details, sorted(missing)


def create_inventory(registry_path, engine_src):
    native_items = load_native_item_index(engine_src)
    registry = json.loads(registry_path.read_text())
    profiles = enumerate_l60_profiles(registry)
    if len(profiles) != 28 or len({cl for cl, _ in profiles}) != 9:
        raise ValueError("Invalid canonical fixed L60 registry (expected 28 / nine classes)")
    if set(SOURCES) != {cl+"/"+sp for cl, sp in profiles}:
        raise ValueError("Source map must cover every canonical profile once")
    rows = []
    for cl, sp in profiles:
        profile = cl+"/"+sp
        kind, relative = SOURCES[profile]
        path = (ROOT if kind == "gsim" else engine_src)/relative
        row = entry(profile,kind,relative)
        if not path.is_file():
            row["blocker"] = "NO_NATIVE_REQUEST: source does not exist: "+str(path)
            rows.append((row, None))
            continue
        try:
            request = json.loads(path.read_text())
            pl = player(request)
            if pl["class"] != "Class"+cl.capitalize():
                raise ValueError("Class identity mismatch: "+str(pl["class"]))
            if not pl.get("equipment",{}).get("items"):
                raise ValueError("Empty source equipment")
            if not pl.get("talentsString"):
                raise ValueError("Missing source talents")
            if not request.get("simOptions"):
                raise ValueError("Missing native simOptions")
            row["source_sha256"] = digest(path)
            row["item_count"] = len(pl["equipment"]["items"])
            row["native_item_inventory"], missing_ids = describe_native_gear(
                pl["equipment"], native_items
            )
            row["native_db_missing_item_ids"] = missing_ids
            if missing_ids:
                row["status"] = "BLOCKED_NATIVE_ITEM_DB"
                row["blocker"] = "Native items.jsonl missing source IDs: " + str(missing_ids)
                rows.append((row, None))
                continue
            row["native_oneofs"] = [k for k in pl if k.lower().endswith(("druid","warrior","mage","priest","shaman","hunter","rogue","warlock","paladin")) and k != "class"]
            row["status"] = "REFERENCE_READY" if kind == "gsim" else "SMOKE_FIXTURE_ONLY"
            row["blocker"] = None
            rows.append((row,request))
        except Exception as exc:
            row["status"] = "BLOCKED_REQUEST_PARSE"
            row["blocker"] = "REQUEST_PARSE: "+str(exc)
            rows.append((row,None))
    return rows


def execute_row(row, reference, *, binary, budget, iterations, seed, outdir):
    profile = row["profile_id"]
    if reference is None:
        return row
    if profile == "priest/discipline":
        row["status"] = "BLOCKED_SPEC_IDENTITY"
        row["blocker"] = "Only Smite Priest fixture; no verified Discipline profile identity"
        return row
    if profile in HEAL or profile in TANK:
        row["status"] = "BLOCKED_OBJECTIVE"
        row["blocker"] = ("HPS" if profile in HEAL else "TPS")+" extractor/comparable native fixture not yet verified"
        return row
    actions = player(reference).get("rotation",{}).get("priorityList")
    if not isinstance(actions,list) or not actions:
        row["status"] = "BLOCKED_APL"
        row["blocker"] = "No nonempty source APL priorityList"
        return row
    safe_name = profile.replace("/","__")
    rowdir = outdir/"profiles"/safe_name
    rowdir.mkdir(parents=True,exist_ok=True)
    (rowdir/"source_request.json").write_text(json.dumps(reference,indent=2))
    base_seed = int(reference["simOptions"].get("randomSeed","42"))
    baseline_deadline = time.monotonic()+30
    try:
        baseline, _, latency, _ = run(binary,reference,iterations,base_seed,"stochastic",baseline_deadline)
        if not math.isfinite(baseline):
            raise ValueError("Non-finite native baseline")
        row["baseline"] = baseline
        row["baseline_duration_s"] = latency
    except Exception as exc:
        row["status"] = "BLOCKED_NATIVE_BASELINE"
        row["blocker"] = ("RUST_UNSUPPORTED_REQUEST: "+str(exc))[:700]
        return row

    errors = []
    failure_repros = []
    deadline = time.monotonic()+budget

    def propose(rng):
        req = copy.deepcopy(reference)
        player(req)["rotation"]["priorityList"] = mutate_apl(None,actions,rng,cold=True)
        return req

    def mutate(req,rng):
        out = copy.deepcopy(req)
        player(out)["rotation"]["priorityList"] = mutate_apl(
            player(out)["rotation"]["priorityList"],actions,rng
        )
        return out

    def legal(req):
        return legal_apl_only_request(reference, req)

    def evaluate(req, *, iterations, seed, rng_mode):
        try:
            metric,_,_,_ = run(binary,req,iterations,seed,rng_mode,deadline)
            return metric
        except (TimeoutError, subprocess.TimeoutExpired):
            raise  # ordinary strict-budget expiry; not a native engine failure
        except Exception as exc:
            errors.append(str(exc)[:900])
            # Preserve the exact native request that triggered a failure.
            # Without it a Rust panic cannot become a minimal regression.
            # Bound artifact growth for repeated stochastic failures.
            if len(failure_repros) < 3:
                path = rowdir / f"native_failure_{len(failure_repros):03}.request.json"
                path.write_text(json.dumps(req, indent=2))
                failure_repros.append({
                    "request_path": str(path.relative_to(outdir)),
                    "request_sha256": digest(path),
                    "error": str(exc)[:900],
                })
            raise

    result = search_native(
        profile_id=profile,reference=reference,propose=propose,mutate=mutate,
        legal=legal,evaluate=evaluate,seconds=budget,
        iterations=iterations,seed=seed,clock=time.monotonic
    )
    row["native_paid"] = result["paid_candidates"]
    row["engine_errors"] = result["engine_errors"]
    row["native_failure_repros"] = failure_repros
    row["rejected_legal"] = result["legal_rejections"]
    row["elapsed_search_s"] = result["elapsed_s"]
    row["best"] = result["best_score"]
    # Never compare a stochastic baseline directly with balanced-RNG search.
    # A stochastic rerank/holdout is a separate follow-on stage.
    row["delta"] = None
    row["baseline_rng_mode"] = "stochastic"
    row["search_rng_mode"] = "balanced"
    row["metric_comparison"] = "NOT_COMPARABLE_DIFFERENT_RNG_MODE"
    row["dimensions_searched"] = ["apl"]
    row["dimensions_blocked"] = ["gear","talents"]
    row["native_status"] = result["status"]
    row["stochastic_holdout"] = "NOT_RUN"
    row["promotable"] = False  # not certified JOINT; C gear/talent adapters still absent
    row["status"] = ("PARTIAL_DIMENSIONS" if result["status"] == "RAN" else result["status"])
    row["blocker"] = (
        "PARTIAL_DIMENSIONS: item legality/pools and class talent tree missing; APL_ONLY"
        if result["status"] == "RAN" else
        (errors[0] if errors else result["status"])
    )
    (rowdir/"result.json").write_text(json.dumps(row,indent=2))
    (rowdir/"native_errors.json").write_text(json.dumps(errors,indent=2))
    if result["best_candidate"] is not None:
        (rowdir/"best_request.json").write_text(json.dumps(result["best_candidate"],indent=2))
        row["best_request_sha256"] = digest(rowdir/"best_request.json")
    return row


def report(rows,outdir,*,binary,engine_src,budget,inventory_only):
    matrix = {
        "scope": "RUST_NATIVE_L60_DIAGNOSTIC_NOT_PROCESS_P7_PASS",
        "requested_search": "JOINT",
        "actual_search": "APL_ONLY where runnable; no gear/talent adapter yet",
        "budget_per_profile_s": budget,
        "inventory_only": inventory_only,
        "native_binary_sha256": digest(binary) if binary and binary.is_file() else None,
        "engine_items_sha256": digest(engine_src/"data/items.jsonl") if (engine_src/"data/items.jsonl").is_file() else None,
        "engine_enchants_sha256": digest(engine_src/"data/enchants.jsonl") if (engine_src/"data/enchants.jsonl").is_file() else None,
        "engine_spells_sha256": digest(engine_src/"data/spells.jsonl") if (engine_src/"data/spells.jsonl").is_file() else None,
        "rows": rows,
    }
    outdir.mkdir(parents=True,exist_ok=True)
    (outdir/"matrix.json").write_text(json.dumps(matrix,indent=2))
    columns = ["class/spec","source","searched","paid","baseline","best","delta","status/blocker"]
    lines=["# Native Rust L60 diagnostic matrix","",
           "**Not a JOINT/P7 PASS:** available profiles have APL-only native screening until source-legal class talent and Rust item adapters exist.","",
           "| "+" | ".join(columns)+" |","|"+"|".join(["---"]*len(columns))+"|"]
    for x in rows:
        def val(v):
            return "%.3f"%v if isinstance(v,float) else str(v if v is not None else "-")
        lines.append("| "+" | ".join([
            x["profile_id"],x["source_type"],",".join(x["dimensions_searched"]) or "-",
            str(x["native_paid"]),val(x["baseline"]),val(x["best"]),val(x["delta"]),
            x["status"]+": "+str(x.get("blocker") or "-").replace("|","/")[:95]
        ])+" |")
    counts=Counter(x["status"] for x in rows)
    lines.extend(["","Status counts: "+str(dict(counts)),"",
                  "This report includes every checkpoint L60 fixed profile, including BLOCKED rows."])
    (outdir/"matrix.md").write_text("\n".join(lines)+"\n")
    gaps = []
    for x in rows:
        if x.get("blocker"):
            gaps.append({"profile_id":x["profile_id"],"category":x["status"],
                         "reason":x["blocker"],"source":x["source_path"]})
    (outdir/"gaps.json").write_text(json.dumps(gaps,indent=2))


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--engine-src",type=Path,required=True)
    ap.add_argument("--binary",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--budget",type=float,default=5.0)
    ap.add_argument("--screen-iterations",type=int,default=10)
    ap.add_argument("--seed",type=int,default=678)
    ap.add_argument("--only",action="append",help="Filter 'class/spec' (can repeat)")
    ap.add_argument("--inventory-only",action="store_true")
    args=ap.parse_args()
    if not args.inventory_only and (args.binary is None or not args.binary.is_file()):
        ap.error("--binary must be a real runnable native executable")
    records=create_inventory(ROOT/"config/validation/checkpoint_148.json",args.engine_src)
    rows=[]
    for idx,(row,request) in enumerate(records):
        if not args.inventory_only and (not args.only or row["profile_id"] in args.only):
            if request is not None:
                row=execute_row(row,request,binary=args.binary,budget=args.budget,
                                iterations=args.screen_iterations,seed=args.seed+idx,
                                outdir=args.out)
        elif args.only and row["profile_id"] not in args.only:
            row["status"]="SKIPPED_FILTER"
            row["blocker"]="Not selected in filtered smoke invocation"
        rows.append(row)
    report(rows,args.out,binary=args.binary,engine_src=args.engine_src,
           budget=args.budget,inventory_only=args.inventory_only)
    assert len(rows)==28 and len({r["profile_id"] for r in rows})==28
    print(json.dumps({"rows":len(rows),"status_counts":dict(Counter(x["status"] for x in rows)),
                      "actual_search":"APL_ONLY; no JOINT claim"},indent=2))


if __name__=="__main__":
    main()
