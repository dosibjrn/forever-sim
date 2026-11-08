#!/usr/bin/env python3
"""Native 8-world-mob probe + real-100-label training of a tiny L30 surrogate.

The predictor never implements a spell, a stat formula, a pet, regeneration
or a battle. Only Rust carries the actor through actual world-mob deaths.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import re
import subprocess
import sys
from pathlib import Path

from wf_warlock_native_optimizer import (
    actor, apl_proposals, call, native_level_equipment, native_pet_autocast_receipt,
    proposals_from_native_talents,
    native_sustain_receipt, profile, set_native_pet, set_native_sustain_buffs,
)
from wf_warlock_l30_direct_affliction_comparison import (
    USER_AFFLICTION, OLD_DESTRO_COMPARATOR, exact_source_ranks, make_apl,
)
from wf_warlock_chain_surrogate import (
    extract_three_mob_features, extract_eight_mob_features, predict,
    select_native_100_validation,
    train_supervised,
)
from live_two_world_pulls import run as native_world_chain
from wf_warlock_surrogate_rank_validation import report_rank_validation
from wf_warlock_eight_mob_joint_search import (
    adaptive_native_search, sorted_observed_native,
)


def diverse_source_candidates(novel, apl_rows, count, seed):
    """Generate a reproducible, disjoint set of source-proposed candidates.

    Pet and gear strata are balanced. Talents/APLs are shuffled independently;
    their native mechanics and legalities are still decided only by Rust.
    """
    if not novel or not apl_rows:
        raise ValueError("No native source candidates")
    rng = random.Random(seed)
    strata = [(p, g) for p in ("Succubus", "Felhunter", "Imp", "Voidwalker")
              for g in ("native_dps", "native_max_hp")]
    rng.shuffle(strata)
    visited = set()
    # The only specified dimensions are source-supported choices; no recipes.
    for k in range(count):
        pet, gear = strata[k % len(strata)]
        for attempt in range(1000):
            talent = rng.choice(novel)
            apl_name, apl = rng.choice(apl_rows)
            signature = (pet, gear, talent["talents"], apl_name)
            if signature not in visited:
                visited.add(signature)
                yield gear, talent, pet, apl_name, apl
                break
        else:
            raise RuntimeError("Source candidate combinations exhausted")



def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--engine-tools", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--engine-sha", required=True)
    parser.add_argument("--full-count", type=int, default=4)
    parser.add_argument("--extra-candidates", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20261108)
    parser.add_argument("--search-iterations", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.full_count <= 128:
        parser.error("full-count must be 0..128")
    if not 0 <= args.extra_candidates <= 2000:
        parser.error("extra-candidates must be 0..2000")
    if not 0 <= args.search_iterations <= 20000:
        parser.error("search-iterations must be 0..20000")
    args.out.mkdir(parents=True,exist_ok=True)
    binary=args.binary.resolve()
    source=json.loads(args.source.read_text())
    source["encounter"]["targets"][0]["level"]=30
    actor(source)["name"]="Warlock L30 Troll eight-mob free optimizer"
    actor(source)["equipment"]["items"]=[{"id":0} for _ in range(17)]
    set_native_sustain_buffs(source)
    sys.path.insert(0,str(args.engine_tools.resolve()))
    import warlock_l20_native_search as search

    options=json.loads(call(
        [binary,"options","--class","warlock","--level","30"],seconds=60))
    if options["talents"]["points_available"]!=21:
        raise RuntimeError("Expected native L30 talent budget 21")
    exact_user={
        "improvedCorruption":5,"suppression":4,"grimReach":1,
        "improvedBaneOfAgony":2,"pandemic":3,"malevolence":3,
        "nightfall":2,"siphonLife":1,
    }
    if exact_source_ranks(options,USER_AFFLICTION)!=exact_user:
        raise RuntimeError("User's Affliction talents differ from native source")

    spells=search.native_spell_candidates(options,source)
    fragments=("corruption","agony","siphon life","shadow bolt",
               "drain life","life tap")
    ids={}
    for fragment in fragments:
        match=next((row["spell_id"] for row in spells
                    if fragment in row["name"].casefold()),None)
        if match is None:
            raise RuntimeError("Native spell absent: "+fragment)
        ids[fragment]=match

    actor(source)["talentsString"]=OLD_DESTRO_COMPARATOR
    actor(source)["rotation"]["priorityList"]=search.multi_apl([
        (ids["corruption"],"dot_missing"),(ids["agony"],"dot_missing"),
        (ids["shadow bolt"],None),
    ])
    dps_gear,gear_audit,hp_gear=native_level_equipment(
        binary,source,options,args.out,level=30)
    scenario_id="L30-world-proxy-2D-balanced-native-12s-gap-v1"
    cases=[]
    def probe_candidate(gear_name,base,build_name,build,pet,apl,filler,
                        *, request_override=None):
        """Pay eight Rust kills and extract both three/eight views of same trace."""
        index=len(cases)
        folder=args.out/("candidate_%02d" % index)
        folder.mkdir(exist_ok=True)
        if request_override is None:
            request=copy.deepcopy(base)
            actor(request)["talentsString"]=build
            set_native_pet(request,pet)
            actor(request)["rotation"]["priorityList"]=copy.deepcopy(apl)
        else:
            request=copy.deepcopy(request_override)
        request=profile(request,level=30)
        source_path=folder/"source_request.json"
        prepared_path=folder/"prepared.json"
        source_path.write_text(json.dumps(request,indent=2)+"\n")
        item={
            "candidate":index,"gear":gear_name,"talents":build,
            "build":build_name,"pet":pet,"filler":filler,
            "status":"PROBE_UNTESTED","confirmed_kills":0,
        }
        probe=None
        probe3=None
        try:
            call([binary,"prepare","--request",source_path,
                  "--actor-level","30","--outfile",prepared_path])
            prepared=json.loads(prepared_path.read_text())
            item["pet_autocasts"]=native_pet_autocast_receipt(prepared,pet)
            item["sustain"]=native_sustain_receipt(prepared,request)
            eight=native_world_chain(
                binary,prepared_path,classic_mob_level=30,
                target_count=8,rng_mode="balanced")
            (folder/"eight_native_world.json").write_text(
                json.dumps(eight,indent=2,allow_nan=False)+"\n")
            probe=extract_eight_mob_features(prepared,eight)
            # Derive the legacy 3-mob control from the exact same native
            # eight-kill trace, not an independent RNG execution.
            three=copy.deepcopy(eight)
            three["native_windows"]=three["native_windows"][:3]
            three["world_targets_killed"]=3
            three["world_elapsed_seconds"]=(
                three["native_windows"][-1]["native_kill_ns"] / 1e9)
            probe3=extract_three_mob_features(prepared,three)
            (folder/"three_native_world.json").write_text(
                json.dumps(three,indent=2,allow_nan=False)+"\n")
            (folder/"three_features.json").write_text(
                json.dumps(probe3,indent=2,allow_nan=False)+"\n")
            (folder/"eight_features.json").write_text(
                json.dumps(probe,indent=2,allow_nan=False)+"\n")
            item.update(status="PROBE_COMPLETED",
                        three_elapsed_s=three["world_elapsed_seconds"],
                        eight_elapsed_s=eight["world_elapsed_seconds"],
                        probe_targets=8,
                        features=probe["features"],
                        cooldowns=probe["cooldowns"])
        except (RuntimeError,ValueError,KeyError,AssertionError,OSError,
                subprocess.TimeoutExpired) as exc:
            item.update(status="PROBE_FAILED",error=str(exc)[-1800:])
        cases.append({"result":item,"probe":probe,"probe3":probe3,
                      "prepared":prepared_path,"folder":folder})
        (folder/"result.json").write_text(json.dumps(item,indent=2)+"\n")
        print("RUST_EIGHT_MOB_FEATURES",json.dumps(item),flush=True)
        return cases[-1]

    # Stable first 16 anchor IDs support exact native three-kill parity
    # with real 100-mob labels from the previous verified workflow.
    for gear_name,base in (("native_dps",dps_gear),("native_max_hp",hp_gear)):
        for build_name,build in (
                ("user_affliction",USER_AFFLICTION),
                ("prior_destro",OLD_DESTRO_COMPARATOR)):
            for pet in ("Succubus","Felhunter"):
                for filler in ("drain life","shadow bolt"):
                    apl=make_apl(
                        search,ids,affliction=build_name=="user_affliction",filler=filler)
                    probe_candidate(gear_name,base,build_name,build,pet,apl,filler)

    # Expand beyond the two known user/reference builds: propose talents
    # and APL entirely from Rust get_options and pay every evaluated candidate
    # with the *same* three-world-mob retained native actor. No 30s combat
    # score is ever used to discard an APL, talent or pet configuration.
    proposals=list(proposals_from_native_talents(options,OLD_DESTRO_COMPARATOR,args.seed))
    novel=[x for x in proposals
           if x["talents"] not in (USER_AFFLICTION,OLD_DESTRO_COMPARATOR)
           and sum(int(ch) for ch in x["talents"] if ch.isdigit())==21]
    apl_rows,_=apl_proposals(options,source,search)
    if not novel or not apl_rows:
        raise RuntimeError("Rust did not offer extra native talent/APL proposals")
    for gear_name, proposed, pet, apl_name, apl in diverse_source_candidates(
            novel, apl_rows, args.extra_candidates, args.seed):
        base = dps_gear if gear_name == "native_dps" else hp_gear
        probe_candidate(
            gear_name, base, proposed["label"], proposed["talents"],
            pet, apl, apl_name)
    probes=[case for case in cases if case["probe"] is not None]
    sessions=[]
    # Reuse exact, completed 100-mob native truth from the earlier L30 run
    # ONLY where each first-three-kill Rust clock, HP and mana tuple matches
    # the new telemetry-enabled Rust actor. No arithmetic extrapolation.
    historical_file=Path(__file__).resolve().parents[1]/"data"/(
        "warlock-l30-real-100mob-truth-with-first3-parity.json")
    historical=json.loads(historical_file.read_text())
    if (historical["source_three_engine_sha"]!=args.engine_sha
            or historical["scenario_id"]!=scenario_id):
        raise RuntimeError("Historical 100-mob truth has another Rust engine/scenario")
    reused_ids=[]
    for old_id,old_elapsed,old_windows in historical["rows"]:
        case=next((x for x in probes if x["result"]["candidate"]==old_id),None)
        if case is None:
            raise RuntimeError("Previously 100-mob-completed candidate lacks live 3-mob probe")
        observed=json.loads((case["folder"]/"three_native_world.json").read_text())
        windows=observed["native_windows"]
        match=(len(windows)==len(old_windows)==3 and all(
            int(actual["native_kill_ns"])==int(old[0])
            and abs(float(actual["actor_health"])-float(old[1])) < 1e-4
            and abs(float(actual["actor_mana"])-float(old[2])) < 1e-4
            for actual,old in zip(windows,old_windows)))
        if not match:
            raise RuntimeError("Rust three-kill telemetry parity failed for "+str(old_id))
        sessions.append({
            "candidate":old_id,"engine_sha":args.engine_sha,"scenario_id":scenario_id,
            "source_100_engine_sha":historical["source_100_engine_sha"],
            "first_three_world_kills_exact_parity":True,
            "probe":case["probe"],"result":{
                "status":"COMPLETED","confirmed_kills":100,
                "elapsed_s":old_elapsed,
            },
        })
        reused_ids.append(old_id)
    # Adaptive acquisition is trained on eight-kill receipts. Three-kill
    # features are held as a paired control on the identical Rust labels.
    prefit=train_supervised(
        sessions,engine_sha=args.engine_sha,scenario_id=scenario_id)
    (args.out/"historical_parity_and_surrogate.json").write_text(
        json.dumps({"reused_real_100_labels":len(reused_ids),
                    "parity_checked_candidates":reused_ids,
                    "label_source_engine":historical["source_100_engine_sha"],
                    "model":prefit},indent=2,allow_nan=False)+"\n")
    print("RUST_REAL_100_HISTORICAL_PARITY",json.dumps({
        "candidates":reused_ids,"trained":prefit["time_model"] is not None,
        "loo_mae_elapsed_s":prefit["loo_mae_elapsed_s"],
    }),flush=True)
    # Explore all four native configuration axes with no hand-selected APL
    # order, talent recipe, item list or per-axis quota. Parent selection is
    # driven by eight-kill Rust measurements and the real-100 trained model.
    def evaluate_mutation(mutant, axis, iteration, incumbent_estimate):
        unit=actor(mutant)
        pet=unit["warlock"]["options"]["classOptions"].get("summon","NoSummon")
        return probe_candidate(
            "native_mutation",mutant,"joint_"+axis,unit["talentsString"],pet,
            unit["rotation"]["priorityList"],"evolved_order",
            request_override=mutant)
    search_summary=None
    if args.search_iterations:
        search_summary=adaptive_native_search(
            probes,evaluate=evaluate_mutation,model=prefit,predict=predict,
            engine_sha=args.engine_sha,scenario_id=scenario_id,
            options=options,source_module=search,
            talent_proposals=proposals,
            pets=sorted({c["result"]["pet"] for c in cases}),
            iterations=args.search_iterations,seed=args.seed,
            emit=lambda row: print("RUST_EIGHT_MOB_JOINT_SEARCH",json.dumps(row),
                                   flush=True))
        (args.out/"adaptive_search_summary.json").write_text(
            json.dumps(search_summary,indent=2,allow_nan=False)+"\n")
        print("RUST_EIGHT_MOB_JOINT_DONE",json.dumps(search_summary),flush=True)
    decision_trace=[]
    def pay_full_100(case):
        item=case["result"]
        item["status"]="UNVERIFIED_ERROR"
        try:
            world=native_world_chain(
                binary,case["prepared"],classic_mob_level=30,
                target_count=100,rng_mode="balanced")
            (case["folder"]/"native_100_world.json").write_text(
                json.dumps(world,indent=2,allow_nan=False)+"\n")
            if (world.get("world_targets_killed") != 100
                    or world.get("continuous_native_actor") is not True
                    or world.get("actual_2d_ack") is not True):
                raise RuntimeError("Rust did not confirm 100 ACKs on one actor")
            item.update(status="COMPLETED",
                        confirmed_kills=world["world_targets_killed"],
                        elapsed_s=world["world_elapsed_seconds"],
                        hp_min=world["minimum_native_actor_health"],
                        mana_min=world["minimum_native_actor_mana"])
        except (RuntimeError,ValueError,KeyError,AssertionError,OSError,
                subprocess.TimeoutExpired) as exc:
            item["error_100"]=str(exc)[-1500:]
            detail=exc.args[0] if isinstance(exc,AssertionError) and exc.args else None
            if (isinstance(detail,tuple) and len(detail)>=5
                    and detail[0]=="RUST_TWO_WORLD_NATIVE_FAILED"
                    and type(detail[3]) is int):
                item["confirmed_kills"]=detail[3]
                item["status"]="INCOMPLETE"
            found=re.search(r'RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:index=(\d+)',
                            item["error_100"])
            if found:
                item["confirmed_kills"]=max(0,int(found.group(1))-1)
                item["status"]="INCOMPLETE"
        # New native truth supersedes an older parity-checked label for the
        # same candidate, rather than falsely double-counting training rows.
        if item["status"] in ("COMPLETED","INCOMPLETE"):
            sessions[:]=[row for row in sessions
                         if row.get("candidate") != item["candidate"]]
            sessions.append({
                "candidate":item["candidate"],
                "engine_sha":args.engine_sha,"scenario_id":scenario_id,
                "probe":case["probe"],"result":item.copy(),
            })
        # A crash/timeout is NOT a verified chain death and cannot teach
        # survival regression or create a fictitious fast duration.
        decision_trace.append({
            "candidate":item["candidate"],
            "selection_reason":item["selection_reason"],
            "prediction_at_selection":item.get("surrogate"),
            "native_100_status":item["status"],
            "native_100_kills":item["confirmed_kills"],
            "native_100_elapsed_s":item.get("elapsed_s"),
        })
        (args.out/"100mob_training_labels.json").write_text(
            json.dumps(sessions,indent=2,allow_nan=False)+"\n")
        (case["folder"]/"result.json").write_text(json.dumps(item,indent=2)+"\n")
        print("RUST_100_MOB_LABEL",json.dumps(item),flush=True)

    # Historical parity-verified 100-kill labels are already real paid
    # truth; do not spend full-run budget repeating them.
    validated_ids=set(reused_ids)
    # Refit after each new 100-mob run. The acquisition is model-selected,
    # not a hard-coded priority list of builds, families, axes or spells.
    while len(decision_trace)<args.full_count:
        model=train_supervised(
            sessions,engine_sha=args.engine_sha,scenario_id=scenario_id)
        untested=[case for case in probes
                  if case["result"]["candidate"] not in validated_ids]
        if not untested:
            break
        for case in untested:
            case["result"]["surrogate"]=predict(
                model,case["probe"],engine_sha=args.engine_sha,
                scenario_id=scenario_id)
        observed=[case for case in probes if any(
            session["candidate"]==case["result"]["candidate"]
            for session in sessions)]
        selected,reason=select_native_100_validation(
            untested,observed,iteration=len(validated_ids))
        selected["result"]["selection_reason"]=reason
        pay_full_100(selected)
        validated_ids.add(selected["result"]["candidate"])

    model=train_supervised(
        sessions,engine_sha=args.engine_sha,scenario_id=scenario_id)
    ranking8=report_rank_validation(
        sessions,cases,engine_sha=args.engine_sha,scenario_id=scenario_id)
    probe3_by_candidate={c["result"]["candidate"]:c["probe3"] for c in cases}
    sessions3=[{**row,"probe":probe3_by_candidate[row["candidate"]]}
               for row in sessions if probe3_by_candidate.get(row["candidate"]) is not None]
    ranking3=report_rank_validation(
        sessions3,cases,engine_sha=args.engine_sha,scenario_id=scenario_id)
    ranking={"eight_mob":ranking8,"three_mob_control":ranking3}
    (args.out/"ranking_validation.json").write_text(
        json.dumps(ranking,indent=2,allow_nan=False)+"\n")
    print("RUST_SURROGATE_RANKING_VALIDATION",json.dumps({
        scope:{name:{k:v for k,v in result.items() if k!="rows"}
               for name,result in diag["validation"].items()}
        for scope,diag in ranking.items()}),flush=True)
    (args.out/"surrogate_model.json").write_text(
        json.dumps(model,indent=2,allow_nan=False)+"\n")
    for case in probes:
        case["result"]["surrogate"]=predict(
            model,case["probe"],engine_sha=args.engine_sha,scenario_id=scenario_id)
    successes=sorted(
        ({"candidate":row["candidate"],**row["result"]}
         for row in sessions
         if row["result"].get("status")=="COMPLETED"
         and row["result"].get("confirmed_kills")==100),
        key=lambda c:c["elapsed_s"])
    for winner in successes:
        match=next((c for c in cases if c["result"]["candidate"]
                    == winner["candidate"]),None)
        if match:
            winner["gear"]=match["result"]["gear"]
            winner["pet"]=match["result"]["pet"]
            winner["talents"]=match["result"]["talents"]
            winner["apl"]=json.loads(
                (match["folder"]/"source_request.json").read_text()
            )["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
    summary={
        "engine_sha":args.engine_sha,"scenario_id":scenario_id,
        "source_gear":gear_audit,
        "eight_mob_probes":len(probes),"three_mob_controls":len(sessions3),
        "candidates":len(cases),
        "actual_100_mob_labels":len(sessions),
        "new_native_100_attempts":len(decision_trace),
        "joint_search":search_summary,
        "adaptive_native_100_decisions":decision_trace,
        "model_trained":model["time_model"] is not None,
        "ranking_validation":{key:value["validation"] for key,value in ranking.items()},
        "model":model,"winner_100":successes[0] if successes else None,
        "candidates_with_results":[c["result"] for c in cases],
    }
    (args.out/"optimization_results.json").write_text(
        json.dumps(summary,indent=2,allow_nan=False)+"\n")
    print("RUST_THREE_TO_100_OPTIMIZATION",json.dumps({
        "eight_mob_probes":len(probes),"full_labels":len(sessions),
        "model_trained":summary["model_trained"],
        "winner":summary["winner_100"],
        "joint_search":search_summary,
    }),flush=True)


if __name__=="__main__":
    run()
