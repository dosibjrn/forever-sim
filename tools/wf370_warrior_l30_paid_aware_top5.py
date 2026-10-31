"""Rebase Warrior L30 provisional Top5 on real 100-mob swap measurements.

Measured finalists are preserved alongside uncertain source-item L0 proxy picks.
No claim of exhaustive Warrior class membership or 21-point L2 calibration.
"""
from __future__ import annotations
import json,os,time
from pathlib import Path
from src.rulesets.forever.items.runtime_selection import clear_runtime_item_cache
from src.game.data.forever.source_checkpoint_p3_empirical_weights import (fit_swap_weights,rank_all_legal_items_with_proxy)
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
from tools.wf370_warrior_l30_source_bis_stage import STAGE
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/wf370/WF370_WARRIOR_L30_PAID_AWARE_TOP5.json'

def run():
    t=time.perf_counter();c=time.process_time()
    os.environ['FOREVER_ITEM_CATALOGUE']=str(STAGE);clear_runtime_item_cache()
    old=json.loads((ROOT/'evidence/wf368/WF368_WARRIOR_L30_P3_PAID_GEAR_SWAPS.json').read_text())
    new=json.loads((ROOT/'evidence/wf370/WF370_WARRIOR_L30_BIS_100MOB_CHALLENGE.json').read_text())
    new_chest=next(x for x in new['rows'] if x['label']=='new_chest')
    assert new_chest['status']=='COMPLETE'
    results=old['results']+[{'slot':'chest','item_id':1488,'name':"Avenger's Armor",
        'source_url':'https://foreverdb.net/item/1488','swaps':{'chest':1488},'result':new_chest['result']}]
    stage={'gear_policy_result':{'winner':{'gear':{'slots':old['baseline_gear']['slots']}}}}
    model=fit_swap_weights(stage=stage,results=results,baseline_s_per_mob=old['baseline']['mean_s_per_mob'],
        class_key='warrior',level=30)
    ranked=rank_all_legal_items_with_proxy(stage=stage,model=model,class_key='warrior',level=30,
        paired_offhand_weapon_id=7687)
    coverage=checkpoint_item_l0(class_key='warrior',level=30)
    shortlist={}
    for slot,entry in ranked.items():
        direct=[r for r in results if r['slot']==slot and r['result']['status']=='COMPLETE']
        incumbent=old['baseline_gear']['slots'].get(slot)
        if incumbent is not None:
            direct.append({'slot':slot,'item_id':int(incumbent['item_id']),
                'name':incumbent['name'],'source_url':incumbent['source_url'],
                'swaps':{slot:int(incumbent['item_id'])},'result':old['baseline']})
        direct=sorted(direct,key=lambda r:(r['result']['mean_s_per_mob'],r['item_id']))
        blocked_bis={int(row['pins']['weapon']):row for row in new['rows']
            if row['status']!='COMPLETE' and 'weapon' in row['pins']}
        picks=[];seen=set()
        for r in direct[:2]:
            if r['item_id'] in seen:continue
            seen.add(r['item_id'])
            picks.append({'item_id':r['item_id'],'name':r['name'],'basis':'PAID_100_CONSECUTIVE_MOBS',
                'measured_s_per_mob':r['result']['mean_s_per_mob'],'source_url':r['source_url'],
                'swaps':r['swaps']})
        for r in entry['known_component_top5']:
            if len(picks)>=5:break
            if r['item_id'] in seen:continue
            seen.add(r['item_id'])
            picks.append({'item_id':r['item_id'],'name':r['name'],'basis':'UNCERTAIN_L0_RIDGE_PROXY',
                'known_proxy_improvement_s_per_mob':r['known_proxy_improvement_s_per_mob'],
                'source_url':r['source_url'],'swaps':r['swaps'],
                'unresolved_source_effects':r['unresolved_source_effects'],
                'paid_100mob_challenge_status':blocked_bis[r['item_id']]['status']
                    if slot=='weapon' and r['item_id'] in blocked_bis else None,
                'paid_100mob_challenge_failure':blocked_bis[r['item_id']]['result'].get('reason')
                    if slot=='weapon' and r['item_id'] in blocked_bis else None})
        shortlist[slot]={'top5_shortlist':picks,'paid_direct_complete':len(direct),
            'evaluated_legal_equipment_packages':entry['evaluated_legal_equipment_packages'],
            'ranking_uncertainty':entry['ranking_uncertainty']}
    assert len(shortlist)==18 and all(v['top5_shortlist'] for v in shortlist.values())
    out={'checkpoint':'warrior:L30:unrestricted','gate3':'FAIL','source_membership_verified':False,
         'provisional_legal_denominator':coverage['legal_item_count'],
         'provisional_l0_assessed':coverage['l0_assessed_count'],
         'unknown_effect_items':coverage['unknown_effect_item_count'],
         'source_backed_bis_witnesses':11,'new_source_items':2,
         'measured_complete_swaps_model':model['n'],
         'model_cv_mae_s_per_mob':model['cv_mae_s_per_mob'],
         'model_status':model['status'],
         'slots':shortlist,'wall_s':time.perf_counter()-t,'cpu_s':time.process_time()-c,
         'limitations':['Only per-item BiS witness legality is sourced; full class-1 denominator remains unknown.',
           'This is a paid-aware candidate shortlist, not a mathematically sorted top5.',
           'All paid 100-mob data use zero allocated talents; 21-point interactions remain L0-only.',
           'Offhand is paired with a one-hand weapon at L0; no 100-mob offhand challenger here.',
           'Unknown source effects remain visible and never silently zeroed.']}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    return out

if __name__=='__main__':
    r=run();print(json.dumps({'p3':r['gate3'],'slots':len(r['slots']),
        'provisional_coverage':str(r['provisional_l0_assessed'])+'/'+str(r['provisional_legal_denominator']),
        'measured_complete_swaps_model':r['measured_complete_swaps_model'],
        'model_cv_mae_s_per_mob':r['model_cv_mae_s_per_mob'],
        'chest':r['slots']['chest']['top5_shortlist'][:3],
        'weapon':r['slots']['weapon']['top5_shortlist'][:3]},indent=2))
