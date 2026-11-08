#!/usr/bin/env python3
"""Assert actual native Warlock L30 Shoot, not Python-approximated wand DPS."""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
from pathlib import Path


def prepare(binary: Path, request: dict, folder: Path, label: str) -> dict:
    input_path=folder/(label+".request.json")
    prepared_path=folder/(label+".prepared.json")
    input_path.write_text(json.dumps(request,indent=2)+"\n")
    p=subprocess.run([str(binary), "prepare", "--request",str(input_path),
                      "--actor-level","30","--outfile",str(prepared_path)],
                     capture_output=True,text=True,timeout=90)
    if p.returncode:
        raise RuntimeError("Native L30 prepare refused "+label+": "+
                           (p.stderr or p.stdout)[-1900:])
    return json.loads(prepared_path.read_text())


def run():
    ap=argparse.ArgumentParser()
    ap.add_argument("--binary",type=Path,required=True)
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    options=subprocess.run(
        [str(args.binary.resolve()),"options","--class","warlock",
         "--level","30"],capture_output=True,text=True,check=True,timeout=90)
    available=json.loads(options.stdout)["items"]
    wands=[(row["item_id"],native["required_level"])
           for row in available
           if row.get("eligibility")=="native_eligible"
           and (native:=row.get("native"))
           and native.get("ranged_weapon_type")=="RangedWeaponTypeWand"
           and type(native.get("required_level")) is int
           and 0<native["required_level"]<=30]
    if not wands:
        raise RuntimeError("Rust source options do not expose a legal-level wand")
    # Source metadata proposes only; Rust itself prepares and verifies.
    wand=min(wands,key=lambda item:(item[1],item[0]))
    source=json.loads(args.source.read_text())
    player=source["raid"]["parties"][0]["players"][0]
    player["race"]="RaceTroll"
    player["equipment"]["items"]=[{"id":0} for _ in range(17)]
    player["equipment"]["items"][16]={"id":wand[0]}
    player["rotation"]["priorityList"]=[
        {"action":{"castSpell":{"spellId":{"otherId":"OtherActionShoot"}}}}
    ]
    equipped=prepare(args.binary.resolve(),source,args.out,"with_wand")
    empty=copy.deepcopy(source)
    empty["raid"]["parties"][0]["players"][0]["equipment"]["items"][16]={"id":0}
    no_wand=prepare(args.binary.resolve(),empty,args.out,"without_wand")
    def registered(row):
        return any(s.get("action_id",{}).get("other_id")=="OtherActionShoot"
                   for s in row["player"].get("spells",[]))
    if equipped["player"]["level"]!=30 or no_wand["player"]["level"]!=30:
        raise RuntimeError("Native actor level is not 30")
    if not registered(equipped):
        raise RuntimeError("Equipped wand did not register native OtherActionShoot")
    if registered(no_wand):
        raise RuntimeError("No-wand actor produced phantom native Shoot")
    if equipped["melee"]["auto_swing_ranged"] is not True:
        raise RuntimeError("Wand did not enable real native ranged swings")
    if no_wand["melee"]["auto_swing_ranged"] is not False:
        raise RuntimeError("No wand still swings ranged")
    # Registration alone is insufficient! Before this fix the 8-mob runtime
    # refused an APL that actually cast OtherActionShoot ("unknown behavior").
    # The canonical Rust check must confirm that this action can execute.
    check=subprocess.run(
        [str(args.binary.resolve()),"check","--infile",
         str(args.out/"with_wand.prepared.json")],
        capture_output=True,text=True,timeout=90)
    if check.returncode:
        raise RuntimeError("Native Shoot APL coverage check failed: "+
                           (check.stderr or check.stdout)[-1800:])
    coverage=json.loads(check.stdout)
    if coverage.get("supported") is not True:
        raise RuntimeError("Native Shoot APL cannot execute: "+
                           repr(coverage.get("refusals")))
    print("RUST_L30_NATIVE_SHOOT_PROVEN",json.dumps({
        "actor_level":30,"source_wand_item_id":wand[0],
        "wand_required_level":wand[1],"shoot_equipped":True,
        "shoot_without_wand":False,"native_ranged_auto_attack":True,
        "native_shoot_apl_coverage":coverage["supported"]
    }),flush=True)


if __name__=="__main__":
    run()
