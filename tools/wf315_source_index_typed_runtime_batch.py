"""Source-index-wide L1 runtime batch, reusing source atom ledger + CombatRuntime.

No class, spell, item, talent or rank whitelist. Every failure is a coverage
blocker, never silently dropped. This is NOT L2, a legal learned spell or a
validated class-level checkpoint; bounded actor templates are explicit proxies.
"""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
from pathlib import Path
import argparse
import json
import sqlite3
from time import process_time_ns

from src.game.data.forever.registry import registered_class_keys
from src.game.data.forever.source_partial_l1 import (
    bounded_actor_l1_probe_ir, probe_l1_source_fragment)

KINDS={
    'weapon_damage_plus':'weapon_flat_bonus',
    'weapon_multiplier_plus':'weapon_flat_bonus',
    'actor_attack_power_increase':'actor_attack_power_aura',
    'target_armor_reduction':'target_armor_debuff',
}


def measure(db_path:Path,*,level:int)->dict:
    if not 1<=level<=60:raise ValueError('INVALID_LEVEL')
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        rows=db.execute('''SELECT a.class_key,a.spell_id,a.kind,i.level_hint
          FROM ability_effect_atom_observations a JOIN spell_index i
          ON i.class_key=a.class_key AND i.spell_id=a.spell_id AND i.kind='abilities'
          WHERE a.kind IN (?,?,?,?) AND i.level_hint<=?
          ORDER BY a.class_key,a.spell_id''',(*KINDS,level)).fetchall()
    started=process_time_ns()
    done=[];blocked=[];events=0;counts=Counter();byclass=Counter();proxies=0
    for cl in registered_class_keys():
        subset=[r for r in rows if r[0]==cl]
        if not subset:continue
        try: ir,template,proxy=bounded_actor_l1_probe_ir(class_key=cl,level=level,db_path=db_path)
        except (ValueError,RuntimeError) as exc:
            blocked.extend({'class_key':cl,'spell_id':sid,'source_kind':kind,
                            'blocker':'ACTOR_TEMPLATE:'+str(exc)} for _,sid,kind,_ in subset)
            continue
        for _,sid,kind,_ in subset:
            try:
                r=probe_l1_source_fragment(ir,class_key=cl,spell_id=sid,
                    fragment_kind=KINDS[kind],db_path=db_path)
            except (ValueError,RuntimeError,NotImplementedError) as exc:
                blocked.append({'class_key':cl,'spell_id':sid,'source_kind':kind,
                                'blocker':str(exc)})
                continue
            events+=int(r['events']);counts[kind]+=1;byclass[cl]+=1;proxies+=int(proxy)
            done.append({'class_key':cl,'spell_id':sid,'source_kind':kind,
                         'runtime_events':r['events'],
                         'actor_template_level':template,'bounded_actor_proxy':proxy,
                         'source_authority':r['source_authority'],
                         'base_damage_observed':r['base_damage_observed'],
                         'actor_ap_delta':r['l1_actor_attack_power_delta'],
                         'target_armor_delta':r['l1_target_armor_delta'],
                         'weapon_flat_bonus':r['l1_weapon_flat_bonus']})
    return {'level':level,'indexed_candidates':len(rows),'l1_executed':len(done),
        'l1_blocked':len(blocked),'l1_runtime_events':events,
        'l1_cpu_s':(process_time_ns()-started)/1e9,
        'l1_bounded_actor_proxies':proxies,'executed_by_kind':dict(counts),
        'executed_by_class':dict(byclass),'blocker_counts':dict(Counter(x['blocker'] for x in blocked)),
        'executed':done,'blocked':blocked,
        'canonical_source_db_sha256':sha256(db_path.read_bytes()).hexdigest(),
        'source_detail_pages_new':0,'l2_source_complete_promotions':0,
        'accepted_checkpoints':0,'verified_world_routes':0,
        'warning':'Canonical index-change partial fragments only. No complete spell semantics, acquisition, gear, GCD or target legality.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True)
    p.add_argument('--level',type=int,default=60);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();r=measure(args.db,level=args.level)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print({k:v for k,v in r.items() if k not in ('executed','blocked','canonical_source_db_sha256')})
