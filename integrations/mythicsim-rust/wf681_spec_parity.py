#!/usr/bin/env python3
"""WF681: paired Feral/Balanced native Rust APL+settings parity probes.

Diagnostic A/B only. Not a candidate in unrestricted cold optimization;
historical Go/2D Feral 848 is not a Rust comparator. Every same-scenario
pair freezes encounter, raid/player buffs and player consumables identically.
"""
import argparse,copy,hashlib,json,random,time
from pathlib import Path
from p73_talent_search_v2 import run,player,sha
from p75_unrestricted_search import source_template,FIXTURES

def construct(reference,feral,kind,seed):
    q=copy.deepcopy(reference)
    p=player(q)
    if kind.startswith("feral"):
        # Preserve class/race and raid scenario from saved Balance request.
        fp=player(feral)
        for spec in ("balanceDruid","feralCatDruid","feralBearDruid","restorationDruid"):
            p.pop(spec,None)
        p["feralCatDruid"]=copy.deepcopy(fp["feralCatDruid"])
        p["inFrontOfTarget"]=False
        p["distanceFromTarget"]=0
        p["talentsString"]=fp["talentsString"]
        p["rotation"]=copy.deepcopy(fp["rotation"])
        if "source_gear" in kind:p["equipment"]=copy.deepcopy(fp["equipment"])
        if "source_cons" in kind:
            p["consumables"]=copy.deepcopy(fp["consumables"])
            p["buffs"]=copy.deepcopy(fp["buffs"])
        if "random_apl" in kind:
            random.Random(seed).shuffle(p["rotation"]["priorityList"])
    elif kind=="balance":
        pass
    else:raise ValueError(kind)
    return q

def main():
    ap=argparse.ArgumentParser()
    for n in ("binary","reference","feral","outdir"):ap.add_argument("--"+n,type=Path,required=True)
    a=ap.parse_args()
    ref=json.loads(a.reference.read_text());feral=json.loads(a.feral.read_text())
    a.outdir.mkdir(parents=True,exist_ok=True)
    variants=["balance","feral_source_gear_source_cons","feral_source_gear",
              "feral_source_gear_random_apl","feral","feral_random_apl"]
    outputs={}
    for name in variants:
        q=construct(ref,feral,name,seed=681)
        try:
            # Native with 1000 stochastic fights to avoid balanced RNG panic
            value,result,elapsed,req_hash=run(a.binary,q,1000,681000,"stochastic",time.monotonic()+45)
            outputs[name]={"status":"OK","dps":value,"seconds":elapsed,
                           "request_sha256":req_hash,"gear":[x["id"] for x in player(q)["equipment"]["items"]],
                           "talents":player(q)["talentsString"],
                           "rotation_sha256":sha(player(q)["rotation"]),
                           "scenario_encounter_sha256":sha(q["encounter"]),
                           "raid_buffs_sha256":sha(q["raid"]["buffs"]),
                           "raid_debuffs_sha256":sha(q["raid"]["debuffs"]),
                           "player_buffs_sha256":sha(player(q).get("buffs",{})),
                           "player_consumables_sha256":sha(player(q).get("consumables",{}))}
        except Exception as e:
            outputs[name]={"status":"RUST_REFUSED","error":str(e)[:1800]}
    (a.outdir/"paired_probe_report.json").write_text(json.dumps({
        "source":"pinned Rust executable; stochastic RNG, seed=681000, 1000 fights per case",
        "historical_feral_go_hybrid_not_comparable":True,"probes":outputs},indent=2))
    print(json.dumps(outputs,indent=2),flush=True)
    # At minimum baseline and original Feral source must work.
    if outputs["balance"]["status"]!="OK" or outputs["feral_source_gear_source_cons"]["status"]!="OK":
        raise RuntimeError("Paired baseline failed; inspect native incompatibility before cross-spec ranking")
if __name__=="__main__":main()
