#!/usr/bin/env python3
"""Native 3-world-mob probe + real-100-label training of a tiny L30 surrogate.

The predictor never implements a spell, a stat formula, a pet, regeneration
or a battle. Only Rust carries the actor through actual world-mob deaths.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

from wf_warlock_native_optimizer import (
    actor, call, native_level_equipment, native_pet_autocast_receipt,
    native_sustain_receipt, profile, set_native_pet, set_native_sustain_buffs,
)
from wf_warlock_l30_direct_affliction_comparison import (
    USER_AFFLICTION, OLD_DESTRO_COMPARATOR, exact_source_ranks, make_apl,
)
from wf_warlock_chain_surrogate import (
    extract_three_mob_features, predict, train_supervised,
)
from live_two_world_pulls import run as native_world_chain


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--engine-tools", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--engine-sha", required=True)
    parser.add_argument("--full-count", type=int, default=8)
    args = parser.parse_args()
    if not 0 <= args.full_count <= 16:
        parser.error("full-count must be 0..16")
    args.out.mkdir(parents=True,exist_ok=True)
    binary=args.binary.resolve()
    source=json.loads(args.source.read_text())
    source["encounter"]["targets"][0]["level"]=30
    actor(source)["name"]="Warlock L30 Troll three-mob surrogate"
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
    for gear_name,base in (("native_dps",dps_gear),("native_max_hp",hp_gear)):
        for build_name,build in (
                ("user_affliction",USER_AFFLICTION),
                ("prior_destro",OLD_DESTRO_COMPARATOR)):
            for pet in ("Succubus","Felhunter"):
                for filler in ("drain life","shadow bolt"):
                    index=len(cases)
                    folder=args.out/("candidate_%02d" % index)
                    folder.mkdir(exist_ok=True)
                    request=copy.deepcopy(base)
                    actor(request)["talentsString"]=build
                    set_native_pet(request,pet)
                    actor(request)["rotation"]["priorityList"]=make_apl(
                        search,ids,affliction=build_name=="user_affliction",
                        filler=filler)
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
                    try:
                        call([binary,"prepare","--request",source_path,
                              "--actor-level","30","--outfile",prepared_path])
                        prepared=json.loads(prepared_path.read_text())
                        item["pet_autocasts"]=native_pet_autocast_receipt(prepared,pet)
                        item["sustain"]=native_sustain_receipt(prepared,request)
                        three=native_world_chain(
                            binary,prepared_path,classic_mob_level=30,
                            target_count=3,rng_mode="balanced")
                        (folder/"three_native_world.json").write_text(
                            json.dumps(three,indent=2,allow_nan=False)+"\n")
                        probe=extract_three_mob_features(prepared,three)
                        (folder/"three_features.json").write_text(
                            json.dumps(probe,indent=2,allow_nan=False)+"\n")
                        item.update(status="PROBE_COMPLETED",
                                    three_elapsed_s=three["world_elapsed_seconds"],
                                    features=probe["features"],
                                    cooldowns=probe["cooldowns"])
                    except (RuntimeError,ValueError,KeyError,AssertionError,OSError,
                            subprocess.TimeoutExpired) as exc:
                        item.update(status="PROBE_FAILED",error=str(exc)[-1800:])
                    cases.append({"result":item,"probe":probe,
                                  "prepared":prepared_path,"folder":folder})
                    (folder/"result.json").write_text(json.dumps(item,indent=2)+"\n")
                    print("RUST_THREE_MOB_FEATURES",json.dumps(item),flush=True)
    probes=[case for case in cases if case["probe"] is not None]
    sessions=[]
    # Broad source-native bootstrap, not 30-second DPS ordering:
    # both talent families, both pet types, both gear tracks and fillers.
    bootstrap=(0,3,4,7,8,11,12,15,1,5,9,13,2,6,10,14)
    chosen=[case for idx in bootstrap for case in probes
            if case["result"]["candidate"]==idx][:args.full_count]
    def pay_full_100(case):
        item=case["result"]
        item["status"]="INCOMPLETE"
        try:
            world=native_world_chain(
                binary,case["prepared"],classic_mob_level=30,
                target_count=100,rng_mode="balanced")
            (case["folder"]/"native_100_world.json").write_text(
                json.dumps(world,indent=2,allow_nan=False)+"\n")
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
            found=re.search(r'RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:index=(\d+)',
                            item["error_100"])
            if found:
                item["confirmed_kills"]=max(0,int(found.group(1))-1)
        sessions.append({
            "engine_sha":args.engine_sha,"scenario_id":scenario_id,
            "probe":case["probe"],"result":item.copy(),
        })
        (args.out/"100mob_training_labels.json").write_text(
            json.dumps(sessions,indent=2,allow_nan=False)+"\n")
        (case["folder"]/"result.json").write_text(json.dumps(item,indent=2)+"\n")
        print("RUST_100_MOB_LABEL",json.dumps(item),flush=True)

    for case in chosen:
        pay_full_100(case)
    model=train_supervised(
        sessions,engine_sha=args.engine_sha,scenario_id=scenario_id)
    (args.out/"surrogate_model.json").write_text(
        json.dumps(model,indent=2,allow_nan=False)+"\n")
    # After a diverse truth-labeled calibration batch, spend the remaining
    # 100-mob budget where the trained model predicts best *or* where the
    # native HP/mana/kill-slope receipts are promising if no model is trained.
    untested=[case for case in probes if case not in chosen]
    for case in untested:
        case["result"]["surrogate"]=predict(
            model,case["probe"],engine_sha=args.engine_sha,scenario_id=scenario_id)
    if model["time_model"] is not None:
        untested.sort(key=lambda case: (
            -(case["result"]["surrogate"]["probability_100_mob_completed"]
              if case["result"]["surrogate"]["probability_100_mob_completed"] is not None
              else .5),
            case["result"]["surrogate"]["estimated_100_mob_elapsed_s"],
        ))
    else:
        untested.sort(key=lambda case: (
            -case["probe"]["features"]["health_end_fraction"],
            -case["probe"]["features"]["mana_end_fraction"],
            case["probe"]["features"]["kill_time_slope"],
            case["probe"]["features"]["late_kill_s"],
        ))
    for case in untested[:max(0,args.full_count-len(sessions))]:
        pay_full_100(case)
    model=train_supervised(
        sessions,engine_sha=args.engine_sha,scenario_id=scenario_id)
    (args.out/"surrogate_model.json").write_text(
        json.dumps(model,indent=2,allow_nan=False)+"\n")
    for case in probes:
        case["result"]["surrogate"]=predict(
            model,case["probe"],engine_sha=args.engine_sha,scenario_id=scenario_id)
    successes=sorted(
        (c["result"] for c in cases if c["result"]["status"]=="COMPLETED"),
        key=lambda c:c["elapsed_s"])
    summary={
        "engine_sha":args.engine_sha,"scenario_id":scenario_id,
        "source_gear":gear_audit,
        "three_mob_probes":len(probes),"candidates":len(cases),
        "actual_100_mob_labels":len(sessions),
        "model_trained":model["time_model"] is not None,
        "model":model,"winner_100":successes[0] if successes else None,
        "candidates_with_results":[c["result"] for c in cases],
    }
    (args.out/"optimization_results.json").write_text(
        json.dumps(summary,indent=2,allow_nan=False)+"\n")
    print("RUST_THREE_TO_100_OPTIMIZATION",json.dumps({
        "probes":len(probes),"full_labels":len(sessions),
        "model_trained":summary["model_trained"],
        "winner":summary["winner_100"],
    }),flush=True)


if __name__=="__main__":
    run()
