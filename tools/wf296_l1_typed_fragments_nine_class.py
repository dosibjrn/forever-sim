"""Nine-class canonical source atom -> typed IR -> existing CombatRuntime frontier.

This is not L2 legality, not a leveling route and not a source-complete
checkpoint. One run evaluates all supported isolated source effect fragments
with explicit unknown mechanics, no class/spell allowlist or proxy rank.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import process_time_ns

from src.game.data.forever.registry import registered_class_keys, build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_partial_l1 import probe_l1_source_fragment,bounded_actor_l1_probe_ir,PartialSourceEvidenceError

KIND_GROUPS = {
    'school_damage_range':'direct_damage',
    'school_damage_fixed':'direct_damage',
    'healing_range':'direct_heal',
    'resource_gain':'resource_gain',
    'weapon_damage_multiplier':'weapon_multiplier',
    'periodic_school_damage':'periodic_total',
    'periodic_damage':'periodic_total',
}


def measure(level: int, *, db_path: Path = Path(DEFAULT_DB), bounded_actor_l1: bool = False) -> dict:
    if not 1 <= level <= 60:
        raise ValueError('INVALID_LEVEL')
    classes=registered_class_keys()
    if len(classes)!=9:
        raise ValueError('MISSING_SOURCE_CLASS')
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        rows=db.execute('''SELECT DISTINCT a.class_key,a.spell_id,a.kind
            FROM ability_effect_atom_observations a JOIN spell_index i
            ON i.class_key=a.class_key AND i.spell_id=a.spell_id
            WHERE i.level_hint<=? ORDER BY a.class_key,a.spell_id,a.kind''',(level,)).fetchall()
    candidates=sorted(set((cls,int(sid),KIND_GROUPS[kind])
                          for cls,sid,kind in rows if kind in KIND_GROUPS))
    by_class={k:[] for k in classes}
    for cls,sid,kind in candidates:by_class[cls].append((sid,kind))
    started=process_time_ns()
    result={};events=0;completed=0;total_by_kind=Counter();proxy_probes=0
    for cls in classes:
        if bounded_actor_l1:
            ir,template_level,proxy=bounded_actor_l1_probe_ir(
                class_key=cls,level=level,db_path=db_path)
        else:
            ir=build_game_ir_slice(class_key=cls,level=level,ability_db_path=db_path)
            template_level=level;proxy=False
        good=[];blocked=Counter()
        if ir is None and not bounded_actor_l1:
            blocked['MISSING_GAME_IR_AT_SCENARIO_LEVEL']=len(by_class[cls])
        else:
            for sid,kind in by_class[cls]:
                try:
                    r=probe_l1_source_fragment(ir,class_key=cls,spell_id=sid,
                                               fragment_kind=kind,db_path=db_path)
                except PartialSourceEvidenceError as exc:
                    blocked[str(exc)]+=1
                    continue
                good.append({'spell_id':sid,'kind':kind,'events':r['events'],
                             'base_damage':r['base_damage_observed'],
                             'base_healing_requested':r['base_healing_requested'],
                             'base_resource_gain_requested':r['base_resource_gain_requested'],
                             'source_authority':r['source_authority'],
                             'actor_proxy':proxy,'actor_template_level':template_level})
                events+=r['events'];completed+=1;total_by_kind[kind]+=1;proxy_probes+=int(proxy)
        result[cls]={'source_fragment_candidates':len(by_class[cls]),
                     'partial_l1_executed':len(good),
                     'executed_by_kind':dict(Counter(g['kind'] for g in good)),
                     'blocked_reasons':dict(blocked),
                     'examples':good[:3],
                     'all_executed':[{'spell_id':g['spell_id'],'kind':g['kind']} for g in good]}
    return {'level':level,'classes':result,'source_fragment_candidates':len(candidates),
            'partial_l1_executed':completed,'partial_l1_executor_events':events,
            'partial_l1_by_kind':dict(total_by_kind),
            'bounded_actor_l1_probe_enabled':bounded_actor_l1,
            'proxy_actor_rank_probes':proxy_probes,
            'controller_cpu_ns':process_time_ns()-started,
            'canonical_ability_sqlite_sha256':sha256(db_path.read_bytes()).hexdigest(),
            'runtime':'existing_game_CombatRuntime',
            'accepted_class_level_checkpoints':0,'world_continuous_routes':0,
            'l2_source_complete_promotions':0,
            'warning':'L1 isolated fragments only; source-incomplete; periodic total uses ONE terminal proxy tick, NOT actual tick timing; weapon uses qualified proxy; no s/mob or L2 legality'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--level',type=int,default=20)
    parser.add_argument('--bounded-actor-l1',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=measure(args.level,bounded_actor_l1=args.bounded_actor_l1)
    args.output.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in data.items() if k not in ('classes','canonical_ability_sqlite_sha256')},indent=2))
    print({k:(v['partial_l1_executed'],v['source_fragment_candidates']) for k,v in data['classes'].items()})
