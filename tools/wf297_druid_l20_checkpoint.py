"""First planned unrestricted milestone: Druid L20. No XP/world-route gate.

Reuse source joint talent×named gear×policy engine and freeze old candidate
as a held-out challenger. Neither candidate is declared globally optimal.
"""
from __future__ import annotations
import argparse, json, sqlite3
from hashlib import sha256
from pathlib import Path
from time import process_time_ns
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from tools.wf282_source_role_heldout_benchmark import frozen_heldout
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_db_scope import ability_source_scope,active_ability_db
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from src.game.gear import apply_gear_selection
from src.v2.source_stateful_budgeted import _make_policy, _condition_from_record
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_prefix import ordered_prefix_executed
from src.game.data.forever.source_indexed_action_coverage import indexed_ability_coverage
from src.version import SOFTWARE_VERSION

JOINT_ARGS={
 'class_key':'druid','level':20,
 'max_evaluations':135,'evaluations_per_talent':45,'initial_search':12,
 'search_per_gear':10,'max_gear_states':2,
 'policy_search_backend':'stateful','stateful_use_l1':False,
 'stateful_search_guarded_continuations':True,
 'stateful_search_mode_paths':True,
 'stateful_family_budget_mode':'measured_balanced',
 'max_event_transitions':16000,'required_level_policy':'observed',
 'gear_role_exploration':True,
 'probe_stats':('agility','strength','stamina'),
 'probe_deltas':(5.0,20.0),'talent_corridor_reserve':3,
}

def run(*, ability_db_path=None):
    with ability_source_scope(ability_db_path):
        return _run_impl()


