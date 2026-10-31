#!/usr/bin/env python3
"""WF677: Druid L60 unrestricted-spec *native* gear/talents/APL search.

An exploratory cross-spec DPS comparison on one fixed encounter, NOT a certified
P7.5 checkpoint or the gsim-2D↔Rust production integration. Cold search: neither
the saved Balance build nor previous P7.x winners initialize candidates.
"""
import argparse,copy,json,math,random,re,sqlite3,subprocess,time
from collections import Counter
from pathlib import Path
from p73_talent_search_v2 import run,sha,player,random_build as balance_random_build,edit_neighbors as balance_edit_neighbors
from talent_schema_druid import TREES,legal_add,parse,encode,validate
from p74_gear_validation import SLOTS,SOURCE_SLOTS,ARMOR,GearValidator,RejectedGear,sha256

FIXTURES={
 "balance":"fixtures/mage/prepared-v2/balance-druid-revelation.request.json",
 "cat":"fixtures/mage/prepared-v2/production-feral-druid.request.json",
 "bear":"fixtures/mage/prepared-v2/feral-bear-druid-absorption.request.json",
 "resto":"fixtures/healers/restoration-druid.request.json",
}
MODES={"balance":"balanceDruid","cat":"feralCatDruid",
       "bear":"feralBearDruid","resto":"restorationDruid"}
TREES_FOR={"balance":0,"cat":1,"bear":1,"resto":2}
FERAL_SAVED_REFERENCE_DPS=811.0237260012982

# Mechanic-based source talent search weights, NOT a saved-reference rank
# allocation. These are synergies with Feral Cat builder/finisher, crit,
# shifting and form-dependent actions. Full legal point distribution stays
# stochastic and all 51-point allocations remain discoverable.
CAT_UTILITY={
    "ferocity":5, "heart_of_the_wild":6, "shredding_attacks":10,
    "savage_fury":8, "sharpened_claws":9, "shifting_power":9,
    "mangle":4, "predatory_strikes":8, "blood_frenzy":8,
    "improved_shifting_power":8, "leader_of_the_pack":10,
    "predatory_instincts":7, "rend_and_tear":8, "berserk":12,
    "furor":6, "naturalist":5, "natural_shapeshifter":6,
    "genesis":4, "natures_majesty":5
}

def one_percent_floor(best_spec_mean):
    if not math.isfinite(best_spec_mean) or best_spec_mean<=0:
        raise ValueError("best fixed-spec mean must be finite and positive")
    return 0.99*best_spec_mean

def within_one_percent(free_mean,best_spec_mean):
    return math.isfinite(free_mean) and free_mean>=one_percent_floor(best_spec_mean)
def process_numeric_pass(free_mean,best_spec_mean=None):
    """Native P7.5 numeric comparison, not full live-2D certification.

    A standalone candidate's external-reference score alone is insufficient:
    the strongest independently accepted compatible fixed-spec stochastic
    mean is required. When unavailable, the numeric verdict is UNKNOWN,
    not a self-certified PASS (or an invented failing comparator).
    """
    if best_spec_mean is None:
        return None
    return (math.isfinite(free_mean) and
            free_mean>=FERAL_SAVED_REFERENCE_DPS and
            within_one_percent(free_mean,best_spec_mean))
def native_report_numeric_verdict(free_mean,best_spec_mean):
    """Native-only arithmetic comparison is NOT a PROCESS P7.5 PASS.

    --benchmark-source is caller-supplied text, not an independently verified
    accepted P7.1-P7.4 prior. The production 2D/native causal gate is also
    absent. Never promote a CLI numeric result to a formal gate verdict.
    """
    return {"process_numeric_pass":None,
            "native_numeric_diagnostic_pass":process_numeric_pass(free_mean,best_spec_mean)}

def choose(rng,weighted):
    total=sum(w for w,_ in weighted);x=rng.random()*total
    for weight,value in weighted:
        x-=weight
        if x<=0:return value
    return weighted[-1][1]
