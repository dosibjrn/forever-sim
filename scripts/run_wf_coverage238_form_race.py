"""Held-constant source gear and policy-budget race for form crit/avoidance."""
import json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_mode_search import evaluate_discovered_mode_search


def run(output: Path):
    source=build_game_ir_slice(class_key='druid',level=20)
    gears=_gear_envelope('druid',20,max_gear_candidates=64,
        required_level_policy='observed',include_melee_gear=True,ir_slice=source)
    gear=gears[0]
    geared,_=apply_gear_selection(source,aggregate_stats=gear['selection'].aggregate_stats,
        selected_items=tuple(gear['selection'].slots.values()),source='canonical_sqlite_forever_catalogue')
    cases=(('base',{'ferocity':5,'heart_of_the_wild':4}),
           ('source_dodge',{'ferocity':5,'heart_of_the_wild':4,'feral_swiftness':2}),
           ('source_crit',{'ferocity':5,'heart_of_the_wild':5,'sharpened_claws':1}))
    rows=[]
    for label,allocation in cases:
        ir,_=apply_talent_selection(geared,allocation,level=20)
        result=evaluate_discovered_mode_search(class_key='druid',level=20,ir_slice=ir,
            max_policies_per_path=24,schedule_incoming_attacks=True)
        rows.append({'label':label,'talents':allocation,'winner':result['winner'],
                     'evaluated_count':result['evaluated_count']})
    result={'version':'0.11.48.238','level':20,'class_key':'druid',
            'same_gear_id':gear['id'],'same_policy_cap':24,
            'same_incoming_attacks':True,'cases':rows,
            'global_optimum_claim':False,
            'note':'The three allocations differ in other filler points. This is a mechanism sensitivity probe, not a one-talent causal isolation.'}
    output.write_text(json.dumps(result,indent=2)+'\n')
    for r in rows:print(r['label'],r['winner']['seconds_per_mob'])
    return result

if __name__=='__main__':run(Path('WF_COVERAGE238_FORM_MECHANISM_RACE.json'))
