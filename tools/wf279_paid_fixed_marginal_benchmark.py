"""WF279: reproducible real L2 talent marginal ablation, no parallel scorer.

Run: python tools/wf279_paid_fixed_marginal_benchmark.py > WF279_REAL_FIXED_TALENT_BENCHMARK.json
The CPU numbers are run-local and cannot be compared to other machines.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from time import process_time_ns, perf_counter_ns

from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.version import SOFTWARE_VERSION


def one(class_key, level, max_attempts, events, measure):
    cpu0,wall0=process_time_ns(),perf_counter_ns()
    r=run_source_budgeted_joint_talents(class_key=class_key,level=level,
        max_evaluations=max_attempts,evaluations_per_talent=max_attempts//2,
        initial_search=20,search_per_gear=8,max_gear_states=2,
        policy_search_backend='stateful',max_event_transitions=events,
        stateful_use_l1=False,stateful_search_guarded_continuations=True,
        measure_parent_fixed_policy=measure)
    return {'class_key':class_key,'level':level,'paid_fixed_marginal':measure,
        'budget_l2_attempts':max_attempts,'budget_event_transitions':events,
        'attempts':r['attempted'],'evaluated':r['evaluated'],'blocked':r['blocked'],
        'event_transitions':r['event_transitions'],
        'cpu_ns':process_time_ns()-cpu0,'wall_ns':perf_counter_ns()-wall0,
        'fixed_policy_attempts':r['fixed_policy_attempts'],
        'fixed_policy_events':r['fixed_policy_event_transitions'],
        'fixed_policy_cpu_ns':r['fixed_policy_cpu_ns'],
        'winner_score_s_per_mob':r['winner']['score_s_per_mob'] if r['winner'] else None,
        'winner_talent_allocation':r['winner']['allocation'] if r['winner'] else None,
        'best_vs_attempt':r['best_vs_budget'],
        'stages':[{'allocation':s['allocation'],'attempted':s['attempted'],
            'events_nested':s['event_transitions'],
            'reoptimized_s_per_mob':s['score_s_per_mob'],
            'reoptimized_marginal_s_per_mob':s['reoptimized_marginal_s_per_mob'],
            'fixed_s_per_mob':(s['parent_fixed_policy_marginal'] or {}).get('score_s_per_mob'),
            'fixed_marginal_s_per_mob':(s['parent_fixed_policy_marginal'] or {}).get('fixed_policy_delta_s_per_mob'),
            'fixed_events':(s['parent_fixed_policy_marginal'] or {}).get('event_transitions',0),
            'named_gear_count':s['gear_policy_result'].get('named_gear_states_evaluated',0)}
            for s in r['stages'] if s.get('gear_policy_result')],
        'complete_search':r['complete_search']}


def main():
    rows=[]
    for level,budget,events in ((10,110,6000),(20,110,9000)):
        for measure in (False,True):
            rows.append(one('druid',level,budget,events,measure))
    result={'software_version':SOFTWARE_VERSION,
        'runtime':'src.v2.source_budgeted_joint_talents -> source_budgeted_gear -> source_stateful_budgeted / _fixed_opening_score -> _policy_combat_evaluation',
        'source':'canonical Forever IR and named gear catalogue',
        'objective':'actual full combat + recovery + survival; not a proxy',
        'L0':'existing source stateful controller, unchanged',
        'L1':'disabled for these gear/talent ablations; no new L1 evidence',
        'L2':'all fixed probes paid real executor L2; reoptimized stage uses same executor',
        'L3':'not used',
        'claim':'fixed-policy talent marginal and gear/policy reoptimized marginal separately measured, not global optimum',
        'cases':rows}
    print(json.dumps(result,indent=2,sort_keys=True,default=str))

if __name__=='__main__':
    main()