def random_talents(rng,spec):
    """Spend 51 points using actual talent tier/prerequisite rules; NO Balance floor."""
    if spec=="balance":
        # The Balance profile must legally unlock its Moonkin/Insect actions.
        # The same independent full-tree operator as the fixed-spec search
        # makes unrestricted-vs-Balance discovery a fair comparison.
        return balance_random_build(rng)
    ranks=[[0]*len(tree) for tree in TREES]
    primary=TREES_FOR[spec]
    for point in range(51):
        legal=[]
        for ti,tree in enumerate(TREES):
            for j,talent in enumerate(tree):
                if legal_add(ranks,ti,j):
                    current=sum(ranks[ti])
                    # Bias towards source archetype without freezing 31/41 or a signature talent.
                    weight=(10. if ti==primary and current<36 else
                            1.7 if ti==primary else 0.75)
                    if spec=="cat":
                        # Independent source-mechanics heuristic: retain a
                        # nonzero chance for every source-legal talent.
                        # No saved allocation or prior winning candidate is
                        # loaded into cold search.
                        weight*=CAT_UTILITY.get(talent.name,0.35)
                    weight*=0.5+1.5*rng.random()
                    legal.append((weight,(ti,j)))
        if not legal:raise RuntimeError("No source-legal talent allocation")
        ti,j=choose(rng,legal);ranks[ti][j]+=1
    if not validate(ranks,moonkin=False,insect=False):
        raise ValueError('Source-illegal random '+spec+' talent allocation: '+encode(ranks))
    return ranks
def mutate_talents(rng,ranks,spec):
    if spec=="balance":return balance_edit_neighbors(ranks,rng)
    # Include independent source-informed macro mutations, not only tiny
    # donor-to-recipient edits that cannot escape talent prerequisite basins.
    if spec=="cat" and rng.random()<0.17:
        return random_talents(rng,spec)
    for _ in range(65):
        out=[row[:] for row in ranks]
        donors=[(ti,j) for ti,row in enumerate(out) for j,v in enumerate(row) if v]
        ti,j=rng.choice(donors);out[ti][j]-=1
        choices=[(i,k) for i,tree in enumerate(TREES) for k,_ in enumerate(tree)
                 if legal_add(out,i,k)]
        if not choices:continue
        i,k=rng.choice(choices);out[i][k]+=1
        if out!=ranks and validate(out,moonkin=False,insect=False):return out
    return random_talents(rng,spec)
def catalogue_pools(path,validator):
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro",uri=True) as db:
        db.row_factory=sqlite3.Row
        names={int(i):str(n).strip().casefold() for i,n in db.execute("SELECT item_id,name FROM items")}
        choices={}
        for spec in MODES:
            role={}
            for slot_idx,slot in enumerate(SLOTS):
                source_slots=SOURCE_SLOTS.get(slot,(slot,))
                sql=("SELECT * FROM items WHERE item_id>0 AND slot IN ("+
                     ",".join("?" for _ in source_slots)+
                     ") AND (required_level IS NULL OR required_level<=60)")
                good=[]
                for row in db.execute(sql,source_slots):
                    r=dict(row)
                    # The source catalogue is not enough: reject missing Rust
                    # IDs, wrong slots, unique/level/class/phase/enchant conflicts.
                    try: validator.item(slot_idx,int(r["item_id"]))
                    except RejectedGear:continue
                    if spec in ("cat","bear"):
                        score=(r["attack_power"] or 0)*0.65+(r["agility"] or 0)*2.0+(r["strength"] or 0)*1.4+(r["hit"] or 0)*2.5+(r["crit"] or 0)*2.3
                        score+=(r["stamina"] or 0)*(.4 if spec=="cat" else 1.0)
                        score+=(r["weapon_dps"] or 0)*.7
                    else:
                        score=(r["spell_power"] or 0)+(r["intellect"] or 0)*.5+(r["hit"] or 0)*1.5+(r["crit"] or 0)*1.3+(r["spirit"] or 0)*.1
                    good.append((score,int(r["item_id"])))
                good.sort(reverse=True)
                ids=list(dict.fromkeys(id_ for _,id_ in good[:100]))
                # Search must not exclude individually legal items from the
                # saved reference merely due an arbitrary top-100 source
                # stat heuristic. This adds independent per-slot CHOICES,
                # never a complete saved reference loadout to the search.
                ref_item=int(validator.reference["raid"]["parties"][0]["players"][0]
                             ["equipment"]["items"][slot_idx]["id"])
                try:
                    validator.item(slot_idx,ref_item)
                    if ref_item not in ids:
                        ids.insert(min(12,len(ids)),ref_item)
                except RejectedGear:
                    pass
                if not ids:raise ValueError(f"No legal candidate for {spec} slot {slot_idx} {slot}")
                role[slot_idx]=ids
            choices[spec]=role
    return choices,names
