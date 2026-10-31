"""Measure source-backed partial L1 execution breadth against the existing engine.

NOT checkpoint/route legality. Runs all 9 classes at a level using a common
source-atom discovery query; no spell or class allowlist for actual actions.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import process_time_ns

from src.game.data.forever.registry import registered_class_keys,build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_partial_l1 import probe_l1_source_fragment,PartialSourceEvidenceError


def measure(level:int=20, *,db_path:Path=Path(DEFAULT_DB))->dict:
    if level<1 or level>60:
        raise ValueError('INVALID_LEVEL')
    classes=registered_class_keys()
    if len(classes)!=9:
        raise ValueError('MISSING_SOURCE_CLASS')
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True) as db:
        rows=db.execute('''SELECT a.class_key,a.spell_id FROM ability_effect_atom_observations a
            JOIN spell_index i ON i.class_key=a.class_key AND i.spell_id=a.spell_id
            WHERE a.kind IN ('school_damage_range','school_damage_fixed') AND i.level_hint<=?
            GROUP BY a.class_key,a.spell_id ORDER BY a.class_key,a.spell_id''',(level,)).fetchall()
    eligible={key:[] for key in classes}
    for key,sid in rows:
        eligible[key].append(int(sid))
    started=process_time_ns()
    outcome={}; total_events=0;total_probes=0;total_damage=0.0
    for cls in classes:
        ir=build_game_ir_slice(class_key=cls,level=level,ability_db_path=db_path)
        if ir is None:
            outcome[cls]={'source_range_candidates':len(eligible[cls]),
                'l1_partial_executed':0,
                'blocked_reasons':{'MISSING_GAME_IR_AT_SCENARIO_LEVEL':len(eligible[cls])},
                'samples':[],'all_probed_spell_ids':[],
                'source_ir_at_level':False}
            continue
        accepted=[];blocked=Counter()
        for spell_id in eligible[cls]:
            try:
                result=probe_l1_source_fragment(ir,class_key=cls,spell_id=spell_id,db_path=db_path)
            except PartialSourceEvidenceError as err:
                blocked[str(err)]+=1;continue
            accepted.append({'spell_id':spell_id,'l1_base_damage':result['base_damage_observed'],
                'executor_events':result['events'],'source':result['source_authority']})
            total_events+=result['events'];total_probes+=1;total_damage+=result['base_damage_observed']
        outcome[cls]={'source_range_candidates':len(eligible[cls]),
            'l1_partial_executed':len(accepted),'blocked_reasons':dict(blocked),
            'samples':accepted[:3], 'all_probed_spell_ids':[a['spell_id'] for a in accepted]}
    return {'level':level,'classes':outcome,'partial_l1_attempts':len(rows),
        'partial_l1_completed':total_probes,'partial_l1_executor_events':total_events,
        'partial_l1_base_damage_sum_diagnostic_only':total_damage,
        'controller_cpu_ns':process_time_ns()-started,
        'canonical_ability_sqlite_sha256':sha256(Path(db_path).read_bytes()).hexdigest(),
        'executed_through':'existing_game_CombatRuntime',
        'l2_source_complete_promotions':0,'accepted_class_level_checkpoints':0,
        'world_continuous_routes':0,
        'WARNING':'L1 partial effects omit mechanics; no s/mob, no L2 legality, no optimal policies'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--level',type=int,default=20)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=measure(args.level)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'level':result['level'],'partial_l1_completed':result['partial_l1_completed'],
        'partial_l1_executor_events':result['partial_l1_executor_events'],
        'controller_cpu_ns':result['controller_cpu_ns'],
        'by_class':{k:{'completed':v['l1_partial_executed'],'candidate':v['source_range_candidates'],
                        'blocked':v['blocked_reasons']} for k,v in result['classes'].items()}},indent=2))
