#!/usr/bin/env python3
"""Replay real search artifact candidates on canonical native Rust 8 and 100 mobs.

This is verification of optimizer-produced builds, NOT a handcrafted search
list or a new simulator. The input requests come from an uploaded Actions
artifact of the native 96-mutation 8-mob optimizer.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from live_two_world_pulls import run as native_world_chain


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--binary",type=Path,required=True)
    p.add_argument("--artifact",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--candidate-ids",type=int,nargs="+",default=[114,0])
    args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    binary=args.binary.resolve()
    complete=[]
    attempts=[]
    for cid in args.candidate_ids:
        src=args.artifact/("candidate_%02d"%cid)/"source_request.json"
        prior=json.loads((args.artifact/("candidate_%02d"%cid)/"result.json").read_text())
        if prior.get("status")!="PROBE_COMPLETED" or not prior.get("eight_elapsed_s"):
            raise RuntimeError(f"Candidate {cid} lacks actual 8-mob source receipts")
        folder=args.out/("candidate_%03d"%cid)
        folder.mkdir(exist_ok=True)
        request=json.loads(src.read_text())
        unit=request["raid"]["parties"][0]["players"][0]
        prepared=folder/"prepared.json"
        call=subprocess.run([str(binary),"prepare","--request",str(src.resolve()),
                             "--actor-level","30","--outfile",str(prepared)],
                            capture_output=True,text=True,timeout=120)
        if call.returncode:
            raise RuntimeError("Rust refused original native candidate: "+
                               (call.stderr or call.stdout)[-1500:])
        new_prep=json.loads(prepared.read_text())
        if new_prep["player"]["level"]!=30:
            raise RuntimeError("Not a genuine L30 Warlock")
        eight=native_world_chain(binary,prepared,classic_mob_level=30,
                                 target_count=8,rng_mode="balanced")
        if (eight.get("world_targets_killed")!=8 or
                abs(eight["world_elapsed_seconds"]-
                    prior["eight_elapsed_s"])>1e-5):
            raise RuntimeError("Native 8-mob replay disagrees with recorded optimizer "
                               "receipt for candidate "+str(cid))
        print("NATIVE_EIGHT_REPLAY_PARITY",
              json.dumps({"candidate":cid,"elapsed_s":eight["world_elapsed_seconds"]}),
              flush=True)
        (folder/"eight_replay.json").write_text(json.dumps(eight,indent=2)+"\n")
        result={"candidate":cid,"status":"UNVERIFIED_ERROR",
                "confirmed_kills":0,"talents":unit["talentsString"],
                "pet":unit["warlock"]["options"]["classOptions"].get("summon"),
                "gear":unit["equipment"]["items"],
                "apl":unit["rotation"]["priorityList"],
                "eight_elapsed_s":eight["world_elapsed_seconds"]}
        try:
            hundred=native_world_chain(binary,prepared,classic_mob_level=30,
                                       target_count=100,rng_mode="balanced")
            (folder/"hundred_world.json").write_text(
                json.dumps(hundred,indent=2)+"\n")
            if (hundred.get("world_targets_killed")!=100 or
                hundred.get("continuous_native_actor") is not True or
                hundred.get("actual_2d_ack") is not True):
                raise RuntimeError("Missing native 100 world lethal acknowledgments")
            result.update(status="COMPLETED",confirmed_kills=100,
                          elapsed_s=hundred["world_elapsed_seconds"])
        except (RuntimeError,ValueError,AssertionError,
                subprocess.TimeoutExpired) as exc:
            result["error"]=str(exc)[-1200:]
            detail=exc.args[0] if isinstance(exc,AssertionError) and exc.args else None
            if (isinstance(detail,tuple) and len(detail)>=5 and
                    detail[0]=="RUST_TWO_WORLD_NATIVE_FAILED" and type(detail[3]) is int):
                result["confirmed_kills"]=detail[3]
                result["status"]="INCOMPLETE"
            match=re.search(r"RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:index=(\d+)",
                            result["error"])
            if match:
                result["confirmed_kills"]=max(0,int(match.group(1))-1)
                result["status"]="INCOMPLETE"
        (folder/"result.json").write_text(json.dumps(result,indent=2)+"\n")
        attempts.append(result)
        print("NATIVE_L30_100_REAL_CANDIDATE",json.dumps(result),flush=True)
        if result["status"]=="COMPLETED":
            complete.append(result)
    report={"native_100_completed":len(complete),"attempts":attempts,
            "winner":min(complete,key=lambda row:row["elapsed_s"]) if complete else None}
    (args.out/"paid_100_replay_results.json").write_text(
        json.dumps(report,indent=2)+"\n")
    print("NATIVE_L30_100_REAL_COMPARISON",json.dumps(report),flush=True)
    if not complete:
        raise RuntimeError("ZERO_NATIVE_100_COMPLETIONS: no winner proven")


if __name__=="__main__":
    main()
