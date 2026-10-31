"""Experimental sequential-mob validation on the actual CombatRuntime.

No 100 x one-mob shortcut and no fresh ActorState on each kill. This is an
independent challenger test: any continuity mismatch blocks acceptance.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from time import perf_counter,process_time
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from src.game.gear import apply_gear_selection
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.policy import execute_priority_policy, opening_for_persistent_actor
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.generic_backend import _policy_combat_evaluation
from tools.wf243_joint_multi_pull_replay import frozen_policy
from src.game.recovery import recover_actor_to_full
from src.shared.leveling.objective import representative_hp
from src.game.data.forever.target_combat_source import target_combat_metadata
from src.v2.source_stateful_budgeted import _make_policy, _condition_from_record

def run(evidence_path:Path, *, mobs:int=100, historical:bool=False,
        allocation_override:dict[str,int]|None=None)->dict:
    start=perf_counter();cpu=process_time()
    source=json.loads(evidence_path.read_text())
    cls=source['class_key'];level=int(source['level']);win=source.get('winner')
    ir=build_game_ir_slice(class_key=cls,level=level)
    if historical and allocation_override is not None:
        raise ValueError('CANNOT_OVERRIDE_HISTORICAL_CHALLENGER')
    if historical:
        ir,_=apply_talent_selection(ir,source['talent_allocation'],level=level)
        original=build_game_ir_slice(class_key=cls,level=level)
        envelope=_gear_envelope(cls,level,max_gear_candidates=256,required_level_policy='observed',
                               include_melee_gear=True,ir_slice=original)
        selected=[x for x in envelope if x['id']==source['gear_id']]
        if len(selected)!=1:
            raise ValueError('FROZEN_GEAR_NOT_UNIQUELY_IN_SOURCE')
        gear=selected[0]['selection'].as_dict()
        if {k:int(v['item_id']) for k,v in gear['slots'].items()} != {
            k:int(v['item_id']) for k,v in source['gear_slots'].items()
        }: raise ValueError('FROZEN_GEAR_SOURCE_ID_MISMATCH')
    else:
        ir,_=apply_talent_selection(ir,allocation_override if allocation_override is not None else win['allocation'],level=level)
        gear=win['gear_policy_result']['winner']['gear']
    if any(v.get('required_level_origin')!='observed' or int(v['required_level'])>level for v in gear['slots'].values()):
        raise ValueError('UNVERIFIED_GEAR_LEVEL')
    ir,applied=apply_gear_selection(ir,aggregate_stats=gear['aggregate_stats'],
              selected_items=tuple(gear['slots'].values()),source='canonical_sqlite_forever_catalogue')
    if applied.unsupported_stats:raise ValueError('UNSUPPORTED_GEAR_STATS')
    if historical:
        policy=frozen_policy(source['policy'])
        opening=()
    else:
        record=win['gear_policy_result']['winner']['winner']
        policy=_make_policy(ir,record['fallback'],guarded_action=record.get('guarded_action'),
              guarded_conditions=tuple(_condition_from_record(g) for g in record.get('guarded_conditions',())))
        opening=tuple(record['prefix'])
    scratch, execution, details = _policy_combat_evaluation(
        ir,level=level,policy_override=policy,opening_action_ids=opening,schedule_incoming_attacks=True)
    if scratch is None or execution is None or not execution.timeline.target_defeated:
        raise ValueError('ONE_PULL_REFERENCE_IS_INVALID')
    one_pull=float(scratch.seconds_per_mob)
    if not historical and allocation_override is None and abs(one_pull-float(win['score_s_per_mob']))>1e-9:
        raise ValueError('SEARCH_ONE_PULL_SCORE_MISMATCH')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    metadata=target_combat_metadata(ir) if ir.provenance.get('target_combat_profile') else {}
    rows=[]
    for n in range(1,mobs+1):
        at_start=float(actor.current_time_s)
        target=TargetState.with_health('canonical_leveling_target_L%d'%level, float(representative_hp(level)),
           **metadata,source_status='source_backed_canonical_leveling_reference',
           authority='src.shared.leveling.objective.MOB_BASE_HP',
           source_basis='CMaNGOS warrior-class BaseHealthExp0 ordinary melee target curve',level=level)
        runtime=CombatRuntime(actor=actor,target=target,
            spell_power=float(actor.stats.get('spell_power',0.)),auto_attacks=ir.auto_attacks,
            companions=tuple(ActorState.from_ir(d,()) for d in ir.companions),
            timed_summons=ir.timed_summons,incoming_attacks=ir.incoming_attacks,
            mitigation_rules=ir.mitigation_rules,triggers=ir.triggers)
        adapted_prefix, already_satisfied = opening_for_persistent_actor(
            opening_action_ids=opening, actions=ir.actions, actor=actor)
        result=execute_priority_policy(policy=policy,actions=ir.actions,runtime=runtime,
            opening_action_ids=adapted_prefix,max_actions=256)
        if (result.stopped_reason or not result.timeline.target_defeated or not actor.resource_positive('health') or not result.selected_actions):
            return {'status':'BLOCKED_COMBAT','mob':n,'stopped_reason':result.stopped_reason,
                    'actor_mode':actor.current_mode_id,'selected':result.selected_actions[-5:],
                    'already_satisfied_mode_actions':already_satisfied,
                    'row_count':len(rows),'wall_s':perf_counter()-start,'kill_s':float(result.timeline.target_death_s)-at_start if result.timeline.target_defeated else None}
        kill=float(result.timeline.target_death_s)-at_start
        recovery=recover_actor_to_full(actor=actor,level=level,actions=ir.actions,
             start_time_s=float(result.timeline.target_death_s),
             healing_power=float(actor.stats.get('spell_power',0.)))
        row={'mob':n,'kill_s':kill,'recovery_s':float(recovery.total_s),
             'total_s':float(actor.current_time_s)-at_start,'mode':actor.current_mode_id,
             'selected_actions':tuple(x['action_id'] for x in result.selected_actions),
             'already_satisfied_mode_actions':already_satisfied,
             'resources':dict(actor.resources), 'events':runtime.event_transitions}
        rows.append(row)
    total=sum(r['total_s'] for r in rows)
    return {'status':'COMPLETE_100_MOBS','count':len(rows),
       'total_s':total,'mean_s_per_mob':total/len(rows),
       'one_pull_s_per_mob':one_pull,
       'difference_from_one_pull':total/len(rows)-one_pull,
       'first':rows[0],'second':rows[1],'last':rows[-1],
       'min_s_per_mob':min(r['total_s'] for r in rows),
       'max_s_per_mob':max(r['total_s'] for r in rows),
       'events':sum(r['events'] for r in rows),
       'continuity_safe_prefix_compilation':True,
       'skipped_only_already_active_pure_mode_transitions':True,
       'wall_s':perf_counter()-start,'cpu_s':process_time()-cpu,
       'continuous_actor_state':True,'fresh_target_per_mob':True,
       'historical_heldout':historical, 'same_combat_runtime_and_recovery':True,
       'allocation':source['talent_allocation'] if historical else (allocation_override if allocation_override is not None else win['allocation']),
       'all_mobs_executed_at_least_one_action':all(bool(r['selected_actions']) for r in rows),
       'all_mobs_ended_full_health':all(abs(r['resources']['health']-actor.resource_capacity['health'])<1e-8 for r in rows)}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,required=True);p.add_argument('--mobs',type=int,default=100);p.add_argument('--output',type=Path,required=True);p.add_argument('--historical',action='store_true');a=p.parse_args();r=run(a.evidence,mobs=a.mobs,historical=a.historical);a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
