"""Source-backed real executor benchmark; no alternate scorer or fixtures."""
from __future__ import annotations
import json
from itertools import product
from pathlib import Path
from statistics import median
from time import process_time_ns, monotonic_ns

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_budgeted_prefix import PrefixCandidate, source_prefix_envelope
from src.v2.source_stateful_budgeted import (
    _guarded_continuations, _make_policy, _unsafe_semantics, run_source_stateful_budgeted,
)
from src.version import SOFTWARE_VERSION


def exhaustive_real_seed_grid(ir, level):
    env = source_prefix_envelope(ir, level=level)
    action_map = {a.id: a for a in ir.actions}
    actions = tuple(a for a in env['actions'] if not _unsafe_semantics(action_map[a]))
    fillers = tuple(f for f in env['fillers'] if f in actions)
    choices = _guarded_continuations(ir, actions, fillers)
    candidates = [PrefixCandidate(tuple(p), f, a, guards)
                  for p in ([(x,) for x in actions] + list(product(actions, repeat=2)))
                  for f in fillers for a, guards in choices]
    rows = []
    cumulative = 0
    cpu_total = 0
    best = None
    for c in candidates:
        start = process_time_ns()
        result, execution, details = _policy_combat_evaluation(
            ir, level=level, policy_override=_make_policy(ir, c.fallback,
                guarded_action=c.guarded_action, guarded_conditions=c.guarded_conditions),
            opening_action_ids=c.prefix, schedule_incoming_attacks=True)
        cpu = process_time_ns() - start
        events = int(details['event_transitions_new'])
        cumulative += events
        cpu_total += cpu
        score = float(result.seconds_per_mob) if result is not None else None
        if score is not None:
            best = min(best, score) if best is not None else score
        rows.append({'prefix': list(c.prefix), 'fallback': c.fallback,
                     'guarded_action': c.guarded_action,
                     'guarded_conditions': [g.as_dict() for g in c.guarded_conditions],
                     'status': 'FULL_L2_VERIFIED' if score is not None else 'BLOCKED_NO_KILL',
                     'score_s_per_mob': score, 'events': events, 'cpu_ns': cpu,
                     'cumulative_events': cumulative, 'best_s_per_mob': best})
    return {'count': len(rows), 'events': cumulative, 'cpu_ns': cpu_total,
            'best_s_per_mob': best, 'rows': rows}


def summarize_run(**kwargs):
    r = run_source_stateful_budgeted(class_key='druid', level=10, **kwargs)
    paired = [x for x in r['observations'] if x['tier'] == 'L2' and
              x.get('status') == 'FULL_L2_VERIFIED']
    guarded = [x for x in paired if x.get('guarded_action')]
    return {'options': kwargs, 'status': r['status'],
            'best_s_per_mob': r['winner']['score_s_per_mob'] if r['winner'] else None,
            'winner_prefix': r['winner']['prefix'] if r['winner'] else None,
            'winner_guarded_action': r['winner'].get('guarded_action') if r['winner'] else None,
            'seed_count': r['seed_count'], 'seed_unattempted': r['seed_unattempted'],
            'l0_candidates_generated': r['l0_candidates_generated'],
            'l1_attempts': r['l1_attempts'], 'l2_attempts': r['l2_attempts'],
            'l2_successful': r['l2_evaluated'], 'guarded_l2_successful': len(guarded),
            'event_transitions': r['event_transitions'],
            'controller_cpu_ns': r['total_controller_cpu_ns'],
            'full_run_cpu_ns': r['full_run_cpu_ns'],
            'full_run_wall_ns': r['full_run_wall_ns'],
            'verification_complete': r['verification_complete'],
            'scratch_verification': r['scratch_verification'],
            'l1_value_evidence': r['l1_value_evidence'],
            'l0_vs_l2': [{'prefix': x['prefix'], 'guarded_action': x.get('guarded_action'),
                          'predicted': x['l0_predicted_s'],
                          'actual': x['score_s_per_mob']} for x in paired],
            'score_vs_compute': [x for x in r['observations'] if x['tier'] == 'progress'],
            'blocked_source_semantics': r['blocked_source_semantics']}


def main():
    ir = build_game_ir_slice(class_key='druid', level=10)
    full = exhaustive_real_seed_grid(ir, 10)
    common = dict(max_l2_attempts=20, max_event_transitions=1800,
                  search_guarded_continuations=True)
    modes = {
        'adaptive_l0_no_l1_no_cache': dict(use_l0=True, use_l1=False, use_prefix_cache=False),
        'no_l0_no_l1_no_cache': dict(use_l0=False, use_l1=False, use_prefix_cache=False),
        'adaptive_l0_l1_no_cache': dict(use_l0=True, use_l1=True, use_prefix_cache=False),
        'adaptive_l0_no_l1_cache': dict(use_l0=True, use_l1=False, use_prefix_cache=True),
        'adaptive_l0_l1_cache': dict(use_l0=True, use_l1=True, use_prefix_cache=True),
    }
    results = {k: summarize_run(**common, **v) for k, v in modes.items()}
    rogue = run_source_stateful_budgeted(class_key='rogue', level=20,
        max_l2_attempts=8, max_event_transitions=700, use_l1=False,
        search_guarded_continuations=True)
    druid_l2 = run_source_stateful_budgeted(class_key='druid', level=2,
        max_l2_attempts=6, max_event_transitions=500, use_l1=False,
        search_guarded_continuations=True)
    output = {'engine': SOFTWARE_VERSION,
        'source': 'canonical Game IR / Forever Wowhead; no source data mutation',
        'objective': 'production full kill + recovery + survival, incoming attacks enabled',
        'exhaustive_tiny_druid_L10_source_seeds': full,
        'same_event_and_attempt_caps_comparisons': results,
        'rogue_L20_real_unresolved_finisher': {
            'source_actions': rogue['source_actions'],
            'blocked': rogue['blocked_source_semantics'],
            'guarded_options': rogue['guarded_continuation_options'],
            'winner': rogue['winner']['score_s_per_mob'] if rogue['winner'] else None,
            'events': rogue['event_transitions']},
        'druid_L2_real_failure': {
            'status': druid_l2['status'], 'attempts': druid_l2.get('l2_attempts'),
            'events': druid_l2.get('event_transitions'),
            'failures': [x for x in druid_l2.get('observations', [])
                         if x['tier'] == 'L2']},
        'limitations': ['exhaustive is only a tiny L10 source seed grid, not L1-60',
                        'guarded continuation L0 proxy does not model guarded action',
                        'no claim of CPU speedup without paired repeat measurements',
                        'Rogue Eviscerate AP coefficient remains unknown and excluded']}
    Path('WF277_REAL_GUARDED_SOURCE_BENCHMARK.json').write_text(
        json.dumps(output, indent=2, ensure_ascii=False))
    print(json.dumps({
        'exhaustive': {k:v for k,v in full.items() if k != 'rows'},
        'ablations': {k: {x:v for x,v in r.items() if x in (
            'status','best_s_per_mob','l1_attempts','l2_attempts','event_transitions',
            'full_run_cpu_ns','guarded_l2_successful','verification_complete')}
            for k,r in results.items()},
        'rogue_blocked': rogue['blocked_source_semantics'],
        'druid_l2': druid_l2['status']}, indent=2))


if __name__ == '__main__': main()
