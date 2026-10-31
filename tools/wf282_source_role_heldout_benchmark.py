"""WF282: source-role exploration vs frozen held-out challenger, ONE real scorer.

No legacy answer is seeded into the optimizer. The held-out candidate is
replayed separately with exact source gear, legal talents and frozen APL.
It is an oracle/challenger, not a proposed optimal policy.
"""
from __future__ import annotations

import json
from pathlib import Path
from time import process_time_ns, monotonic_ns

from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection, validate_talent_selection
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_budgeted_gear import run_source_budgeted_gear
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from tools.wf243_joint_multi_pull_replay import frozen_policy

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'fixtures/wf243_heldout_feral_l20.json'


def frozen_heldout(fixture=None):
    f = dict(fixture or json.loads(FIXTURE.read_text()))
    key, level = str(f['class_key']), int(f['level'])
    source = build_game_ir_slice(class_key=key, level=level)
    validate_talent_selection(source, f['talent_allocation'], level=level)
    gears = _gear_envelope(key, level, max_gear_candidates=256,
                           required_level_policy='observed',
                           include_melee_gear=True, ir_slice=source)
    matched = [g for g in gears if g['id'] == f['gear_id']]
    if len(matched) != 1:
        raise ValueError('frozen held-out gear not unique in observed source envelope')
    gear = matched[0]
    exact = {k: int(v['item_id']) for k,v in gear['selection'].slots.items()}
    expected = {k: int(v['item_id']) for k,v in f['gear_slots'].items()}
    if exact != expected:
        raise ValueError('frozen held-out item IDs do not match observed source envelope')
    # Observed Wowhead listview eligibility != proof that a player can acquire
    # every item at this level. Do not elevate this to a legal leveling route.
    if any(v.get('required_level_origin') != 'observed'
           for v in gear['selection'].slots.values()):
        raise ValueError('frozen challenger has inferred item-level eligibility')
    geared, applied = apply_gear_selection(source,
        aggregate_stats=gear['selection'].aggregate_stats,
        selected_items=tuple(gear['selection'].slots.values()),
        source='canonical_sqlite_forever_catalogue')
    ir, talents = apply_talent_selection(geared, f['talent_allocation'], level=level)
    policy = frozen_policy(f['policy'])
    legal_actions = {a.id for a in ir.actions}
    if any(r.action_id not in legal_actions for r in policy.rules):
        raise ValueError('frozen challenger has unavailable policy action')
    start_cpu, start_wall = process_time_ns(), monotonic_ns()
    result, execution, details = _policy_combat_evaluation(
        ir, level=level, policy_override=policy,
        schedule_incoming_attacks=True)
    cpu_ns, wall_ns = process_time_ns()-start_cpu, monotonic_ns()-start_wall
    if result is None or execution is None or not execution.timeline.target_defeated:
        raise ValueError('frozen challenger did not survive a full real L2 kill')
    return {
        'status':'FULL_L2_VERIFIED',
        'score_s_per_mob':float(result.seconds_per_mob),
        'events':int(details['event_transitions_new']),
        'cpu_ns':cpu_ns, 'wall_ns':wall_ns,
        'gear_id':gear['id'], 'gear_item_ids':exact,
        'talent_allocation':dict(f['talent_allocation']),
        'talent_modifiers':len(talents.applied_modifiers),
        'policy_actions':[r.action_id for r in policy.rules],
        'source_gear_role':gear['selection'].role,
        'observed_required_level_only':True,
        'source_acquisition_route_proven':False,
        'unsupported_gear_stats':dict(applied.unsupported_stats),
        'source_context':'Forever canonical SQLite + generic production scorer',
        'incoming_enabled':True,
        'full_cycle_objective':True,
        'historical_reference_same_scenario':False,
    }


def compact(r):
    return {
        'status':r['status'], 'attempts':r['attempted'],
        'l1_attempts':r['stateful_l1_attempts'],
        'stat_probe_attempts':r['stat_probe_attempts'],
        'events':r['event_transitions'],
        'total_controller_cpu_ns':r['total_controller_cpu_ns'],
        'total_wall_ns':r['total_wall_ns'],
        'stat_probe_cpu_ns':r['stat_probe_cpu_ns'],
        'best_score_s_per_mob':r['winner']['winner']['score_s_per_mob'],
        'gear_roles_evaluated':r['source_roles_evaluated'],
        'role_proposals':r['role_proposal_trace'],
        'stages':[
            {'stage':s['stage'], 'role':(s['gear'] or {}).get('role'),
             'l2_attempts':s['attempted'],
             'score_s_per_mob':(s['winner'] or {}).get('score_s_per_mob'),
             'source_gear_item_ids':({k:v['item_id'] for k,v in s['gear']['slots'].items()}
                                     if s['gear'] else None),
             'family_l2_counts':s['family_l2_counts']}
            for s in r['stages']],
        'score_vs_attempt':r['best_vs_budget'],
        'full_optimum_proven':False,
    }


