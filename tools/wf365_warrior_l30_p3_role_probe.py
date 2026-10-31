"""Warrior L30 source-legal package smoke and transparent heuristic Top5.

No source-membership proof: all outputs are PROVISIONAL until a genuine class-1
capture is imported. No 30/300-second joint search and no PASS promotion.
"""
from __future__ import annotations
import hashlib,json,os,time
from collections import defaultdict
from pathlib import Path
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0,source_item_slots,source_item_l0
from src.rulesets.forever.items.runtime_selection import (
    available_items,select_gear,item_vector,_source_class_profile,clear_runtime_item_cache
)
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_warrior_l30_gear_provisional_wf365.sqlite'
OUT=ROOT/'evidence/wf365/WF365_WARRIOR_L30_P3_ROLE_PROBE.json'


def run():
    os.environ['FOREVER_ITEM_CATALOGUE']=str(DB)
    clear_runtime_item_cache()
    start=time.perf_counter();cpu=time.process_time()
    inventory=checkpoint_item_l0(class_key='warrior',level=30)
    rows=available_items('warrior',30,required_level_policy='observed')
    roles=_source_class_profile('warrior')['gear_selection_roles']
    byslot=defaultdict(list)
    for i in rows:
        for slot in source_item_slots(i):byslot[slot].append(i)
    role_evidence={}
    for role,config in roles.items():
        weights=config['proxy_weights']
        gear=select_gear('warrior',30,role,required_level_policy='observed',exclude_unknown_item_effects=True)
        sections={}
        role_slots=dict(byslot)
        if config['weapon_package'] in ('dual_wield','best_package'):
            # A source one-hand weapon is a legal Warrior offhand candidate at
            # L30 even though its raw catalogue slot is 'one_hand'.
            role_slots['offhand']=list({i.item_id:i for i in
                list(byslot['offhand'])+[x for x in rows if x.slot=='one_hand']}.values())
        for slot,candidates in sorted(role_slots.items()):
            ranks=[];unresolved=0
            for item in candidates:
                l0=source_item_l0(item)
                if l0['unresolved_effects']:
                    unresolved+=1
                    continue  # UNKNOWN, not zero: separate from known-effect ranking.
                if slot=='offhand':
                    if config['weapon_package']=='two_hand':continue
                    if config['weapon_package']=='one_hand_shield' and item.armor_type!='shield':continue
                    if config['weapon_package']=='dual_wield' and item.slot!='one_hand':continue
                    if item.item_id==gear['weapon'].item_id:continue
                v=item_vector(item)
                parts={stat:round(float(value)*float(weights.get(stat,0)),6)
                       for stat,value in v.items() if value and stat in weights}
                unknown_stats=[stat for stat,value in v.items() if value and stat not in weights]
                ranks.append({'item_id':item.item_id,'name':item.name,'source_url':item.source_url,
                    'heuristic_score':round(sum(parts.values()),6),'stat_contributions':parts,
                    'unweighted_stat_axes':unknown_stats,
                    'proxy_uncertainty':'UNCALIBRATED_ROLE_PRIOR_NOT_COMBATRUNTIME_MARGINAL'})
            ranks.sort(key=lambda x:(-x['heuristic_score'],x['item_id']))
            sections[slot]={'provisional_items':len(candidates),'unresolved_effect_items':unresolved,
                'heuristic_top5':ranks[:5]}
        role_evidence[role]={'weapon_package':config['weapon_package'],'weights':weights,
            'gear':{slot:{'item_id':item.item_id,'name':item.name,
                'source_url':item.source_url} for slot,item in gear.items()},
            'slots':sections,'gear_item_count':len(gear)}
    result={'checkpoint':'warrior:L30:unrestricted','accepted_checkpoints':'2/148',
        'p1':{'status':'PASS','coverage':'54/54','source':'WF361'},
        'p2':{'status':'PASS','coverage':'117/117','source':'WF362'},
        'p3':{'status':'FAIL','reason':'CLASS_1_SOURCE_MEMBERSHIP_UNVERIFIED',
            'legal_denominator':None,'provisional_l0':inventory['l0_assessed_count'],
            'provisional_denominator':inventory['legal_item_count'],
            'provisional_slots':len(inventory['slot_frontiers']),
            'unresolved_effect_items':inventory['unknown_effect_item_count'],
            'provisional_shields':sum(i.armor_type=='shield' for i in rows),
            'source_membership_verified':inventory['source_membership_verified'],
            'role_package_probe':'PROVISIONAL_NOT_BUILD_CALIBRATED'},
        'p4':{'status':'NOT_RUN'},'p5':{'status':'NOT_RUN'},'p6':{'status':'NOT_RUN'},
        'search_wall_cpu_events_attempts_unique_prediction_actual':'NOT_MEASURED',
        'roles':role_evidence,'staged_db_sha256':hashlib.sha256(DB.read_bytes()).hexdigest(),
        'probe_wall_s':time.perf_counter()-start,'probe_cpu_s':time.process_time()-cpu,
        'limitations':['Cross-class provisional membership is not proof of Warrior usability',
            'Shields are recovered from Paladin source rows only as Warrior-proficiency candidates',
            'Heuristic role priors are not measured 100-mob stat weights; cannot certify Top5',
            'Unknown item effects excluded from role ranking, never assigned zero',
            'Unrestricted talent directions remain unrestricted']}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result

if __name__=='__main__':
    r=run();print(json.dumps({'p3':r['p3'],'roles':{k:v['gear_item_count'] for k,v in r['roles'].items()},
        'wall_s':r['probe_wall_s'],'cpu_s':r['probe_cpu_s']},indent=2))
