#!/usr/bin/env python3
"""WF670: cold joint gear × talents × APL native search; diagnostic only.

Native Rust is genuine; live 2D↔native causality and joint legality beyond
catalogue filters still need audit. Neither saved reference nor P7.1–P7.4
winners initialize the search population.
"""
import argparse,copy,json,random,re,sqlite3,subprocess,time
from pathlib import Path
from p73_talent_search_v2 import random_build,edit_neighbors,encode,parse,run,sha,player
from p74_gear_search import candidate_pool, source_enchant_pools
from p74_gear_validation import GearValidator, RejectedGear, sha256
from apl_mutation import mutate_apl

REFERENCE_DPS=728.1936126415858
# P7.4 WF669's 797.362 DPS was not a validated, accepted prior. The
# PROCESS v2.10 prior floor must be supplied separately with provenance.

def pick_gear(pool,rng):
    """Source-score biased but cold; never derives from reference or past winners."""
    if rng.random()<0.13:
        return rng.choice(pool)
    return pool[min(len(pool)-1,int(rng.expovariate(0.15)))]

def make_candidate(reference,pools,rng,elite=None,item_names=None,enchant_pools=None,repair_axes=None):
    """Independent cold generation; later mutations improve one axis at a time.

    A gear slot's captured reference enchant is a *per-slot option*, not a
    saved loadout seed. The additional 'none' option keeps enchant free.
    In selected full live search, enchant_pools are native-data proposals rather
    than a Python-filtered subset of the reference's enchant choices.
    """
    q=copy.deepcopy(reference)
    template=player(reference)["equipment"]["items"]
    allowed_enchants=[item.get("enchant") for item in template]
    # Old standalone diagnostics retain their historical reference/no-enchant
    # choices. The selected full 2D production search supplies every enchant
    # admitted for this slot by the existing pinned Rust/source validator.
    if enchant_pools is not None:
        enchant_choices={i:list(enchant_pools[i]) for i in range(len(template))}
    else:
        enchant_choices={i:[None]+([e] if e is not None else [])
                         for i,e in enumerate(allowed_enchants)}
    if elite is not None:
        base=player(elite)
        ids=[item["id"] for item in base["equipment"]["items"]]
        enchants=[item.get("enchant") for item in base["equipment"]["items"]]
        ranks=parse(base["talentsString"])
        actions=copy.deepcopy(base["rotation"]["priorityList"])
        axes=(repair_axes if repair_axes is not None else
              (rng.choices(("gear","talents","rotation","enchant"),
                           weights=(50,27,18,5))[0],))
        allowed=("gear","talents","rotation","enchant",
                 "gear_rebuild","talents_rebuild","rotation_rebuild")
        if (not isinstance(axes, tuple) or not axes or
                any(a not in allowed for a in axes)):
            raise ValueError("INVALID_REPAIR_AXES")
        for axis in axes:
            if axis=="gear":
                for _ in range(1 if rng.random()<0.8 else 2):
                    j=rng.randrange(16)
                    ids[j]=pick_gear(pools[j],rng)
            elif axis=="talents":
                ranks=edit_neighbors(ranks,rng,native_authoritative=True)
            elif axis=="rotation":
                actions=mutate_apl(actions,player(reference)["rotation"]["priorityList"],rng)
            elif axis=="gear_rebuild":
                ids=[pick_gear(pools[j],rng) for j in range(16)]
                enchants=[rng.choice(enchant_choices[i]) for i in range(16)]
            elif axis=="talents_rebuild":
                ranks=random_build(rng,native_authoritative=True)
            elif axis=="rotation_rebuild":
                actions=mutate_apl(None,player(reference)["rotation"]["priorityList"],rng,cold=True)
            else:
                candidates=[i for i,options in enchant_choices.items()
                            if any(e != enchants[i] for e in options)]
                if candidates:
                    i=rng.choice(candidates)
                    enchants[i]=rng.choice([e for e in enchant_choices[i]
                                             if e != enchants[i]])
    else:
        ids=[pick_gear(pools[j],rng) for j in range(16)]
        enchants=([rng.choice(enchant_choices[i]) for i in range(16)]
                  if enchant_pools is not None else
                  [e if rng.random()<0.86 else None for e in allowed_enchants])
        ranks=random_build(rng,native_authoritative=True)
        actions=mutate_apl(None,player(reference)["rotation"]["priorityList"],rng,cold=True)
    # Preserve the proposed equipment vector unchanged. MythicSim decides duplicate
    # item IDs and unique-equipped categories; Forever does not rewrite the build.
    p=player(q)
    for i,item in enumerate(p["equipment"]["items"]):
        item.clear()
        item["id"]=ids[i]
        if enchants[i] is not None:
            item["enchant"]=enchants[i]
    p["talentsString"]=encode(ranks)
    p["rotation"]["priorityList"]=actions
    # Forward generated talents unchanged. Only selected MythicSim Rust
    # prepare/sim --gate decides whether this combination is executable.
    return q

def candidate_key(q):
    p=player(q)
    return sha({"equipment":p["equipment"],"talentsString":p["talentsString"],"rotation":p["rotation"]})

