"""Paid source-bound 100-mob Mage L30 stamina sensitivity; NOT a P4 search."""
from __future__ import annotations
from time import perf_counter,process_time
from pathlib import Path
import json,hashlib
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.checkpoint_pipeline import checkpoint_enemy,discover_source_damage_seeds
from src.game.recovery_threshold_search import search_recovery_thresholds
from src.rulesets.forever.items.runtime_selection import available_items,item_payload,item_vector

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_mage_l30_stamina_70374.sqlite'


def run():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DB)
    enemy=checkpoint_enemy(ir=ir,level=30)
    policy=next(p for p in discover_source_damage_seeds(ir,max_actions=3)
                if p.rules[0].action_id=='fire_blast:8412')
    leg=next(x for x in available_items('mage',30,required_level_policy='observed')
             if x.item_id==2277)
    assert leg.stamina==12. and leg.slot=='legs'
    cases=[('naked',{},(),1),('named_legal_legs',item_vector(leg),(item_payload(leg,display_slot='legs'),),1),
           ('naked_two_enemy_pack',{},(),2),
           ('synthetic_160_stamina_two_enemy_pack',{'stamina':160.},(),2)]
    results=[]
    for label,stats,items,pack in cases:
        geared,application=apply_gear_selection(ir,aggregate_stats=stats,selected_items=items,db_path=DB)
        hp=next(x for x in geared.resources if x.id=='health')
        t,c=perf_counter(),process_time()
        result=search_recovery_thresholds(ir_slice=geared,policy=policy,level=30,
            target_health=enemy.hp,count=100,pack_size=pack,
            schedule_incoming_attacks=True,apply_target_defense=True,
            health_fractions=(.5,),mana_fractions=(.1,))
        wall,cpu=perf_counter()-t,process_time()-c
        best=result.get('best')
        results.append({'case':label,'gear':{'stamina':stats.get('stamina',0.),
            'source_item_ids':[x['item_id'] for x in items],
            'applied':application.applied_stats,'unsupported':application.unsupported_stats},
            'player_hp':hp.capacity,'pack_size':pack,'enemy_hp':enemy.hp,
            'status':result['status'],'100mob_completed':bool(best and best['mobs_killed']==100),
            's_per_mob':best['seconds_per_mob'] if best else None,
            'events':best['event_transitions'] if best else None,
            'recovery_s':best['recovery_s'] if best else None,
            'wall_s':wall,'cpu_s':cpu})
    return {'scenario':'Mage L30 unrestricted diagnostic, NOT joint gear×talent×APL search',
        'source_db_sha256':hashlib.sha256(DB.read_bytes()).hexdigest(),
        'enemy':enemy.as_dict(),'policy':[r.action_id for r in policy.rules],
        'cases':results,'assumption':'unknown naked Mage Stamina >=20; synthetic +160 is NOT a legal item build'}

if __name__=='__main__':
    print(json.dumps(run(),indent=2))
