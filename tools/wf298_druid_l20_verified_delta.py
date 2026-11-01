"""Adversarial Druid L20 joint-search validation: blind source search, same scorer,
controlled gear/talent/policy factorial, exact event traces, scratch replay.

The held-out historical fixture is read only AFTER independent optimization.
All counterfactual cells are fresh CombatRuntime executions, not cached scores.
"""
from __future__ import annotations
import argparse, json
from hashlib import sha256
from pathlib import Path
from time import process_time_ns
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from src.game.gear import apply_gear_selection
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_stateful_budgeted import _make_policy, _condition_from_record
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_prefix import ordered_prefix_executed
from tools.wf243_joint_multi_pull_replay import frozen_policy
from tools.wf282_source_role_heldout_benchmark import frozen_heldout
from tools.wf297_druid_l20_checkpoint import JOINT_ARGS

ARGS={**JOINT_ARGS,'max_evaluations':205,'max_event_transitions':22000,
      'post_talent_refinement_budget':70}
ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'fixtures/wf243_heldout_feral_l20.json'

def _trace(execution):
    return [{'time_s':e.time_s,'kind':e.kind,'actor_id':e.actor_id,
             'target_id':e.target_id,'action_id':e.action_id,
             'payload':e.payload} for e in execution.timeline.events]

def _cell(ir, gear, talent, policy_kind, *, policy_record, old_policy):
    talented,_=apply_talent_selection(ir,talent,level=20)
    geared,application=apply_gear_selection(talented,
        aggregate_stats=gear['aggregate_stats'],
        selected_items=tuple(gear['slots'].values()),
        source='canonical_sqlite_forever_catalogue')
    if application.unsupported_stats:
        raise ValueError('UNSUPPORTED_NAMED_GEAR_STATS')
    if policy_kind=='old':
        policy=frozen_policy(old_policy)
        prefix=()
    else:
        policy=_make_policy(geared,policy_record['fallback'],
            guarded_action=policy_record.get('guarded_action'),
            guarded_conditions=tuple(_condition_from_record(c)
                for c in policy_record.get('guarded_conditions',())))
        prefix=tuple(policy_record['prefix'])
    score,execution,details=_policy_combat_evaluation(geared,level=20,
        policy_override=policy,opening_action_ids=prefix,
        schedule_incoming_attacks=True)
    if score is None or execution is None or not execution.timeline.target_defeated or (
            details.get('actor_survived') is not True) or not ordered_prefix_executed(execution,prefix):
        raise ValueError('COUNTERFACTUAL_FULL_L2_FAILED')
    trace=_trace(execution)
    return {'score_s_per_mob':float(score.seconds_per_mob),
        'kill_s':float(execution.timeline.target_death_s),
        'recovery_s':float(details['recovery']['total_s']),
        'events':int(details['event_transitions_new']),
        'trace_sha256':sha256(json.dumps(trace,sort_keys=True,default=str).encode()).hexdigest(),
        'selected_actions':[(a['action_id'],a['start_time_s']) for a in execution.selected_actions],
        'incoming_hits':int(details['incoming_hit_count']),
        'actor_base_stats':{k:float(v) for k,v in geared.actor.base_stats.items()
                            if k in ('strength','agility','stamina','armor','dodge_rating')},
        'gear_applied_stats':dict(application.applied_stats),
        'gear_item_ids':{k:int(v['item_id']) for k,v in gear['slots'].items()},
        'recovery':details['recovery']}