def main():
    ap=argparse.ArgumentParser()
    for x in ("binary","reference","catalogue","outdir"):
        ap.add_argument("--"+x,type=Path,required=True)
    ap.add_argument("--seconds",type=float,default=300)
    ap.add_argument("--screen-iterations",type=int,default=60)
    ap.add_argument("--holdout-iterations",type=int,default=4000)
    ap.add_argument("--seed",type=int,default=670)
    ap.add_argument("--engine-items",type=Path,required=True)
    ap.add_argument("--engine-enchants",type=Path,required=True)
    ap.add_argument("--accepted-prior-dps",type=float,default=None)
    ap.add_argument("--accepted-prior-provenance",type=str,default=None)
    ap.add_argument("--pool-per-slot",type=int,default=80)
    args=ap.parse_args()
    # The 300s gate budget includes inputs, item pool construction, search,
    # reranking and frozen holdout — not just paid candidate evaluations.
    started=time.monotonic()
    deadline=started+args.seconds
    if not (0 < args.seconds <= 300) or args.screen_iterations<1 or args.holdout_iterations<1000 or args.pool_per_slot<1:
        ap.error("Need finite 0 < seconds <= 300, positive iterations/pool and >=1000 independent stochastic holdout fights")
    args.outdir.mkdir(parents=True,exist_ok=True)
    ref=json.loads(args.reference.read_text())
    if (args.accepted_prior_dps is None) != (args.accepted_prior_provenance is None):
        ap.error("Accepted prior DPS and its independent provenance must be supplied together")
    if args.accepted_prior_dps is not None:
        if not (0 < args.accepted_prior_dps < float("inf")):
            ap.error("Prior mean DPS must be positive and finite")
        if not args.accepted_prior_provenance.strip():
            ap.error("Accepted prior provenance must be nonblank")
        # This CLI can record a purported prior and compute a provisional
        # numeric floor, but it cannot self-certify source/legal compatiblity.
        # External reviewer/gate provider must verify acceptance and parity.
    validator=GearValidator(args.catalogue,args.engine_items,args.engine_enchants,ref)
    pools,excluded=candidate_pool(validator,args.pool_per_slot)
    item_names={iid:str(row["name"]).strip().casefold() for iid,row in validator.rows.items()}
    legal_rejections=[]
    rng=random.Random(args.seed)
    # Search uses nearly the full budget; reserve native rerank and frozen holdout.
    screen_end=deadline-min(32.,max(8.,args.seconds*0.10))
    original_key=candidate_key(ref)
    # Reference and accepted previous winners must NOT be warm-started.
    # Independent cold rediscovery of an identical candidate is legitimate.
    seen=set();paid=[];errors=[];elites=[];rerank_records=[]
    source_seed=int(ref["simOptions"]["randomSeed"])
    balanced_peak=float("-inf")
    balanced_probes=0
    rejected_unknown=set()
    while time.monotonic()<screen_end-0.1:
        elite=(rng.choice(elites[:min(8,len(elites))])[1]
               if elites and rng.random()<0.94 else None)
        try:
            q=make_candidate(ref,pools,rng,elite,item_names=item_names)
            candidate_items=player(q)["equipment"]["items"]
            ids=[int(item["id"]) for item in candidate_items]
            validator.validate(ids,[item.get("enchant",0) for item in candidate_items])
        except RejectedGear as exc:
            legal_rejections.append({"category":exc.category,"slot":exc.slot,
                                     "item_id":exc.item_id,"error":str(exc)[:400]})
            continue
        except (ValueError,AssertionError) as exc:
            legal_rejections.append({"category":"candidate_construction","error":str(exc)[:400]})
            continue
        key=candidate_key(q)
        if key in seen:continue
        seen.add(key)
        try:
            value,_,duration,_=run(args.binary,q,args.screen_iterations,source_seed,"balanced",screen_end)
            balanced_peak=max(balanced_peak,value)
            # Persist reconstructible paid candidates; a hash/DPS alone
            # cannot support independent replay or acceptance review.
            candidate_player=player(q)
            record={"balanced_dps":value,"key":key,"elapsed_s":duration,
                    "equipment":copy.deepcopy(candidate_player["equipment"]),
                    "talentsString":candidate_player["talentsString"],
                    "priorityList":copy.deepcopy(candidate_player["rotation"]["priorityList"]),
                    "screen_iterations":args.screen_iterations,"screen_seed":source_seed}
            # Balanced is a cheap ranking hint, not an unbiased expected DPS.
            # Additional balanced native probes govern the elite pool; stochastic is holdout-only.
            promising=(len(elites)<10 or value>=balanced_peak-38.
                       or rng.random()<0.04)
            if promising and time.monotonic()<screen_end-0.5:
                probe,_,probe_duration,_=run(args.binary,q,160,source_seed+554433,
                                             "balanced",screen_end)
                record["balanced_probe_dps"]=probe
                record["balanced_probe_s"]=probe_duration
                balanced_probes+=1
                elites.append((probe,q))
                elites.sort(key=lambda x:-x[0])
                elites=elites[:28]
            paid.append(record)
        except (TimeoutError,subprocess.TimeoutExpired):break
        except Exception as exc:
            message=str(exc)
            m=re.search(r"no item with id (\d+)|item (\d+) has an effect not prepared",message)
            if m:
                bad=int(m.group(1) or m.group(2))
                rejected_unknown.add(bad)
                for idx,items in pools.items():
                    pools[idx]=[v for v in items if v!=bad]
                if any(not items for items in pools.values()):
                    raise RuntimeError("No recognized items remain in a legal slot") from exc
            errors.append({"key":key,"error":message[:900]})
    
    if not paid:raise RuntimeError("No source-legal native joint candidate completed")
    rerank_end=deadline-min(8.,max(2.,args.seconds*0.02))
    reranked=[]
    for score,q in elites[:25]:
        if time.monotonic()>rerank_end-0.1:break
        try:
            value,_,duration,_=run(args.binary,q,2000,source_seed+555123,"balanced",rerank_end)
            reranked.append((value,q))
            rerank_records.append({"candidate_key":candidate_key(q),
                                   "balanced_rerank_dps":value,
                                   "iterations":2000,"seed":source_seed+555123})
        except (TimeoutError,subprocess.TimeoutExpired):break
        except Exception as exc:errors.append({"key":candidate_key(q),"error":str(exc)[:800]})
    if not reranked:raise RuntimeError("No balanced finalists evaluated")
    score,winner=max(reranked,key=lambda x:x[0])
    # A reference-identical winner is legal IF independently rediscovered.
    winner_items=player(winner)["equipment"]["items"]
    winner_ids=[int(item["id"]) for item in winner_items]
    winner_audit=validator.audit(winner_ids,[item.get("enchant",0) for item in winner_items])
    (args.outdir/"frozen_winner_request.json").write_text(json.dumps(winner,indent=2))
    (args.outdir/"winner_identity_audit.json").write_text(json.dumps(winner_audit,indent=2))
    holdout,raw,_,_=run(args.binary,winner,args.holdout_iterations,args.seed+1300000007,"stochastic",deadline)
    elapsed=time.monotonic()-started
    floor= max(REFERENCE_DPS,0.99*args.accepted_prior_dps) if args.accepted_prior_dps is not None else None
    report={"status":"NATIVE_P75_DIAGNOSTIC_NOT_PROCESS_GATE_PASS","elapsed_s":elapsed,
       "paid_unique":len(paid),"failures":len(errors),"search_rng_mode":"balanced",
       "legality_rejections":len(legal_rejections),
       "catalogue_rejections_by_category":dict(excluded),
       "reference_sha256":sha(ref),
       "native_binary_sha256":sha256(args.binary),
       "catalogue_sha256":sha256(args.catalogue),
       "engine_items_sha256":sha256(args.engine_items),
       "engine_enchants_sha256":sha256(args.engine_enchants),
       "balanced_probes":balanced_probes,"engine_unavailable_items_rejected":sorted(rejected_unknown),
       "apl_search_grammar":"GENERIC_TYPED_SOURCE_REFERENCE_CORPUS",
       "apl_search_support":"Action creation, deletion, ordering, predicate substitution and RHS threshold mutation; only known spell IDs and condition ASTs; full spellbook/effect parity unverified",
       "winner_gear":[x["id"] for x in player(winner)["equipment"]["items"]],
       "winner_talents":player(winner)["talentsString"],
       "winner_apl_sha256":sha(player(winner)["rotation"]),
       "rerank_dps":score,"rerank_rng_mode":"balanced","holdout_mode":"stochastic","holdout_dps":holdout,"external_reference_dps":REFERENCE_DPS,
       "accepted_prior_dps":args.accepted_prior_dps,
       "accepted_prior_provenance":args.accepted_prior_provenance,
       "point_floor_provisional":floor,
       "external_floor_mean_pass":holdout>=REFERENCE_DPS,
       "prior_floor_mean_numeric_check_only":holdout>=floor if floor is not None else None,
       "comparator_status":"PRIOR_PROVENANCE_SUPPLIED_UNVERIFIED" if floor is not None else "BLOCKED_ACCEPTED_COMPATIBLE_PRIOR_UNVERIFIED",
       "holdout_iterations":args.holdout_iterations,
       "limitations":["No live gsim 2D↔Rust causal integration evidence",
         "Source catalogue unique-equipped families and weapon-hand restrictions require audit; same-name ring/trinket variants are conservatively rejected",
         "PROCESS v2.10 tests independently frozen holdout MEAN, not 95% CI lower bound; accepted-compatible prior must be verified",
         "Enchant catalogue is limited to captured source-slot IDs or no enchant; semantic item/enchant effect parity and unrecorded restrictions need audit"]}
    for name,data in (("report.json",report),("paid.json",paid),("errors.json",errors),
                      ("legality_rejections.json",legal_rejections),("holdout.json",raw),
                      ("reranked_finalists.json",rerank_records)):
        (args.outdir/name).write_text(json.dumps(data,indent=2))
    print(json.dumps(report,indent=2),flush=True)
    validator.close()
    if elapsed>args.seconds:raise TimeoutError("300s joint-search budget exceeded")
if __name__=="__main__":main()
