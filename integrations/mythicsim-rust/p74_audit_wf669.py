#!/usr/bin/env python3
"""Independent, data-driven audit of an historical winning gear loadout.

Unlike replaying an old DPS number, this interrogates the pinned Rust item DB.
Any rejection stays in the audit evidence; cannot be silently called PASS.
"""
import argparse
import json
from pathlib import Path
from p74_gear_validation import GearValidator, RejectedGear

def audit_winner(reference, report, catalogue, items, enchants):
    from p74_preflight import player
    ids=report["winner"]["ids"]
    v=GearValidator(catalogue,items,enchants,reference)
    try:
        entries=[];errors=[]
        for idx,item_id in enumerate(ids):
            try:entries.append(v.item(idx,item_id))
            except RejectedGear as exc:
                errors.append({"slot_index":idx,"item_id":item_id,"category":exc.category,"reason":str(exc)})
        if not errors:
            try:v.validate(ids)
            except RejectedGear as exc:errors.append({"category":exc.category,"reason":str(exc)})
        return {"status":"REJECTED" if errors else "SOURCE_AND_PINNED_ENGINE_IDENTITY_LEGAL",
                "historical_winner_ids":ids,
                "verified_items":entries,"rejections":errors,
                "source_catalogue_sha256":__import__("hashlib").sha256(Path(catalogue).read_bytes()).hexdigest(),
                "pinned_items_sha256":__import__("hashlib").sha256(Path(items).read_bytes()).hexdigest(),
                "known_limitations":["This is not a live Go↔Rust causality check",
                                     "Undocumented faction/phase/profession restrictions are not certified"]}
    finally:v.close()

def main():
    p=argparse.ArgumentParser()
    for n in ("reference","report","catalogue","engine-items","engine-enchants","out"):
        p.add_argument("--"+n,required=True,type=Path)
    a=p.parse_args()
    result=audit_winner(json.loads(a.reference.read_text()),json.loads(a.report.read_text()),
                        a.catalogue,a.engine_items,a.engine_enchants)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"status":result["status"],"rejections":result["rejections"]},indent=2))

if __name__=="__main__":main()