def pick_gear(rng,items):
    if rng.random()<0.16:return rng.choice(items)
    return items[min(len(items)-1,int(rng.expovariate(0.14)))]
def distinct_pairs(ids,pool,names,rng):
    for i,j in ((10,11),(12,13)):
        if ids[i]==ids[j] or names.get(ids[i])==names.get(ids[j]):
            safe=[id_ for id_ in pool[j] if id_!=ids[i] and
                  (names.get(ids[i]) is None or names.get(ids[i])!=names.get(id_))]
            if not safe:raise ValueError("No distinct ring/trinket candidates")
            ids[j]=pick_gear(rng,safe)
def source_template(reference,spec,fixtures,balance_reference):
    """One immutable Feral reference WORLD; source-valid per-spec character actions.

    The historical standalone production-feral-druid fixture is not the saved
    811-DPS Feral reference, and must NEVER populate a Cat candidate.
    """
    q=copy.deepcopy(reference)
    p=player(q)
    f=(player(reference) if spec=="cat" else
       player(balance_reference) if spec=="balance" else
       player(fixtures[spec]))
    p.pop("balanceDruid",None)
    for k in MODES.values():p.pop(k,None)
    p[MODES[spec]]=copy.deepcopy(f[MODES[spec]])
    # Source APL defines legal spell/condition grammar; order is independently searched.
    p["rotation"]=copy.deepcopy(f["rotation"])
    # Preserve the saved reference player buffs and consumables for every spec.
    # Spec-specific actions still come from the corresponding source APL.
    if spec!="cat":
        p.pop("itemSwap",None)
        p.pop("enableItemSwap",None)
    # Preserve the SAVED encounter's player geometry exactly, including
    # absent fields. The old spec-specific front/range assignments silently
    # compared Bear at the front and Balance/Resto at 15yd against Cat at 0yd.
    # If a form cannot act at the pinned geometry, its native result must
    # expose that limitation; changing the encounter is not a valid shortcut.
    return q
def validate_candidate_gear(validator,reference,gear):
    """Check the ACTUAL candidate enchants, not stripped reference defaults.

    Some enchant metadata disagrees with the exact saved Feral request even
    though pinned Rust replays that original item+enchant pair. Such a known
    reference pair may use base-item validation, with an explicit audit entry.
    Never extend that exception to a DIFFERENT item carrying the same enchant.
    """
    original=player(reference)["equipment"]["items"]
    if len(gear)!=16 or len(original)!=16:
        raise RejectedGear("slot_count","Expected 16 source/candidate gear slots")
    ids=[int(item["id"]) for item in gear]
    actual=[int(item.get("enchant",0) or 0) for item in gear]
    checked=actual[:]
    exceptions=[]
    for idx,(item,source) in enumerate(zip(gear,original)):
        if not actual[idx] or ids[idx]!=int(source["id"]) or actual[idx]!=int(source.get("enchant",0) or 0):
            continue
        try:
            validator.item(idx,ids[idx],actual[idx])
        except RejectedGear as exc:
            if exc.category not in ("enchant_slot","engine_enchant_missing"):
                raise
            checked[idx]=0
            exceptions.append({"slot_index":idx,"item_id":ids[idx],
                               "enchant_id":actual[idx],"source_metadata_rejection":exc.category})
    validator.validate(ids,checked)
    return {"actual_enchants":actual,"validated_enchants":checked,
            "reference_pair_exceptions":exceptions}

def set_candidate_item(gear,slot,new_id):
    """An enchant belongs to its item; never carry it across an item swap."""
    new_id=int(new_id)
    if int(gear[slot]["id"])!=new_id:
        gear[slot].pop("enchant",None)
    gear[slot]["id"]=new_id