def run():
    args=dict(class_key='druid', level=20, max_evaluations=110,
        initial_search=24, search_per_gear=16, max_gear_states=3,
        policy_search_backend='stateful', stateful_use_l1=False,
        stateful_search_guarded_continuations=True,
        stateful_search_mode_paths=True,
        stateful_family_budget_mode='measured_balanced',
        probe_stats=('agility','strength','stamina'),
        required_level_policy='observed', max_event_transitions=15000)
    standard = compact(run_source_budgeted_gear(**args,gear_role_exploration=False))
    diverse = compact(run_source_budgeted_gear(**args,gear_role_exploration=True))
    old = frozen_heldout()
    # Separate *oracle-conditioned* diagnostic: hold the old talent allocation
    # fixed, but independently rediscover gear and policy from source singles
    # and ordered pairs. Never count this as independent TALENT discovery.
    base = build_game_ir_slice(class_key='druid', level=20)
    same_talent_ir, _ = apply_talent_selection(base, old['talent_allocation'], level=20)
    conditioned = compact(run_source_budgeted_gear(
        **args, ir_slice=same_talent_ir, gear_role_exploration=True))
    coverage = base.provenance.get('indexed_ability_coverage') or {}
    # Truly independent talent search: starts from the empty allocation,
    # source legal neighbors only, never sees the held-out talent/gear/policy.
    joint_cpu_started, joint_wall_started = process_time_ns(), monotonic_ns()
    independent = run_source_budgeted_joint_talents(
        class_key='druid',level=20,max_evaluations=80,
        evaluations_per_talent=48,initial_search=18,search_per_gear=12,
        max_gear_states=1,policy_search_backend='stateful',
        stateful_use_l1=False,stateful_search_guarded_continuations=True,
        stateful_search_mode_paths=True,
        stateful_family_budget_mode='measured_balanced',
        max_event_transitions=13000,required_level_policy='observed',
        gear_role_exploration=True)
    joint_cpu_ns = process_time_ns()-joint_cpu_started
    joint_wall_ns = monotonic_ns()-joint_wall_started
    independent_row={
        'status':independent['status'],
        'attempts':independent['attempted'],
        'events':independent['event_transitions'],
        'cpu_ns':joint_cpu_ns, 'wall_ns':joint_wall_ns,
        'score_vs_attempt':independent['best_vs_budget'],
        'talent_states_evaluated':independent['talent_states_evaluated'],
        'winning_talents':independent['winner']['allocation'],
        'best_score_s_per_mob':independent['winner']['score_s_per_mob'],
        'required_level_policy':independent['required_level_policy'],
        'heldout_seeded':False,
        'source_legal_talent_frontier':True,
        'source_complete':False,
    }
    return {
        'version':'0.11.48.282',
        'scorer':'src.v2.generic_backend._policy_combat_evaluation',
        'scenario':'Druid L20 representative_hp, incoming enabled, kill+recovery+survival',
        'optimizer_talent_allocation':{},
        'heldout_talent_allocation':old['talent_allocation'],
        'same_scorer_and_scenario':True,
        'same_talent_or_gear_configuration':False,
        'equal_compute_between_gear_ablations':{
            'max_l2_attempts':110,'max_events':15000,
            'actual_l2_attempts_equal':standard['attempts']==diverse['attempts'],
            'actual_event_costs_equal':standard['events']==diverse['events'],
            'cpu_costs_equal':False},
        'standard':standard, 'role_diverse':diverse,
        'frozen_heldout':old,
        'independent_empty_root_talent_gear_policy':independent_row,
        'oracle_conditioned_same_talents_gear_policy_search':conditioned,
        'oracle_conditioned_is_independent_talent_search':False,
        'oracle_conditioned_better_than_frozen_s_per_mob':(
            old['score_s_per_mob']-conditioned['best_score_s_per_mob']),
        'source_action_coverage':coverage,
        'heldout_beats_diverse_by_s_per_mob':diverse['best_score_s_per_mob']-old['score_s_per_mob'],
        'heldout_seeded_into_search':False,
        'source_effects_changed':False,
        'source_complete':False,
        'fully_validated_levels_delta':0,
        'limitations':[
            'observed item eligibility is not acquisition/route proof',
            'old challenger uses 11 talent points; new gear ablations use zero',
            'old challenger is a separately paid L2 and NOT included in gear search budget',
            'oracle-conditioned comparison reuses old TALENTS only, not old gear or policy; cannot establish independent talent discovery',
            'source roles may map to identical physical item sets; no duplicate evaluation',
            'no L1/L3 in this experiment; L0 is an untrusted ranking feature',
            'independent talent search budget reaches only two source-legal talent states',
            'no global optimum or full class×level coverage claim',
        ],
    }


if __name__=='__main__':
    import sys
    report=run()
    out=Path(sys.argv[1] if len(sys.argv)>1 else 'WF282_REAL_HELDOUT_BENCHMARK.json')
    out.write_text(json.dumps(report,indent=2,sort_keys=True,default=str)+'\n')
    print(json.dumps({key:report[key]['best_score_s_per_mob'] for key in ('standard','role_diverse')} |
                     {'heldout':report['frozen_heldout']['score_s_per_mob'],
                      'same_talents_fresh_gear_policy':report['oracle_conditioned_same_talents_gear_policy_search']['best_score_s_per_mob'],
                      'independent_talent_gear_policy':report['independent_empty_root_talent_gear_policy']['best_score_s_per_mob']},indent=2))
