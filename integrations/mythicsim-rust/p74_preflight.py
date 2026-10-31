#!/usr/bin/env python3
"""P7.4 fixed-dimension contract. Actual gear catalogue/search is separate."""
import copy, hashlib, json, argparse
from pathlib import Path

def digest(o):
    return hashlib.sha256(json.dumps(o,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def player(request):
    return request["raid"]["parties"][0]["players"][0]
def preflight(reference,candidate=None):
    original=player(reference)
    gear=original["equipment"]["items"]
    if not (len(gear)==16 and all(isinstance(item.get("id"),int) and item["id"]>0 for item in gear)):
        raise ValueError("Reference must contain 16 valid equipment IDs")
    if original["talentsString"]!="5532220115501351--505":
        raise ValueError("Reference talents differ from pinned Balance preset")
    if len(original["rotation"]["priorityList"])!=10:
        raise ValueError("Reference APL differs from pinned 10-action preset")
    witness={"reference_sha256":digest(reference),"fixed_talents":original["talentsString"],
             "fixed_rotation_sha256":digest(original["rotation"]),
             "reference_gear_sha256":digest(original["equipment"])}
    if candidate is not None:
        a=copy.deepcopy(reference);b=copy.deepcopy(candidate)
        ga=player(a).pop("equipment");gb=player(b).pop("equipment")
        if a!=b:
            raise ValueError("P7.4 may change equipment only")
        # A cold search may independently rediscover the saved reference gear.
        # Exclude it from INITIALIZATION, not from legality or holdout.
        if set(gb)!=set(ga):
            raise ValueError("Equipment schema may not be changed")
        items=gb["items"]
        if len(items)!=len(ga["items"]):
            raise ValueError("All 16 gear positions must be specified")
        for orig,cand in zip(ga["items"],items):
            if {k:v for k,v in orig.items() if k!="id"}!={k:v for k,v in cand.items() if k!="id"}:
                raise ValueError("Only item IDs may change; preserve enchants, gems and suffixes")
        if not all(isinstance(x.get("id"),int) and x["id"]>0 for x in items):
            raise ValueError("Each slot needs a positive item ID")
        witness["candidate_gear_sha256"]=digest(gb)
        witness["candidate_ids"]=[x["id"] for x in items]
    return witness
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--reference",type=Path,required=True)
    p.add_argument("--candidate",type=Path)
    a=p.parse_args()
    print(json.dumps(preflight(json.loads(a.reference.read_text()),
         json.loads(a.candidate.read_text()) if a.candidate else None),indent=2))
if __name__=="__main__":main()