def run():
    started=process_time_ns()
    # No historical fixture or old score enters this optimizer invocation.
    independent=run_source_budgeted_joint_talents(**ARGS)
    winner=independent['winner']
    if winner is None or not winner.get('gear_policy_result'):
        raise ValueError('NO_INDEPENDENT_NAMED_GEAR_WINNER')
    if independent['attempted']>ARGS['max_evaluations'] or independent['event_transitions']>ARGS['max_event_transitions']:
        raise ValueError('SEARCH_BUDGET_EXCEEDED')
    search_cpu=process_time_ns()-started
    # Frozen oracle is intentionally read only AFTER the blind optimizer run.
    fixture=json.loads(FIXTURE.read_text())
    old=frozen_heldout(fixture)
    ir=build_game_ir_slice(class_key='druid',level=20)
    gears=_gear_envelope('druid',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)
    old_gear=next(g['selection'].as_dict() for g in gears if g['id']==fixture['gear_id'])
    new_gear=winner['gear_policy_result']['winner']['gear']
    if {k:v['item_id'] for k,v in old_gear['slots'].items()}!={k:v['item_id'] for k,v in fixture['gear_slots'].items()}:
        raise ValueError('HISTORICAL_GEAR_ID_CHANGED')
    for gear in (old_gear,new_gear):
        if any(v['required_level_origin']!='observed' or int(v['required_level'])>20
               for v in gear['slots'].values()):
            raise ValueError('NAMED_GEAR_LEVEL_ILLEGAL')
    cells={}
    for gear_label,gear in (('old',old_gear),('new',new_gear)):
        for talent_label,talent in (('old',fixture['talent_allocation']),('new',winner['allocation'])):
            for policy_label in ('old','new'):
                key=f'{gear_label}_gear__{talent_label}_talent__{policy_label}_policy'
                cells[key]=_cell(ir,gear,talent,policy_label,
                    policy_record=winner['gear_policy_result']['winner']['winner'],
                    old_policy=fixture['policy'])
    # An identical gear+talent configuration must produce the same objective,
    # ordered actions and exact event trace with either policy representation.
    policy_equivalence={}
    for gear_label in ('old','new'):
        for talent_label in ('old','new'):
            key=f'{gear_label}_gear__{talent_label}_talent'
            a=cells[f'{key}__old_policy'];b=cells[f'{key}__new_policy']
            equal=(abs(a['score_s_per_mob']-b['score_s_per_mob'])<1e-9 and
                   a['selected_actions']==b['selected_actions'] and
                   a['trace_sha256']==b['trace_sha256'])
            policy_equivalence[key]=equal
            if not equal:raise ValueError(f'POLICY_SEMANTIC_MISMATCH:{key}')
    oo=cells['old_gear__old_talent__old_policy']
    nn=cells['new_gear__new_talent__new_policy']
    on=cells['old_gear__new_talent__old_policy']
    no=cells['new_gear__old_talent__old_policy']
    if abs(oo['score_s_per_mob']-old['score_s_per_mob'])>1e-9:
        raise ValueError('OLD_HELDOUT_REPLAY_MISMATCH')
    if abs(nn['score_s_per_mob']-winner['score_s_per_mob'])>1e-9:
        raise ValueError('NEW_SEARCH_WINNER_REPLAY_MISMATCH')
    if not nn['score_s_per_mob']<oo['score_s_per_mob']:
        raise ValueError('NEW_NOT_FASTER_IN_COMMON_L2')
    # Balanced two-factor attribution: averages effects over both contexts.
    gear_effect=((no['score_s_per_mob']-oo['score_s_per_mob'])+
                 (nn['score_s_per_mob']-on['score_s_per_mob']))/2
    talent_effect=((on['score_s_per_mob']-oo['score_s_per_mob'])+
                   (nn['score_s_per_mob']-no['score_s_per_mob']))/2
    delta=nn['score_s_per_mob']-oo['score_s_per_mob']
    if abs(gear_effect+talent_effect-delta)>1e-9:
        raise AssertionError('FACTORIAL_DECOMPOSITION_FAILED')
    return {'schema':'wf298_blind_search_factorial_same_L2_v1',
        'objective':'full L2 kill + recovery + survival s/mob',
        'independent_search_args':ARGS,
        'independent_search_cpu_ns':search_cpu,
        'independent_search_attempts':independent['attempted'],
        'independent_search_events':independent['event_transitions'],
        'independent_search_winner':winner,
        'refinement':independent['post_talent_refinement'],
        'frozen_old':old,
        'new_minus_old_s_per_mob':delta,
        'new_relative_improvement_pct':100*(-delta)/oo['score_s_per_mob'],
        'gear_effect_shapley_s_per_mob':gear_effect,
        'talent_effect_shapley_s_per_mob':talent_effect,
        'policy_effect_s_per_mob':0.,
        'all_four_policy_equivalence_checks':policy_equivalence,
        'factorial_eight_fresh_L2_replays':cells,
        'new_named_gear_item_changes':{
            k:{'old':old_gear['slots'][k]['item_id'],'new':v['item_id']}
            for k,v in new_gear['slots'].items()
            if v['item_id']!=old_gear['slots'][k]['item_id']},
        'heldout_was_not_a_search_seed':True,
        'source_complete':False,'validated_checkpoints_delta':0,
        'total_controller_and_replays_cpu_ns':process_time_ns()-started}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    x=run();a.output.write_text(json.dumps(x,indent=2,default=str)+'\n')
    print(json.dumps({k:x[k] for k in ('new_minus_old_s_per_mob','new_relative_improvement_pct',
        'gear_effect_shapley_s_per_mob','talent_effect_shapley_s_per_mob',
        'policy_effect_s_per_mob','new_named_gear_item_changes',
        'independent_search_attempts','independent_search_events','independent_search_cpu_ns')},indent=2))
