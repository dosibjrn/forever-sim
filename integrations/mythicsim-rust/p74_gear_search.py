#!/usr/bin/env python3
"""P7.4 gear-search helpers; live candidate pools come from pinned Rust data."""
import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import subprocess
import tempfile
import time

from p74_preflight import preflight, player
from p74_gear_validation import GearValidator, RejectedGear, RUST_TYPES, SLOTS, SOURCE_SLOTS, read_jsonl, sha256

REFERENCE_DPS = 728.1936126415858

class NativeFailure(RuntimeError):
    def __init__(self, category, detail, returncode=None):
        super().__init__(detail)
        self.category, self.returncode = category, returncode

def _write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n")

def candidate_pool(validator, limit, *, independent_enchants=False,
                   native_authoritative=False):
    """Build gear proposals from the source catalogue.

    The default retains the legacy Python admission behavior. The live P7.4
    caller sets native_authoritative=True: slot membership and stat columns
    shape the proposal distribution only; GearValidator.item() is not called.
    Every complete proposed request is then sent to selected native sim before
    it can reach the live 2D world. Native INVALID/UNSUPPORTED/errors are final.
    """
    con=validator.connection
    pool={}; exclusions=Counter()
    for i,slot in enumerate(SLOTS):
        src_slots=SOURCE_SLOTS.get(slot,(slot,))
        q=",".join("?" for _ in src_slots)
        rows=con.execute(
            f"SELECT * FROM items WHERE slot IN ({q}) AND item_id>0 ORDER BY item_id",
            src_slots)
        good=[]
        for row in rows:
            r=dict(row); iid=int(r["item_id"])
            if not native_authoritative:
                try:
                    if independent_enchants:
                        validator.item(i, iid, 0)
                    else:
                        validator.item(i, iid)
                except RejectedGear as exc:
                    exclusions[exc.category]+=1
                    continue
            score=(r["spell_power"] or 0)+.5*(r["intellect"] or 0)+1.5*(r["hit"] or 0)+1.3*(r["crit"] or 0)+.1*(r["spirit"] or 0)
            good.append((score,iid))
        good.sort(key=lambda x:(-x[0],x[1]))
        ids=[iid for _,iid in good[:limit]]
        if not ids:
            if native_authoritative:
                raise ValueError(f"No source item proposals: slot={slot}, index={i}")
            raise ValueError(f"No PINNED-RUST legal source candidates: slot={slot}, index={i}, excluded={dict(exclusions)}")
        pool[i]=ids
    return pool,exclusions



def pinned_rust_candidate_pool(items_path, enchants_path):
    """Build P7.4 proposals directly from the pinned Rust JSONL data tables.

    This reads Rust's own item/enchant rows, not the Forever SQLite catalogue.
    It applies only slot-shape and proposal-ranking logic; complete candidate
    acceptance remains the paid native source-control simulation.
    """
    rust_items = read_jsonl(items_path)
    rust_enchants = read_jsonl(enchants_path, key="effect_id")
    pool = {}
    enchant_pools = {}
    for slot_index, slot in enumerate(SLOTS):
        item_type = RUST_TYPES[slot]
        candidates = []
        for row in rust_items.values():
            if not isinstance(row, dict) or row.get("type") != item_type:
                continue
            item_id = row.get("id")
            if type(item_id) is not int or item_id <= 0:
                continue
            scaling_options = row.get("scaling_options")
            if not isinstance(scaling_options, dict):
                continue
            scaling = scaling_options.get("0", scaling_options.get(0))
            if not isinstance(scaling, dict):
                continue
            # Native relics such as druid idols carry their behavior in
            # item_effects and legitimately have no stat map. Keep them in
            # the source proposal universe with a zero stat-order score;
            # native prepare/execute remains the only legality/effect gate.
            stats = scaling.get("stats")
            if stats is None:
                stats = {}
            if not isinstance(stats, dict):
                continue
            if slot == "weapon":
                if row.get("hand_type") not in (
                    "HandTypeOneHand", "HandTypeMainHand",
                    "HandTypeTwoHand", "HandTypeUnknown",
                ) or row.get("weapon_type") == "WeaponTypeShield":
                    continue
            if slot == "relic" and row.get("ranged_weapon_type") not in (
                "RangedWeaponTypeIdol", "RangedWeaponTypeUnknown", "",
            ):
                continue

            def stat(index):
                value = stats.get(str(index), stats.get(index, 0.0))
                return (float(value) if type(value) in (int, float)
                        and math.isfinite(value) else 0.0)

            score = (stat(5) + .5 * stat(3) + 1.5 * stat(12)
                     + 1.3 * stat(13) + .1 * stat(16))
            candidates.append((score, item_id))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        if not candidates:
            raise ValueError(
                f"No pinned Rust item options for slot={slot}, type={item_type}"
            )
        pool[slot_index] = [item_id for _, item_id in candidates]

        valid_enchant_types = {
            item_type,
            "EnchantType" + item_type.removeprefix("ItemType"),
        }
        if slot == "weapon":
            valid_enchant_types.add("EnchantTypeWeapon")
        choices = [None]
        for enchant in rust_enchants.values():
            if not isinstance(enchant, dict):
                continue
            enchant_id = enchant.get("effect_id")
            if type(enchant_id) is not int or enchant_id <= 0:
                continue
            types = [
                str(enchant.get("type") or ""),
                str(enchant.get("enchant_type") or ""),
            ]
            types.extend(str(value) for value in (enchant.get("extra_types") or []))
            if any(
                value in valid_enchant_types
                or value.endswith("All")
                or value.endswith("Any")
                for value in types
            ):
                choices.append(enchant_id)
        enchant_pools[slot_index] = list(dict.fromkeys(choices))

    metadata = {
        "unique_item_options": len({
            item_id for candidates in pool.values() for item_id in candidates
        }),
        "unique_enchant_options": len({
            enchant_id for choices in enchant_pools.values()
            for enchant_id in choices if enchant_id is not None
        }),
    }
    return pool, enchant_pools, metadata

