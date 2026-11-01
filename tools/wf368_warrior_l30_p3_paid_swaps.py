"""Warrior L30 P3 provisional-source measured Top5 calibration, same CombatRuntime.

Uses source-sourced *provisional* Warrior membership, not an accepted denominator.
Only source-effect-resolved equipment is paid into 100 consecutive mobs. The
Warrior's original executable source policy is the fixed context; this is not
P4's independent gear×talent×rotation search and not a complete 21-point build.
"""
from __future__ import annotations
import hashlib,json,os,time,resource
from collections import defaultdict
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.gear import select_named_gear
from src.game.gear import apply_gear_selection
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,source_item_l0,source_item_slots
from src.game.data.forever.source_checkpoint_p3_empirical_weights import fit_swap_weights,rank_all_legal_items_with_proxy
from src.game.data.forever.source_checkpoint_p3_ratings import apply_source_equipped_item_stats
from src.rulesets.forever.items.source_equipment_semantics import apply_equipped_source_effects
from src.rulesets.forever.items.source_numeric_extras import apply_source_numeric_extras
from src.rulesets.forever.items.runtime_selection import (
    available_items,item_score,gear_overrides,_source_class_profile,clear_runtime_item_cache)
from src.v2.source_persistent_joint_finalists import PreparedCandidate,evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]
ABILITY=ROOT/'data/forever/staged_warrior_l30_gear_runtime_wf368.sqlite'
ITEMS=ROOT/'data/forever/staged_warrior_l30_gear_provisional_wf365.sqlite'
OUT=ROOT/'evidence/wf368/WF368_WARRIOR_L30_P3_PAID_GEAR_SWAPS.json'


def gear_ir(base_ir,selection):
    ids=tuple(int(x['item_id']) for x in selection.slots.values())
    ir,applied=apply_gear_selection(base_ir,aggregate_stats=selection.aggregate_stats,
        selected_items=tuple(selection.slots.values()),db_path=ABILITY)
    if applied.unsupported_stats:
        raise ValueError('UNSUPPORTED_SOURCE_GEAR_STATS:'+str(applied.unsupported_stats))
    ir=apply_source_equipped_item_stats(ir,class_key='warrior',level=30,item_ids=ids)
    ir=apply_equipped_source_effects(ir,class_key='warrior',level=30,item_ids=ids)
    ir=apply_source_numeric_extras(ir,class_key='warrior',level=30,item_ids=ids)
    return ir


def eval_selection(base_ir,selection):
    ir=gear_ir(base_ir,selection)
    return evaluate_persistent_candidate(PreparedCandidate(ir,ir.policies[0],(),{},{}),
        level=30,mobs=100,max_wall_s=8,max_cpu_s=8,max_total_events=300000)


