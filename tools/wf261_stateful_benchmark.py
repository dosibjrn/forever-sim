"""Real Forever Druid L10 benchmark and equal event-budget ablations."""
from __future__ import annotations
import json
from itertools import product
from pathlib import Path
from time import process_time_ns
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_stateful_budgeted import _make_policy, _l0_proxy, _unsafe_semantics, run_source_stateful_budgeted
from src.v2.source_budgeted_prefix import source_prefix_envelope, PrefixCandidate


def exhaustive(class_key='druid', level=10):
    ir = build_game_ir_slice(class_key=class_key, level=level)
    envelope = source_prefix_envelope(ir, level=level)
    amap = {a.id: a for a in ir.actions}
    actions = tuple(a for a in envelope['actions'] if not _unsafe_semantics(amap[a]))
    fillers = tuple(a for a in envelope['fillers'] if a in actions)
    prefixes = [(a,) for a in actions] + list(product(actions, repeat=2))
    start = process_time_ns()
    trials = []
    events = 0
    for prefix in prefixes:
        for fallback in fillers:
            score, execution, details = _policy_combat_evaluation(
                ir, level=level, policy_override=_make_policy(ir, fallback),
                opening_action_ids=tuple(prefix), schedule_incoming_attacks=True)
            events += details['event_transitions_new']
            trials.append({'prefix': list(prefix), 'fallback': fallback,
                           'score_s_per_mob': score.seconds_per_mob if score is not None else None,
                           'events': details['event_transitions_new'],
                           'reason': details.get('stop_reason')})
    valid = [x for x in trials if x['score_s_per_mob'] is not None]
    winner = min(valid, key=lambda x: x['score_s_per_mob'])
    predicted_best = min((PrefixCandidate(tuple(x['prefix']), x['fallback']) for x in trials),
                         key=lambda c: _l0_proxy(c, amap, ir, level)['predicted_s'])
    predicted_true = next((x['score_s_per_mob'] for x in trials if
                           tuple(x['prefix']) == predicted_best.prefix and x['fallback'] == predicted_best.fallback), None)
    return {'evaluated': len(trials), 'events': events, 'cpu_ns': process_time_ns() - start,
            'winner_s_per_mob': winner['score_s_per_mob'], 'winner': winner,
            'l0_top_prefix': list(predicted_best.prefix), 'l0_top_fallback': predicted_best.fallback,
            'l0_top_true_s_per_mob': predicted_true,
            'l0_top_missed_winner': predicted_true != winner['score_s_per_mob'],
            'trials': trials}


def run():
    truth = exhaustive()
    mage_truth = exhaustive('mage', 20)
    runs = []
    for event_cap in (100, 300, 600, 1000):
        for name, flags in [('adaptive_full',{}), ('no_l0',{'use_l0':False}),
                            ('no_l1',{'use_l1':False}),
                            ('no_cache',{'use_prefix_cache':False})]:
            r = run_source_stateful_budgeted(class_key='druid', level=10,
                    max_l2_attempts=24, max_event_transitions=event_cap, **flags)
            best = r['winner']['score_s_per_mob'] if r['winner'] else None
            runs.append({'name': name, 'event_cap': event_cap,
                         'best_s_per_mob': best, 'regret_s_per_mob': best - truth['winner_s_per_mob'] if best else None,
                         'event_transitions': r['event_transitions'], 'l1_attempts': r['l1_attempts'],
                         'l2_attempts': r['l2_attempts'], 'l2_evaluated': r['l2_evaluated'],
                         'blocked': r['blocked_or_aborted'],
                         'cache_hits_l2': r['cache_hits_l2'], 'cache_entries': r['cache_entries'],
                         'cpu_ns': r['total_controller_cpu_ns'],
                         'winner_prefix': r['winner']['prefix'] if r['winner'] else None,
                         'runner_up_s_per_mob': r['runner_up']['score_s_per_mob'] if r['runner_up'] else None,
                         'prediction_l0_mae_s': sum(abs(x['l0_error_s']) for x in r['predictions']) / len(r['predictions']) if r['predictions'] else None,
                         'prediction_l1_mae_s': sum(abs(x['l1_error_s']) for x in r['predictions'] if x['l1_error_s'] is not None) / max(1, sum(x['l1_error_s'] is not None for x in r['predictions'])) if r['predictions'] else None})
    mage = run_source_stateful_budgeted(class_key='mage',level=20,max_l2_attempts=8)
    druid2 = run_source_stateful_budgeted(class_key='druid',level=2,max_l2_attempts=6)
    return {'source_ir': 'forever:druid:caster-healing-slice@10',
            'exhaustive_tiny_source_legal': truth, 'exhaustive_mage_l20': mage_truth,
            'equal_event_budget_ablations': runs,
            'mage_l20': {'winner': mage['winner'], 'l2_attempts': mage['l2_attempts'],
                         'events': mage['event_transitions'], 'blocked': mage['blocked_or_aborted']},
            'druid_l2': {'status': druid2['status'], 'l2_attempts': druid2.get('l2_attempts'),
                         'source_actions': druid2.get('source_actions'),
                         'blocked': druid2.get('blocked_or_aborted'),
                         'events': druid2.get('event_transitions'),
                         'failures': [x for x in druid2.get('observations',[]) if x.get('tier') == 'L2']}}

if __name__ == '__main__':
    result = run()
    Path('WF261_STATEFUL_REAL_BENCHMARK.json').write_text(json.dumps(result, indent=2, sort_keys=True))
    print('truth',result['exhaustive_tiny_source_legal']['winner_s_per_mob'])
    print('mage truth',result['exhaustive_mage_l20']['winner_s_per_mob'], 'L0 missed',result['exhaustive_mage_l20']['l0_top_missed_winner'])
    for x in result['equal_event_budget_ablations']:
        print(x['event_cap'],x['name'],x['best_s_per_mob'],x['event_transitions'],x['l2_attempts'],x['l2_evaluated'],round(x['cpu_ns']/1e6,1),'ms')
    print('mage',result['mage_l20']['winner'] and result['mage_l20']['winner']['score_s_per_mob'])
    print('druid2',result['druid_l2'])