def source_enchant_pools(validator, pools):
    """Enumerate slot-legal native enchants; never whitelist saved gear only.

    The selected GearValidator enforces native enchant existence and slot
    restrictions in item(); candidate loadouts are validated again afterwards.
    """
    enchant_ids = sorted(int(e) for e in validator.enchants if int(e) > 0)
    result = {}
    for slot in range(len(pools)):
        if not pools.get(slot):
            raise ValueError("NO_SOURCE_LEGAL_GEAR_FOR_ENCHANT_SLOT")
        anchor = pools[slot][0]
        options = [None]
        for enchant_id in enchant_ids:
            try:
                validator.item(slot, anchor, enchant_id)
            except RejectedGear:
                continue
            options.append(enchant_id)
        result[slot] = options
    return result


def simulate(binary, request, mode, iterations, seed, deadline):
    remaining=deadline-time.monotonic()
    if remaining<=0.05:raise TimeoutError("native deadline exhausted")
    req=copy.deepcopy(request)
    req["simOptions"]["iterations"]=iterations
    req["simOptions"]["randomSeed"]=str(seed)
    with tempfile.TemporaryDirectory() as d:
        a,b=Path(d)/"request.json",Path(d)/"result.json"
        _write(a,req)
        try:
            run=subprocess.run(
                [str(binary.resolve()),"sim","--request",str(a),"--outfile",str(b),"--gate","--rng-mode",mode],
                capture_output=True,text=True,
                timeout=max(.01,remaining))
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("strict native simulation deadline exhausted") from exc
        # Rust may report a refusal on stdout, not stderr.
        raw=(run.stdout or "")+"\n"+(run.stderr or "")
        if run.returncode:
            category="engine_refusal"
            lower=raw.lower()
            if "unknown_item" in lower or "no item with id" in lower: category="unknown_item"
            elif "unsupported" in lower or "not implemented" in lower: category="unsupported_effect"
            elif "enchant" in lower: category="enchant"
            raise NativeFailure(category,raw[-2500:] or f"exit={run.returncode} without diagnostics",run.returncode)
        if not b.exists():
            raise NativeFailure("missing_result","native exit 0 but no output; stdout/stderr: "+raw[-1800:],run.returncode)
        try:
            obj=json.loads(b.read_text())
            score=float(obj["result"]["raidMetrics"]["dps"]["avg"])
            if not math.isfinite(score):raise ValueError("non-finite DPS")
            return score
        except (ValueError,TypeError,KeyError) as exc:
            raise NativeFailure("malformed_result",f"{exc}; result={b.read_text()[:900]}; log={raw[-900:]}") from exc

def _swap(reference, ids):
    req=copy.deepcopy(reference)
    for slot,iid in zip(player(req)["equipment"]["items"],ids):
        slot["id"]=iid
    preflight(reference,req)
    return req