def run(max_per_slot=7):
    started=time.perf_counter();cpu=time.process_time()
    os.environ['FOREVER_ITEM_CATALOGUE']=str(ITEMS)
    clear_runtime_item_cache()
    profile=_source_class_profile('warrior')
    role='warrior_arms'
    weights=profile['gear_selection_roles'][role]['proxy_weights']
    ir=build_game_ir_slice(class_key='warrior',level=30,ability_db_path=ABILITY)
    baseline_gear=select_named_gear(class_key='warrior',level=30,role=role,stat_weights=weights,
        required_level_policy='observed',exclude_unknown_item_effects=True)
    baseline=eval_selection(ir,baseline_gear)
    if baseline['status']!='COMPLETE':raise ValueError('WARRIOR_ARMS_BASELINE_NOT_100MOB_COMPLETE:'+str(baseline))
    inventory=checkpoint_item_l0(class_key='warrior',level=30)
    items=available_items('warrior',30,required_level_policy='observed')
    slots=defaultdict(list)
    for item in items:
        for slot in source_item_slots(item):
            if slot=='offhand':continue  # Arms 2H; unrestricted offhand evaluated in other roles.
            if slot=='weapon' and item.weapon_hands!=2 and item.slot!='two_hand':continue
            if source_item_l0(item)['unresolved_effects']:continue
            slots[slot].append(item)
    incumbent={slot:int(v['item_id']) for slot,v in baseline_gear.slots.items()}
    # Top role prior plus one per stat axis for diversity; all items have L0.
    proposals=[]
    for slot,candidates in sorted(slots.items()):
        ranked=sorted(candidates,key=lambda x:(-item_score(x,weights),x.item_id))
        chosen=[];seen=set()
        def add(item):
            if item.item_id not in seen and item.item_id!=incumbent.get(slot):
                seen.add(item.item_id);chosen.append(item)
        for item in ranked[:max_per_slot]:add(item)
        for stat in ('strength','agility','stamina','attack_power','armor','weapon_dps'):
            if len(chosen)>=max_per_slot+3:break
            for item in sorted(candidates,key=lambda x:(-float(getattr(x,stat,0) or 0),x.item_id))[:1]:add(item)
        for item in chosen[:max_per_slot+3]:proposals.append((slot,item))
    results=[];complete=0;paid_events=baseline['events']
    for idx,(slot,item) in enumerate(proposals,1):
        started_one=time.perf_counter();cpu_one=time.process_time()
        row={'slot':slot,'item_id':item.item_id,'source_url':item.source_url,
             'name':item.name,'swaps':{slot:item.item_id},'unresolved_effects':[]}
        try:
            with gear_overrides({slot:item.item_id}):
                selection=select_named_gear(class_key='warrior',level=30,role=role,stat_weights=weights,
                    required_level_policy='observed',exclude_unknown_item_effects=True)
            selected={k:int(v['item_id']) for k,v in selection.slots.items()}
            if selected.get(slot)!=item.item_id:raise ValueError('OVERRIDE_NOT_APPLIED')
            row['result']=eval_selection(ir,selection)
        except (ValueError,KeyError,RuntimeError) as exc:
            row['result']={'status':'BLOCKED_SOURCE_LEGAL_OR_RUNTIME','reason':str(exc)[:250]}
        row['paid_wall_s']=time.perf_counter()-started_one
        row['paid_cpu_s']=time.process_time()-cpu_one
        paid_events+=int(row['result'].get('events') or 0)
        complete+=row['result']['status']=='COMPLETE'
        results.append(row)
        if idx%25==0:print('paid',idx,'/',len(proposals),'complete',complete,flush=True)
    stage={'gear_policy_result':{'winner':{'gear':{'slots':baseline_gear.slots}}}}
    model=fit_swap_weights(stage=stage,results=results,baseline_s_per_mob=baseline['mean_s_per_mob'],
        class_key='warrior',level=30)
    # Pair a one-hand weapon when ranking source-legal offhands from the Arms
    # 2H context; this is L0 only until a full offhand package is measured.
    onehand=next((x for x in items if x.slot=='one_hand' and x.weapon_hands!=2 and
                  not source_item_l0(x)['unresolved_effects']),None)
    ranked=rank_all_legal_items_with_proxy(stage=stage,model=model,class_key='warrior',level=30,
        paired_offhand_weapon_id=int(onehand.item_id) if onehand else -1) if model['status'].startswith('MEASURED_') else {}
    slot_report={}
    for slot in sorted(set(slots)|{'offhand'}):
        direct=sorted((r for r in results if r['slot']==slot and r['result']['status']=='COMPLETE'),
            key=lambda r:(r['result']['mean_s_per_mob'],r['item_id']))
        slot_report[slot]={'direct_100mob_complete':len(direct),
            'direct_best5':[{k:v for k,v in r.items() if k in ('item_id','name','source_url','swaps','result')}
                for r in direct[:5]],
            'l0_proxy':ranked.get(slot,{}),
            'incumbent_item_id':incumbent.get(slot),
            'context_status':'ARMS_2H_NO_OFFHAND' if slot=='offhand' else 'PROVISIONAL_SOURCE_FIXED_POLICY_NO_TALENTS'}
    result={'checkpoint':'warrior:L30:unrestricted','scoreboard':'2/148',
        'p1':{'status':'PASS','coverage':'54/54'},'p2':{'status':'PASS','coverage':'117/117'},
        'p3':{'status':'FAIL','provisional_l0':inventory['l0_assessed_count'],
              'provisional_denominator':inventory['legal_item_count'],
              'confirmed_legal_denominator':None,
              'source_membership_verified':inventory['source_membership_verified'],
              'provisional_slots':len(inventory['slot_frontiers']),
              'unknown_effect_items':inventory['unknown_effect_item_count'],
              'reason':'CLASS_1_MEMBERSHIP_UNKNOWN_AND_FULL_21_POINT_CONTEXT_NOT_EXECUTABLE'},
        'p4':{'status':'NOT_RUN'},'p5':{'status':'NOT_RUN'},'p6':{'status':'NOT_RUN'},
        'role':role,'talents':'SOURCE_EMPTY_ONLY_21_POINT_BUILD_NOT_SUPPORTED',
        'policy':'EXISTING_WARRIOR_RAGE_PRIORITY',
        'baseline':baseline,'baseline_gear':baseline_gear.as_dict(),
        'measured':{'attempts':len(results),'complete_100mob':complete,'events':paid_events,
                    'wall_s':time.perf_counter()-started,'cpu_s':time.process_time()-cpu,
                    'unique_gear_sets_attempted':len({tuple(sorted(r['swaps'].items())) for r in results})},
        'model':model,'slots':slot_report,'results':results,
        'source_sha256':{'ability_sqlite':hashlib.sha256(ABILITY.read_bytes()).hexdigest(),
                         'item_sqlite':hashlib.sha256(ITEMS.read_bytes()).hexdigest()},
        'uncertainty':['Class 1 source membership is not yet established; provisional 2951 is not a legal denominator.',
            'No full 21-point Warrior allocation can be applied with current L2 talent coverage.',
            'Warrior action IR contains five executable actions; policy fidelity is incomplete.',
            'Unresolved item effects excluded from paid L2, remain L0 visible.',
            'Measured swaps are local and do not prove optimal gear or global 100-mob optimum.']}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result

if __name__=='__main__':
    r=run();print(json.dumps({'p3':r['p3'],'measured':r['measured'],
        'baseline_s_per_mob':r['baseline']['mean_s_per_mob'],
        'model':{k:v for k,v in r['model'].items() if k not in ('per_item','weights')},
        'direct_slots':{k:v['direct_100mob_complete'] for k,v in r['slots'].items()}},indent=2))