def source_valid_reference_enchant(validator,reference,slot,item_id,enchant_id):
    """Allow only source-valid enchants or the EXACT saved native-replayed pair."""
    if not enchant_id:
        return False
    try:
        validator.item(slot,int(item_id),int(enchant_id))
    except RejectedGear as exc:
        saved=player(reference)["equipment"]["items"][slot]
        return (int(item_id)==int(saved["id"]) and
                int(enchant_id)==int(saved.get("enchant",0) or 0) and
                exc.category in ("enchant_slot","engine_enchant_missing"))
    return True

def build(rng,spec,reference,fixtures,balance_reference,pools,names,parent=None,validator=None):
    q=source_template(reference,spec,fixtures,balance_reference)
    p=player(q)
    if parent is not None:
        old=player(parent)
        gear=copy.deepcopy(old["equipment"]["items"])
        ranks=parse(old["talentsString"])
        actions=copy.deepcopy(old["rotation"]["priorityList"])
        axis=choose(rng,[(50,"gear"),(28,"talents"),(18,"apl"),(4,"enchant")])
        if axis=="gear":
            for _ in range(1 if rng.random()<.85 else 2):
                j=rng.randrange(16)
                set_candidate_item(gear,j,pick_gear(rng,pools[spec][j]))
        elif axis=="talents":
            ranks=mutate_talents(rng,ranks,spec)
        elif axis=="apl" and len(actions)>1:
            # Cat requires the item-swap + shapeshift setup at the front of
            # the APL. Never destroy that ordered causal precondition.
            start=4 if spec=="cat" else 0
            if len(actions)-start>=2:
                i,j=rng.sample(range(start,len(actions)),2)
                actions[i],actions[j]=actions[j],actions[i]
        elif axis=="enchant":
            candidates=[i for i,x in enumerate(gear) if "enchant" in x]
            if candidates:gear[rng.choice(candidates)].pop("enchant",None)
    else:
        gear=[{"id":pick_gear(rng,pools[spec][j])} for j in range(16)]
        # Enchants are sourced per slot from saved player, not a copied gear setup.
        for j,item in enumerate(gear):
            option=player(reference)["equipment"]["items"][j].get("enchant")
            if (option is not None and rng.random()<.85 and
                    (validator is None or
                     source_valid_reference_enchant(validator,reference,j,item["id"],option))):
                item["enchant"]=option
        ranks=random_talents(rng,spec)
        actions=copy.deepcopy(p["rotation"]["priorityList"])
        if spec=="cat":
            prefix,tail=actions[:4],actions[4:]
            rng.shuffle(tail)
            actions=prefix+tail
        else:
            rng.shuffle(actions)
    ids=[int(x["id"]) for x in gear]
    distinct_pairs(ids,pools[spec],names,rng)
    for j in range(len(gear)):
        # Ring/trinket de-duplication can also change item identity.
        set_candidate_item(gear,j,ids[j])
    p["equipment"]={"items":gear}
    p["talentsString"]=encode(ranks)
    p["rotation"]["priorityList"]=actions
    if not validate(ranks,moonkin=(spec=="balance"),insect=(spec=="balance")):
        raise ValueError('Source-illegal '+spec+' candidate talents: '+encode(ranks))
    if validator is not None:validate_candidate_gear(validator,reference,gear)
    return q
def key(spec,req):
    p=player(req)
    return sha({"spec":spec,"gear":p["equipment"],"talents":p["talentsString"],"apl":p["rotation"]})

def require_finite_native_dps(value,stage):
    """Only a real finite native mean can count as a paid evaluation.

    Rust output may contain NaN/Infinity; Python json.dumps would otherwise
    write non-standard JSON, and paid-form coverage could count false scores.
    Zero DPS is valid for a legal support/control profile.
    """
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
        raise ValueError(f"INVALID_NATIVE_DPS:{stage}: expected finite nonnegative mean")
    return float(value)

def paid_candidate_record(spec,req,screen_dps,screen_mode,elapsed):
    """Persist the actual scored request, not just its unreplayable digest.

    The independent P7 audit must be able to inspect/replay every paid
    candidate's gear, enchants, talents, APL and encounter. Copying the
    request also protects the ledger against later in-memory mutations.
    """
    return {"spec":spec,"key":key(spec,req),
            "candidate_request":copy.deepcopy(req),
            "screen_dps":require_finite_native_dps(screen_dps,"screen"),"screen_mode":screen_mode,
            "elapsed_s":elapsed}