def main():
    p=argparse.ArgumentParser()
    for name in ("binary","reference","catalogue","engine-items","engine-enchants","outdir"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--seconds",type=float,default=300)
    p.add_argument("--screen-iterations",type=int,default=60)
    p.add_argument("--holdout-iterations",type=int,default=4000)
    p.add_argument("--pool-per-slot",type=int,default=80)
    p.add_argument("--seed",type=int,default=667)
    a=p.parse_args()
    if a.seconds<=0 or a.screen_iterations<1 or a.holdout_iterations<1 or a.pool_per_slot<1:
        p.error("positive budget, iteration counts and pool size required")
    started=time.monotonic()
    deadline=started+a.seconds
    a.outdir.mkdir(parents=True,exist_ok=True)
    reference=json.loads(a.reference.read_text())
    fixed=preflight(reference)
    validator=GearValidator(a.catalogue,a.engine_items,a.engine_enchants,reference)
    original=[x["id"] for x in player(reference)["equipment"]["items"]]
    # Cold optimization must not SEED the saved reference, but a naturally
    # rediscovered reference loadout remains legal for validation and scoring.
    seen=set()
    elites=[]; paid=[]; failed=[];rejected=[]
    reranked=[];winner=None;holdout=None;pool={}
    engine_sha=sha256(a.binary)
    # All evidence is flushed even if a native refusal, no results, or deadline blocks.
    try:
        pool,excluded=candidate_pool(validator,a.pool_per_slot)
        rng=random.Random(a.seed)
        search_seed=int(reference["simOptions"]["randomSeed"])
        screen_end=deadline-min(90,a.seconds*.32)
        while time.monotonic()<screen_end-.1:
            if elites and rng.random()<.8:
                ids=list(rng.choice(elites[:min(15,len(elites))])[1])
                for _ in range(rng.randint(1,5)):
                    j=rng.randrange(16);ids[j]=rng.choice(pool[j])
            else:
                ids=[rng.choice(pool[j]) for j in range(16)]
            if tuple(ids) in seen:continue
            seen.add(tuple(ids))
            try:
                validator.validate(ids)
                req=_swap(reference,ids)
                score=simulate(a.binary,req,"balanced",a.screen_iterations,search_seed,screen_end)
                entry={"ids":ids,"screen_dps":score}
                paid.append(entry)
                elites.append((score,ids))
                elites.sort(reverse=True)
                elites=elites[:24]
            except RejectedGear as exc:
                rejected.append({"ids":ids,"category":exc.category,"slot":exc.slot,
                                 "item_id":exc.item_id,"error":str(exc)})
            except (TimeoutError,subprocess.TimeoutExpired):
                break
            except NativeFailure as exc:
                failed.append({"ids":ids,"phase":"screen","category":exc.category,
                               "returncode":exc.returncode,"error":str(exc)})
        finalists=sorted(paid,key=lambda x:-x["screen_dps"])[:20]
        rerank_end=deadline-min(20,a.seconds*.075)
        for candidate in finalists:
            if time.monotonic()>rerank_end-.1:break
            req=_swap(reference,candidate["ids"])
            try:
                score=simulate(a.binary,req,"balanced",2000,search_seed+555123,rerank_end)
                reranked.append({**candidate,"rerank_dps":score})
            except (TimeoutError,subprocess.TimeoutExpired):break
            except NativeFailure as exc:
                failed.append({"ids":candidate["ids"],"phase":"rerank",
                               "category":exc.category,"returncode":exc.returncode,"error":str(exc)})
        if not reranked:raise RuntimeError("no successful balanced reranking: see failures.json")
        winner=max(reranked,key=lambda x:x["rerank_dps"])
        audit=validator.audit(winner["ids"])
        req=_swap(reference,winner["ids"])
        _write(a.outdir/"frozen_winner_request.json",req)
        _write(a.outdir/"winner_identity_audit.json",audit)
        holdout=simulate(a.binary,req,"stochastic",a.holdout_iterations,a.seed+1300000007,deadline)
        if time.monotonic()>deadline:raise TimeoutError("strict P7.4 end-to-end deadline exceeded")
    finally:
        validator.close()
        _write(a.outdir/"paid_candidates.json",paid)
        _write(a.outdir/"failures.json",failed)
        _write(a.outdir/"rejected_combinations.json",rejected)
        _write(a.outdir/"reranked.json",reranked)
        report={"status":"NATIVE_P74_DIAGNOSTIC_NOT_LIVE_2D",
                "reference_dps":REFERENCE_DPS, "winner":winner,"holdout_dps":holdout,
                "point_estimate_ge_99pct_reference":holdout is not None and holdout>=.99*REFERENCE_DPS,
                "paid":len(paid),"native_failures":len(failed),"legality_rejections":len(rejected),
                "native_failure_categories":dict(Counter(x["category"] for x in failed)),
                "legality_rejection_categories":dict(Counter(x["category"] for x in rejected)),
                "attempt_denominator":len(paid)+len(failed)+len(rejected),
                "elapsed_s":time.monotonic()-started,
                "binary_sha256":engine_sha,
                "reference_frozen":fixed,
                "catalogue_sha256":sha256(a.catalogue),
                "engine_items_sha256":sha256(a.engine_items),
                "engine_enchants_sha256":sha256(a.engine_enchants),
                "source_pool_counts":{str(k):len(v) for k,v in pool.items()},
                "limitations":["No verified live gsim-2D/Rust causal trace",
                               "Unrecorded faction, profession or phase restrictions not certified",
                               "Successful native evaluation does not prove full item-effect parity"]}
        _write(a.outdir/"report.json",report)
    print(json.dumps(report,indent=2))
    if not paid or holdout is None:raise RuntimeError("P7.4 incomplete native diagnostic; inspect report/failures")

if __name__=="__main__":
    main()
