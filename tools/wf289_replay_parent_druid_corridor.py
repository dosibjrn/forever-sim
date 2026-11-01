"""Revalidate prior full-point Druid L1–60 winning route on CURRENT native executor.

Held-out reference ONLY: this does not supply its winner to the independent
9-class banked-talent search, nor infer acquisition or objective optimality.
"""
from __future__ import annotations
import json
from pathlib import Path
from time import process_time_ns
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from src.game.level_legality import LevelState, validate_level_state, validate_level_transition
from src.v2.source_stateful_budgeted import _make_policy, source_execution_context
from src.v2.source_budgeted_prefix import ordered_prefix_executed
from src.v2.generic_backend import _policy_combat_evaluation
from src.version import SOFTWARE_VERSION

ROOT=Path(__file__).resolve().parents[1]
PARENT=ROOT/'WF288_RELEASE_DRUID_L1_60_BOUNDED_ROUTE.json'

def replay():
    source=json.loads(PARENT.read_text())
    original=source['bounded_route']
    if [x['level'] for x in original]!=list(range(1,61)):
        raise ValueError('parent reference route incomplete')
    results=[];prev=None;started=process_time_ns()
    for old in original:
        level=old['level']
        ir=build_game_ir_slice(class_key='druid',level=level)
        if ir is None:raise ValueError(f'No current Druid IR L{level}')
        talented,_=apply_talent_selection(ir,old['talents'],level=level)
        policy=_make_policy(talented,old['continuation_fallback'],
                            guarded_action=old.get('guarded_action'))
        observed,execution,details=_policy_combat_evaluation(
            talented,level=level,policy_override=policy,
            opening_action_ids=tuple(old['ordered_prefix']),
            schedule_incoming_attacks=True)
        if (observed is None or execution is None or
            not execution.timeline.target_defeated or
            not ordered_prefix_executed(execution,tuple(old['ordered_prefix']))):
            raise ValueError(f'Parent Druid L{level} did not execute source policy')
        actual=float(observed.seconds_per_mob)
        if abs(actual-float(old['score_s_per_mob']))>1e-9:
            raise ValueError(f'Current Druid L{level} replay different from stored L2')
        actions=tuple(dict.fromkeys((*old['ordered_prefix'],old['continuation_fallback'])))
        state=LevelState('druid',level,ir.actor.metadata.get('race_key'),
                         old['talents'],actions)
        validate_level_state(state)
        transition=validate_level_transition(prev,state) if prev else None
        if (level>=10 and sum(old['talents'].values())!=level-9) or (level<10 and old['talents']):
            raise ValueError('Parent source full talent-point corridor invalid')
        results.append({'level':level,'talents':old['talents'],
           'full_cycle_s_per_mob':actual,'source_context':source_execution_context(talented),
           'policy_prefix':old['ordered_prefix'], 'continuation_fallback':old['continuation_fallback'],
           'guarded_action':old.get('guarded_action'),
           'source_action_ids':list(actions),
           'source_scenario_race':state.race_key,
           'source_legal_transition':transition,
           'scratch_replayed_real_executor':True,
           'real_full_executor_events':int(details.get('event_transitions_total',0))})
        prev=state
    return {'software_version':SOFTWARE_VERSION,'class_key':'druid',
      'authority':'WF288-heldout-reference-replayed-on-WF289-production-executor',
      'status':'EVALUATED_BOUNDED_CONTIGUOUS_SOURCE_SCENARIO',
      'steps':results,'replayed_levels':len(results),
      'sum_event_transitions':sum(r['real_full_executor_events'] for r in results),
      'cpu_ns':process_time_ns()-started,
      'independent_joint_search_performed':False,
      'full_source_complete_checkpoints':0,
      'full_world_legal_leveling_routes':0,
      'gear_acquisition_verified':False,
      'trainer_quest_rune_verified':False,
      'xp_travel_and_resource_carry_verified':False,
      'independent_forever_fidelity_verified':False}

if __name__=='__main__':
    r=replay()
    out=ROOT/'data/forever/wf289_parent_druid_l1_60_replay.json'
    out.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(r['status'],'steps',r['replayed_levels'],'events',r['sum_event_transitions'],'CPU ms',round(r['cpu_ns']/1e6))
