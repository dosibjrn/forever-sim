"""Replay provenance audit of a frozen external legacy L30 inventory.

Never mutate item origin nor replace unavailable legacy items with substitutes.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from src.rulesets.forever.items.runtime_selection import available_items


def audit(legacy:dict, *, level:int=30) -> dict:
    inventory=dict(legacy['gear']['slots'])
    catalogue={int(row.item_id):row for row in available_items('druid',level,required_level_policy='catalogue')}
    observed={int(row.item_id):row for row in available_items('druid',level,required_level_policy='observed')}
    rows=[]
    for slot,raw in sorted(inventory.items()):
        item_id=int(raw['item_id']); item=catalogue.get(item_id)
        rows.append({'slot':slot,'item_id':item_id,'name':raw.get('name'),
           'in_catalogue_level_eligible':item is not None,
           'in_observed_source_level_eligible':item_id in observed,
           'required_level_origin':item.required_level_origin if item else None,
           'effective_required_level':item.required_level if item else None,
           'source_url':item.source_url if item else None})
    failed=[r for r in rows if not r['in_observed_source_level_eligible']]
    return {'status':'NOT_FULLY_SOURCE_VERIFIED' if failed else 'SOURCE_OBSERVED_FULLY_VERIFIED',
       'legacy_winner_talents':dict(legacy['talent_ranks']),
       'legacy_winner_policy':legacy['rotation'],
       'slots_total':len(rows),'source_observed_eligible':len(rows)-len(failed),
       'source_provenance_gaps':failed,'all_slot_audit':rows,
       'note':'No item substitutions. Not a P7 result; the build must still execute in the common 100mob CombatRuntime.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--legacy',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); legacy=json.loads(args.legacy.read_text()); data=audit(legacy)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
    print(data['status'],data['source_observed_eligible'],'/',data['slots_total'],flush=True)

if __name__=='__main__':main()