def paid_rerank_record(spec,req,rerank_dps,seed,iterations):
    """Record each paid finalist re-evaluation with its exact replay inputs.

    The screen ledger alone cannot establish which stochastic rerank score
    selected the winner; keep a separate immutable request and RNG record.
    """
    return {"spec":spec,"key":key(spec,req),
            "candidate_request":copy.deepcopy(req),
            "rerank_dps":require_finite_native_dps(rerank_dps,"rerank"),"rng_mode":"stochastic",
            "seed":seed,"iterations":iterations}

def require_paid_spec_coverage(requested_specs,paid):
    """Fail closed if any advertised form had no successful native screen.

    A spec appearing in --specs or attempts_per_spec is not evidence that a
    legal candidate was actually evaluated by pinned Rust. Count the paid
    ledger only; duplicates and native failures cannot establish coverage.
    """
    expected=set(requested_specs)
    counts=Counter(record["spec"] for record in paid)
    missing=sorted(spec for spec in expected if counts[spec]<1)
    unexpected=sorted(set(counts)-expected)
    if missing or unexpected:
        raise RuntimeError("BLOCKED: native paid spec coverage incomplete; "+
                           "missing="+",".join(missing)+
                           "; unexpected="+",".join(unexpected))
    return {spec:counts[spec] for spec in sorted(expected)}

def write_search_evidence_stage(outdir,stage,paid_count,rerank_count):
    """Never confuse preserved paid search data with a completed holdout."""
    (outdir/"search_evidence_stage.json").write_text(json.dumps({
        "stage":stage,"paid_screen_records":paid_count,
        "paid_rerank_records":rerank_count,
    },indent=2)+"\n")

def persist_paid_search_evidence(outdir,paid,rerank_paid,errors,legality_rejections,stage):
    """Save all paid requests BEFORE holdout, which may fail or time out.

    Without this checkpoint a late stochastic holdout failure discarded the
    entire paid candidate/rerank ledger. This is evidence preservation, not
    a numeric or PROCESS gate PASS.
    """
    for name,data in (("paid.json",paid),("rerank.json",rerank_paid),
                      ("failures.json",errors),
                      ("legality_rejections.json",legality_rejections)):
        (outdir/name).write_text(json.dumps(data,indent=2)+"\n")
    write_search_evidence_stage(outdir,stage,len(paid),len(rerank_paid))

