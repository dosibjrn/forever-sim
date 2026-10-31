"""WF276: actual source-IR / production-executor evidence, not synthetic fixtures.

Run from the extracted project root. All outcomes are bounded, not complete
source-fidelity claims. Includes tiny exhaustive real-scorer comparisons.
"""
from __future__ import annotations
import json
from pathlib import Path
from statistics import median
from src.version import SOFTWARE_VERSION
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
from tools.wf261_stateful_benchmark import exhaustive


def run():
    cases = [('druid', 10, 500), ('mage', 20, 700), ('rogue', 20, 700)]
    truth = {}
    ablations = []
    for cls, lvl, event_cap in cases:
        t = exhaustive(cls, lvl)
        truth[f'{cls}_L{lvl}'] = {k: t[k] for k in (
            'evaluated', 'events', 'cpu_ns', 'winner_s_per_mob', 'winner',
            'l0_top_true_s_per_mob', 'l0_top_missed_winner')}
        for label, flags in [
            ('L0_L2', {'use_l0': True, 'use_l1': False}),
            ('L0_L1_L2', {'use_l0': True, 'use_l1': True}),
            ('no_L0_L2', {'use_l0': False, 'use_l1': False}),
            ('L0_L1_L2_cache', {'use_l0': True, 'use_l1': True, 'use_prefix_cache': True}),
        ]:
            samples = [run_source_stateful_budgeted(
                class_key=cls, level=lvl, max_l2_attempts=12,
                max_event_transitions=event_cap, **flags) for _ in range(3)]
            r = samples[0]
            winner = r['winner']
            ablations.append({
                'case': f'{cls}_L{lvl}', 'label': label,
                'event_cap': event_cap, 'status': r['status'],
                'source_actions': r['source_actions'],
                'blocked_source_semantics': r['blocked_source_semantics'],
                'l0_candidates': r['l0_candidates_generated'],
                'l1_attempts': r['l1_attempts'], 'l2_attempts': r['l2_attempts'],
                'l2_evaluated': r['l2_evaluated'],
                'event_transitions': r['event_transitions'],
                'cache_hits_l2': r['cache_hits_l2'],
                'verified_scratch': r['verification_completed'],
                'verification_required': r['verification_required'],
                'verification_complete': r['verification_complete'],
                'cpu_ms_median_3': median(x['total_controller_cpu_ns'] / 1e6 for x in samples),
                'wall_ms_median_3': median(x['total_wall_ns'] / 1e6 for x in samples),
                'best_s_per_mob': winner['score_s_per_mob'] if winner else None,
                'regret_vs_exhaustive_s': (winner['score_s_per_mob'] - t['winner_s_per_mob']) if winner else None,
                'winner_prefix': winner['prefix'] if winner else None,
                'winner_fallback': winner['fallback'] if winner else None,
                'l0_mae_s': sum(abs(x['l0_error_s']) for x in r['predictions']) /
                    len(r['predictions']) if r['predictions'] else None,
                'l1_mae_s': sum(abs(x['l1_error_s']) for x in r['predictions']
                    if x['l1_error_s'] is not None) / max(1, sum(
                    x['l1_error_s'] is not None for x in r['predictions']))
                    if r['predictions'] else None,
            })
    low = run_source_stateful_budgeted(class_key='druid', level=2,
        max_l2_attempts=6, max_event_transitions=400)
    return {
        'software_version': SOFTWARE_VERSION,
        'source': 'existing canonical Forever IR + production generic executor; no new source facts',
        'truth': truth, 'ablations': ablations,
        'druid_L2': {
            'status': low['status'], 'source_actions': low['source_actions'],
            'attempted_l2': low['l2_attempts'],
            'full_failures': [{k: o.get(k) for k in ('prefix','fallback','status','reason',
                'target_hp_remaining','selected_action_count')} for o in low['observations']
                if o.get('tier') == 'L2'],
        },
        'coverage': {
            'validated_class_level_checkpoints': 0,
            'total_required': 540,
            'new_complete_checkpoints': 0,
            'new_canonical_source_facts': 0,
            'new_bounded_executable_canary': 'rogue L20: Sinister Strike resource-mutating weapon action',
            'explicit_blocker': 'Eviscerate AP scaling not normalized; excluded from bounded search',
        },
    }


if __name__ == '__main__':
    result = run()
    out = Path('WF276_REAL_SOURCE_ACTION_BENCHMARK.json')
    out.write_text(json.dumps(result, indent=2, sort_keys=True))
    print('wrote', out)
    for row in result['ablations']:
        print(row['case'], row['label'], row['best_s_per_mob'],
              row['event_transitions'], row['l2_attempts'],
              row['verified_scratch'], round(row['cpu_ms_median_3'], 1))