def _run_impl():
    started=process_time_ns()
    independent=run_source_budgeted_joint_talents(**JOINT_ARGS)
    if independent.get('attempted',0)>JOINT_ARGS['max_evaluations'] or independent.get('event_transitions',0)>JOINT_ARGS['max_event_transitions']:
        raise ValueError('SHARED_SEARCH_BUDGET_VIOLATION')
    winner=independent.get('winner')
    if not winner or not winner['gear_policy_result']['winner'].get('gear'):
        raise ValueError('NO_EVALUATED_NAMED_GEAR_WINNER')
    # Held-out is applied AFTER independent search and shares the same
    # source IR, level, real L2 kill+recovery+survival, and incoming model.
    old=frozen_heldout()
    score=float(winner['score_s_per_mob'])
    # Independent scratch replay of the selected named gear / talent /
    # guarded policy on the SAME production executor, never the search cache.
    source=build_game_ir_slice(class_key='druid',level=20)
    talented,_=apply_talent_selection(source,winner['allocation'],level=20)
    picked=winner['gear_policy_result']['winner']
    gear=picked['gear']
    if any(item.get('required_level_origin')!='observed' or
           int(item['required_level'])>20 for item in gear['slots'].values()):
        raise ValueError('GEAR_LEVEL_NOT_OBSERVED_LEGAL')
    geared,_=apply_gear_selection(talented,aggregate_stats=gear['aggregate_stats'],
        selected_items=tuple(gear['slots'].values()),source='canonical_sqlite_forever_catalogue')
    record=picked['winner']
    policy=_make_policy(geared,record['fallback'],
        guarded_action=record.get('guarded_action'),
        guarded_conditions=tuple(_condition_from_record(g) for g in record.get('guarded_conditions',())))
    verified,execution,details=_policy_combat_evaluation(geared,level=20,
        policy_override=policy,opening_action_ids=tuple(record['prefix']),
        schedule_incoming_attacks=True)
    if (verified is None or execution is None or
        not execution.timeline.target_defeated or
        details.get('actor_survived') is not True or
        not ordered_prefix_executed(execution,record['prefix']) or
        abs(float(verified.seconds_per_mob)-score)>1e-9):
        raise ValueError('NEW_WINNER_INDEPENDENT_L2_REPLAY_FAILED')
    if old['status']!='FULL_L2_VERIFIED':raise ValueError('OLD_CHALLENGER_NOT_FULL_L2')
    coverage=indexed_ability_coverage(build_game_ir_slice(class_key='druid',level=20),class_key='druid',level=20)
    # This is an acceptance gate, not a proxy for source verification.
    # An exact spell-ID match is NOT proof that every effect, acquisition
    # requirement, and current client build is source-authoritative.
    from tools.wf317_first_checkpoint_source_plan import make_plan
    source_plan=make_plan(class_key='druid',level=20,
                          db_path=active_ability_db(DEFAULT_DB))
    missing_verified_html=source_plan['counts']['missing_real_html']
    selected_slots=gear['slots']
    missing_item_routes=[slot for slot,item in selected_slots.items()
                         if item.get('acquisition_route_verified') is not True]
    with sqlite3.connect(active_ability_db(DEFAULT_DB)) as source_db:
        has_external=source_db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_external_rank_observations'").fetchone()
        external_observations=(source_db.execute('SELECT COUNT(*) FROM source_external_rank_observations').fetchone()[0]
                               if has_external else 0)
    completeness=(coverage['unrepresented_rank_count']==0 and
                  missing_verified_html==0 and not missing_item_routes and
                  external_observations==0 and
                  not old['unsupported_gear_stats'] and
                  independent.get('complete_search') is True)
    # Never claim full checkpoint when sources or search breadth are incomplete.
    return {'schema':'wf297_druid_l20_priority_joint_v1',
       'software_version':SOFTWARE_VERSION,'prioritized_case':'druid:L20',
       'current_requirement':'best modeled full kill+recovery+survival s/mob, no XP',
       'acceptance_order':'Druid L20 first; L10 not the first named checkpoint',
       'shared_budget':dict(JOINT_ARGS),'source_db_sha256':sha256(active_ability_db(DEFAULT_DB).read_bytes()).hexdigest(),
       'item_db_sha256':sha256(Path('data/forever/catalogue/items_2026-09-29.sqlite').read_bytes()).hexdigest(),
       'search':independent,'held_out_frozen_feral':old,
       'comparison':{'same_engine_L2':True,'held_out_not_seeded':True,
          'new_score_s_per_mob':score,'old_score_s_per_mob':old['score_s_per_mob'],
          'new_minus_old_s_per_mob':score-old['score_s_per_mob'],
          'new_beats_old':score<old['score_s_per_mob'],
          'winner_independent_scratch_replay_s_per_mob':float(verified.seconds_per_mob),
          'winner_independent_scratch_replay_events':int(details['event_transitions_new']),
          'winner_independent_scratch_replay_kill_s':float(execution.timeline.target_death_s),
          'winner_independent_scratch_replay_recovery_s':float(details['recovery']['total_s']),
          'search_l2_attempts':independent['attempted'],
          'search_executor_events':independent['event_transitions'],
          'old_replay_executor_events':old['events']},
       'source_completeness':{'indexed_rank_count':coverage['at_or_unknown_below_level_count'],
          'rank_count_matched_to_IR':coverage['exact_source_rank_in_ir_count'],
          'unrepresented':coverage['unrepresented_rank_count'],
          'missing_independently_verified_spell_detail_html':missing_verified_html,
          'selected_item_acquisition_routes_unverified':missing_item_routes,
          'external_web_text_observations_not_html_verified':external_observations,
          'full_rank_and_mechanics_and_joint_coverage_proven':False},
       'formal_validated_checkpoint':bool(completeness),
       'bounded_real_L2_comparison_complete':True,
       'wall_or_XP_routes_required':False,
       'new_checkpoint_count':1 if completeness else 0,
       'controller_cpu_ns_including_old_replay':process_time_ns()-started}

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    out=run();args.output.write_text(json.dumps(out,indent=2,default=str)+'\n')
    summary={k:v for k,v in out['comparison'].items() if k not in ('held_out_not_seeded',)}
    print(json.dumps({'comparison':summary,'formal_validated_checkpoint':out['formal_validated_checkpoint'],
         'source_completeness':out['source_completeness']},indent=2))
if __name__=='__main__':main()