def main():
    ap=argparse.ArgumentParser()
    for n in ("binary","reference","balance-reference","catalogue","fixtures","outdir"):
        ap.add_argument("--"+n,type=Path,required=True)
    ap.add_argument("--seconds",type=float,default=300.)
    ap.add_argument("--screen-iterations",type=int,default=60)
    ap.add_argument("--holdout-iterations",type=int,default=4000)
    ap.add_argument("--seed",type=int,default=684)
    ap.add_argument("--specs",nargs="+",choices=list(MODES),default=list(MODES),
                    help="Cold search can be run with all specs or cat only for independent comparator")
    ap.add_argument("--engine-items",type=Path,required=True)
    ap.add_argument("--engine-enchants",type=Path,required=True)
    ap.add_argument("--benchmark-dps",type=float,default=None,
                    help="Accepted comparable fixed-spec mean; omit for independent parallel discovery")
    ap.add_argument("--benchmark-source",type=str,default=None,
                    help="Provenance of accepted comparator; omit when independent job computes it")
    a=ap.parse_args()
    # PROCESS <=300s is end-to-end: start before reading reference files,
    # opening the Rust/source validator, or constructing item candidate pools.
    t0=time.monotonic();deadline=t0+a.seconds
    if not (math.isfinite(a.seconds) and 15<a.seconds<=300):
        ap.error("--seconds must be finite and within (15, 300] for a cold P7.5 search")
    if a.holdout_iterations<1000:
        ap.error("Need >=1000 independent stochastic holdout fights")
    a.outdir.mkdir(parents=True,exist_ok=True)
    reference=json.loads(a.reference.read_text())
    if "feralCatDruid" not in player(reference):
        raise ValueError('UNRESTRICTED_MUST_USE_SAVED_FERAL_REFERENCE')
    if len(player(reference)["rotation"]["priorityList"])!=18:
        raise ValueError('Wrong saved Feral APL length')
    balance_reference=json.loads(a.balance_reference.read_text())
    if "balanceDruid" not in player(balance_reference):
        raise ValueError('Wrong saved Balance reference spec')
    fixtures={spec:json.loads((a.fixtures/path).read_text()) for spec,path in FIXTURES.items()}
    if (a.benchmark_dps is None)!=(a.benchmark_source is None):
        ap.error("--benchmark-dps and --benchmark-source must be provided together")
    if a.benchmark_dps is not None and (not math.isfinite(a.benchmark_dps) or a.benchmark_dps<=0):
        ap.error("--benchmark-dps must be positive finite")
    # Source-saved Feral request legitimately uses enchant IDs that the
    # catalogue's typed enchant metadata rejects on the same slots, despite
    # the pinned Rust binary accepting the COMPLETE saved reference. Validate
    # item base identity/level/slot/class/unique-category without relying on
    # the source/enchant classification, then independently let real Rust
    # reject unsupported enchant+item combinations on paid candidates.
    item_validation_reference=copy.deepcopy(reference)
    for slot in player(item_validation_reference)["equipment"]["items"]:
        slot.pop("enchant",None)
    validator=GearValidator(a.catalogue,a.engine_items,a.engine_enchants,item_validation_reference)
    pools,names=catalogue_pools(a.catalogue,validator)
    benchmark_floor=one_percent_floor(a.benchmark_dps) if a.benchmark_dps is not None else None
    rng=random.Random(a.seed)
    end_screen=deadline-min(35.,max(10.,a.seconds*.12))
    seed=int(reference["simOptions"]["randomSeed"])
    seen={};elites={s:[] for s in MODES};paid=[];errors=[];counts=Counter()
    allbest=[];probes=0;legality_rejections=[];balanced_crit_fallbacks=0
    while time.monotonic()<end_screen-.1:
        # Equal exploration by spec, with exploitation only after native paid evaluation.
        spec=rng.choice(a.specs)
        if allbest and rng.random()<.65:
            spec=rng.choice(allbest[:min(12,len(allbest))])[1]
        parent=(rng.choice(elites[spec][:min(9,len(elites[spec]))])[1]
                if elites[spec] and rng.random()<.90 else None)
        try:q=build(rng,spec,reference,fixtures,balance_reference,pools,names,parent,validator=validator)
        except RejectedGear as exc:
            legality_rejections.append({"spec":spec,"category":exc.category,
                                        "item_id":exc.item_id,"error":str(exc)[:450]})
            continue
        except (ValueError,AssertionError,RuntimeError) as exc:
            errors.append({"spec":spec,"stage":"build","error":str(exc)[:450]});continue
        h=key(spec,q)
        if h in seen:continue
        seen[h]=1;counts[spec]+=1
        try:
            screen_mode="balanced"
            try:
                dps,_,elapsed,_=run(a.binary,q,a.screen_iterations,seed,"balanced",end_screen)
            except RuntimeError as exc:
                if "balanced RNG: probability must be finite and in [0,1]" not in str(exc):
                    raise
                # A source-legal Feral crit chance can reach/exceed 1.0.
                # The balanced surrogate panics although native stochastic
                # Rust handles the same request. Never silently discard the
                # candidate because the *search accelerator* is less robust.
                screen_mode="stochastic_fallback"
                dps,_,elapsed,_=run(a.binary,q,a.screen_iterations,seed,"stochastic",end_screen)
                balanced_crit_fallbacks+=1
            record=paid_candidate_record(spec,q,dps,screen_mode,elapsed)
            # The screen was a real paid native evaluation. Persist it BEFORE
            # the optional stochastic probe, which can fail or time out.
            # A probe failure must never erase the successful screen result.
            paid.append(record)
            current=elites[spec][0][0] if elites[spec] else -math.inf
            if (len(elites[spec])<8 or dps>=current-45 or rng.random()<.05) and time.monotonic()<end_screen-.3:
                measured,_,_,_=run(a.binary,q,140,seed+554433,"stochastic",end_screen)
                record["stochastic_probe_dps"]=require_finite_native_dps(measured,"probe");probes+=1
                elites[spec].append((measured,q))
                elites[spec].sort(key=lambda x:-x[0]);elites[spec]=elites[spec][:20]
                allbest=[(x[0],s,x[1]) for s,rows in elites.items() for x in rows]
                allbest.sort(key=lambda x:-x[0])
        except (subprocess.TimeoutExpired,TimeoutError):break
        except Exception as exc:
            message=str(exc);errors.append({"spec":spec,"key":h,"stage":"native",
                                             "candidate_request":copy.deepcopy(q),
                                             "error":message[:850]})
            ids=re.findall(r"no item with id (\d+)|item (\d+) has an effect not prepared",message)
            for x,y in ids:
                missing=int(x or y)
                for role in pools.values():
                    for slot in role:
                        role[slot]=[v for v in role[slot] if v!=missing]
                        if not role[slot]:raise RuntimeError(f"All items for slot {slot} rejected")
    reranked=[];rerank_paid=[]
    end_rerank=deadline-min(8.,max(2.,a.seconds*.03))
    for measured,spec,q in allbest[:30]:
        if time.monotonic()>=end_rerank-.15:break
        try:
            exact,_,_,_=run(a.binary,q,1800,seed+100005,"stochastic",end_rerank)
            rerank_record=paid_rerank_record(spec,q,exact,seed+100005,1800)
            reranked.append((exact,spec,q))
            rerank_paid.append(rerank_record)
        except (subprocess.TimeoutExpired,TimeoutError):break
        except Exception as exc:
            errors.append({"spec":spec,"stage":"rerank",
                           "candidate_request":copy.deepcopy(q),"error":str(exc)[:850]})
    # Persist paid screen and finalist rerank ledgers before winner audit
    # and stochastic holdout. Both can fail; paid work must remain auditable.
    persist_paid_search_evidence(a.outdir,paid,rerank_paid,errors,
                                 legality_rejections,"HOLDOUT_NOT_VERIFIED")
    # Search flags and attempted candidates cannot establish that each
    # advertised spec/form was really paid and scored by pinned native Rust.
    # Preserve raw evidence first, then block the diagnostic if any are absent.
    paid_per_spec=require_paid_spec_coverage(a.specs,paid)
    if not reranked:raise RuntimeError("No native stochastic finalists; inspect errors")
    best_score,winner_spec,winner=max(reranked,key=lambda t:t[0])
    p=player(winner)
    winner_gear_ids=[x["id"] for x in p["equipment"]["items"]]
    winner_enchant_evidence=validate_candidate_gear(validator,reference,p["equipment"]["items"])
    winner_audit=validator.audit(winner_gear_ids,winner_enchant_evidence["validated_enchants"])
    winner_audit.update(winner_enchant_evidence)
    (a.outdir/"winner_identity_audit.json").write_text(json.dumps(winner_audit,indent=2))
    (a.outdir/"winner.json").write_text(json.dumps(winner,indent=2))
    holdout,output,_,_=run(a.binary,winner,a.holdout_iterations,a.seed+1300000007,"stochastic",deadline)
    holdout=require_finite_native_dps(holdout,"holdout")
    report={"status":"UNRESTRICTED_DRUID_NATIVE_99PCT_DIAGNOSTIC",
      "elapsed_s":time.monotonic()-t0,"paid":len(paid),"attempts_per_spec":dict(counts),
      "paid_per_spec":paid_per_spec,
      "paid_evidence_schema":"replayable_native_candidate_requests_v1",
      "search_rng_seed":a.seed,"screen_rng_seed":seed,
      "stochastic_probe_seed":seed+554433,"rerank_seed":seed+100005,
      "holdout_seed":a.seed+1300000007,"holdout_mode":"stochastic",
      "screen_iterations":a.screen_iterations,
      "stochastic_probe_iterations":140,"rerank_iterations":1800,
      "failures":len(errors),"legal_rejections":len(legality_rejections),
      "stochastic_probes":probes,"reranked":len(reranked),
      "rerank_paid_records":len(rerank_paid),
      "rerank_evidence_schema":"replayable_native_stochastic_reranks_v1",
      "balanced_crit_stochastic_fallbacks":balanced_crit_fallbacks,
      "winner_spec":winner_spec,"winner_dps":holdout,"winner_gear":[x["id"] for x in p["equipment"]["items"]],
      "winner_talents":p["talentsString"],"winner_apl_sha256":sha(p["rotation"]),
       "winner_actual_enchants":winner_enchant_evidence["actual_enchants"],
       "winner_reference_pair_enchant_exceptions":winner_enchant_evidence["reference_pair_exceptions"],
      "source_fixture_paths":FIXTURES,"source_fixture_sha256":{spec:sha(req) for spec,req in fixtures.items()},
      "engine_binary_sha256":sha256(a.binary),"balance_reference_sha256":sha(balance_reference),
      "reference_encounter_sha256":sha(reference["encounter"]),
      "holdout_iterations":a.holdout_iterations,
      "benchmark_dps":a.benchmark_dps,"benchmark_source":a.benchmark_source,
      "searched_specs":a.specs,
      "feral_saved_reference_dps":FERAL_SAVED_REFERENCE_DPS,
      "external_reference_mean_pass":holdout>=FERAL_SAVED_REFERENCE_DPS,
      **native_report_numeric_verdict(holdout,a.benchmark_dps),
      "native_numeric_evidence_scope":"UNVERIFIED_NO_ACCEPTED_COMPARATOR" if benchmark_floor is None else "PROVISIONAL_COMPARATOR_REQUIRES_INDEPENDENT_ACCEPTANCE_AUDIT",
      "feral_saved_reference_sha256":sha(reference),
      "feral_saved_reference_request_source":"https://api.mythicsim.com/api/forever/ranking-sims/f2176db2-8217-47d2-8d3c-c9260d8ccb73/report",
      "benchmark_floor_99pct":benchmark_floor,
      "within_1pct_of_fixed_spec":within_one_percent(holdout,a.benchmark_dps) if benchmark_floor is not None else None,
      "gap_dps":holdout-benchmark_floor if benchmark_floor is not None else None,
      "catalogue_sha256":sha256(a.catalogue),
      "pinned_rust_items_sha256":sha256(a.engine_items),
      "pinned_rust_enchants_sha256":sha256(a.engine_enchants),
      "enchant_validation_policy":"Validate each actual candidate enchant against source/Rust slot metadata; only exact saved Feral item+enchant pairs with conflicting metadata use explicitly logged native-replayed reference exceptions. Item-swap enchant semantics remain separately unaudited.",
      "limitations":["No separately accepted unrestricted-spec DPS reference; benchmark source is diagnostic until accepted",
      "Native only, no live gsim 2D↔Rust controller trace",
      "Cat actions and consumables come from the saved Feral reference; balance actions from saved Balance reference; other specs from engine fixtures",
      "Pinned Rust/source known legality is verified for winner; unrecorded phase/faction and item-effect semantics still require audit",
      "Frozen stochastic arithmetic mean is judged against 99% benchmark; no confidence-limit gate",
      "Benchmark may be diagnostic until independently accepted and compatible",
      "Not a full live 2D/native P7.5 gate"]}
    for name,data in (("report.json",report),("holdout.json",output)):
        (a.outdir/name).write_text(json.dumps(data,indent=2))
    write_search_evidence_stage(a.outdir,"HOLDOUT_COMPLETE",len(paid),len(rerank_paid))
    print(json.dumps(report,indent=2),flush=True)
    validator.close()
    if time.monotonic()-t0>a.seconds:raise TimeoutError("Exceeded cold-search wall-clock limit")
    if not report["external_reference_mean_pass"]:
        raise SystemExit("FAIL: unrestricted Druid did not reach the saved Feral external reference DPS")
    if report["within_1pct_of_fixed_spec"] is False:
        raise SystemExit("FAIL: unrestricted Druid did not reach 99% of the accepted-compatible fixed-spec benchmark")
    if benchmark_floor is None:
        print("UNVERIFIED: no independently accepted compatible fixed-spec mean supplied; standalone native search is diagnostic only",flush=True)
if __name__=="__main__":main()
