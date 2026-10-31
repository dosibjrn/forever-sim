"""Run a previously discovered sourced policy through the production multi-pull runtime.

Not an optimizer or a new combat engine: this is a held-out continuity gate.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from time import process_time, perf_counter
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection
from src.game.multi_pull import evaluate_repeated_pulls
from src.shared.leveling.objective import representative_hp
from src.v2.source_stateful_budgeted import _make_policy, _condition_from_record

def run(evidence: Path, count: int = 100):
    data=json.loads(evidence.read_text()); win=data['winner']
    cls=data['class_key']; level=int(data['level'])
    ir=build_game_ir_slice(class_key=cls,level=level)
    ir,_=apply_talent_selection(ir,win['allocation'],level=level)
    gear=win['gear_policy_result']['winner']['gear']
    for item in gear['slots'].values():
        if item.get('required_level_origin')!='observed' or int(item['required_level'])>level:
            raise ValueError('BLOCKED_UNVERIFIED_GEAR_LEVEL')
    ir,app=apply_gear_selection(ir,aggregate_stats=gear['aggregate_stats'],
          selected_items=tuple(gear['slots'].values()),source='canonical_sqlite_forever_catalogue')
    if app.unsupported_stats: raise ValueError('BLOCKED_UNSUPPORTED_GEAR_STATS')
    record=win['gear_policy_result']['winner']['winner']
    policy=_make_policy(ir,record['fallback'],guarded_action=record.get('guarded_action'),
             guarded_conditions=tuple(_condition_from_record(x) for x in record.get('guarded_conditions',())))
    start=perf_counter();cpu=process_time()
    result=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=level,
             target_health=float(representative_hp(level)),count=count,
             schedule_incoming_attacks=True,apply_target_defense=True,
             opening_action_ids=tuple(record['prefix']))
    pulls=result.pulls
    return {'class_key':cls,'level':level,'count':count,
            'score_s_per_mob':result.seconds_per_mob,
            'total_s':result.end_time_s-result.start_time_s,
            'single_pull_reference_s_per_mob':win['score_s_per_mob'],
            'first':pulls[0], 'second':pulls[1] if len(pulls)>1 else None,
            'last':pulls[-1],
            'all_defeated':len(pulls)==count,
            'event_transitions':sum(int(p['event_transitions']) for p in pulls),
            'satisfied_mode_entry_skips':sum(len(p['satisfied_mode_opening_ids']) for p in pulls),
            'wall_s':perf_counter()-start,'cpu_s':process_time()-cpu,
            'source_complete':False,'validated_checkpoint':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);p.add_argument('--mobs',type=int,default=100);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=run(a.evidence,a.mobs);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('first','second','last')},indent=2))
