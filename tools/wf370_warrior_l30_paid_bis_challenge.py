"""Independent source-BiS challenge of WF368's provisional Arms gear context.

Existing CombatRuntime and 100-mob scorer only. No 21-point talent claim,
no P4 cold search, and no use of legacy winner as an optimization seed.
"""
from __future__ import annotations
import json,os,time,hashlib
from pathlib import Path
from src.rulesets.forever.items.runtime_selection import (gear_overrides,clear_runtime_item_cache,available_items)
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.gear import select_named_gear
from tools.wf368_warrior_l30_p3_paid_swaps import gear_ir,eval_selection,ABILITY
from tools.wf370_warrior_l30_source_bis_stage import stage,STAGE,SOURCE
from src.rulesets.forever.items.runtime_selection import _source_class_profile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/wf370/WF370_WARRIOR_L30_BIS_100MOB_CHALLENGE.json'

def run():
    t0=time.perf_counter();c0=time.process_time()
    stage_result=stage()
    os.environ['FOREVER_ITEM_CATALOGUE']=str(STAGE)
    clear_runtime_item_cache()
    ir=build_game_ir_slice(class_key='warrior',level=30,ability_db_path=ABILITY)
    role='warrior_arms'; weights=_source_class_profile('warrior')['gear_selection_roles'][role]['proxy_weights']
    inventory=available_items('warrior',30,required_level_policy='observed')
    ids={i.item_id for i in inventory}
    assert {6976,1488}.issubset(ids)
    base={'weapon':279841,'chest':2870}
    challenges={
      'wf368_equivalent':base,
      'new_weapon':{**base,'weapon':6976},
      'new_chest':{**base,'chest':1488},
      'both_new':{'weapon':6976,'chest':1488},
    }
    rows=[]
    for label,pins in challenges.items():
        t=time.perf_counter();c=time.process_time()
        with gear_overrides(pins):
            selected=select_named_gear(class_key='warrior',level=30,role=role,stat_weights=weights,
                required_level_policy='observed',exclude_unknown_item_effects=True)
        actual={slot:int(v['item_id']) for slot,v in selected.slots.items()}
        assert all(actual.get(k)==v for k,v in pins.items()),(label,actual)
        result=eval_selection(ir,selected)
        rows.append({'label':label,'pins':pins,'gear_ids':actual,'status':result['status'],
                     'mean_s_per_mob':result.get('mean_s_per_mob'),'events':result.get('events'),
                     'result':result,'wall_s':time.perf_counter()-t,'cpu_s':time.process_time()-c})
        print(label,result['status'],result.get('mean_s_per_mob'),result.get('events'),flush=True)
    base_s=rows[0]['mean_s_per_mob']
    out={'checkpoint':'warrior:L30:unrestricted','source':str(SOURCE.relative_to(ROOT)),
         'source_sha256':stage_result['source_sha256'],'staged_sqlite_sha256':stage_result['staged_sha256'],
         'p1':{'status':'PASS','coverage':'54/54'},'p2':{'status':'PASS','coverage':'117/117'},
         'p3':{'status':'FAIL','source_backed_individual_item_witnesses':11,
               'new_legal_items_added':2,'provisional_observed_legal_items':len(inventory),
               'true_class_legal_denominator':None,'class_membership_verified':False},
         'p4':{'status':'NOT_RUN'},'p5':{'status':'NOT_RUN'},'p6':{'status':'NOT_RUN'},
         'talent_context':'NO_TALENT_ALLOCATION: L2_ONLY; FULL_21_POINT_L0_CONTEXT_NOT_PAID',
         'rows':rows,'improvement_over_wf368_equivalent':[
           {'label':r['label'],'fraction':(r['mean_s_per_mob']/base_s-1) if r['status']=='COMPLETE' else None}
           for r in rows],
         'measurement':{'wall_s':time.perf_counter()-t0,'cpu_s':time.process_time()-c0,
                        'attempts':len(rows),'complete':sum(r['status']=='COMPLETE' for r in rows),
                        'events':sum(r['events'] or 0 for r in rows),
                        'unique_gear_builds':len({tuple(sorted(r['gear_ids'].items())) for r in rows})},
         'uncertainty':['Source BiS is not the entire legal item universe.',
           'Whirlwind Warhammer is a Warrior-only quest reward available via level-30 quest chain; level-40 boss may need help.',
           'Gear test holds the executable zero-point Warrior policy and does not score 21-point talent synergies.',
           'No P4/P5/P6 30/300-second joint search was run.']}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    return out

if __name__=='__main__':
    r=run();print(json.dumps({'p3':r['p3'],'measurement':r['measurement'],'improvement':r['improvement_over_wf368_equivalent']},indent=2))
