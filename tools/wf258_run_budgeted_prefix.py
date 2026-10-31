"""Reproduce WF258 real ordered-prefix budgeted discovery, without fixture seeding.

Usage: python -m tools.wf258_run_budgeted_prefix --budget 32 --output WF258_REAL_REPLAY.json
"""
import argparse
import json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_budgeted_prefix import run_source_budgeted_prefix
from src.v2.source_policy_search import synthesize_source_policies
from src.v2.generic_backend import _policy_combat_evaluation


def run(budget=32):
    r = run_source_budgeted_prefix(class_key='druid', level=10, max_evaluations=budget,
                                   schedule_incoming_attacks=True)
    ir = build_game_ir_slice(class_key='druid',level=10)
    # Historical .233 source-priority winner, held out of the new search.
    # This is a *priority* challenger, not a claimed OG full gear/talent build.
    previous = ('wrath:5177',)
    candidates = synthesize_source_policies(ir,level=10,max_policies=96)['policies']
    matches = [p for p in candidates if tuple(rule.action_id for rule in p.rules) == previous]
    if len(matches) != 1:
        raise ValueError('historical priority challenger unavailable in current IR')
    old, execution, details = _policy_combat_evaluation(
        ir, level=10, policy_override=matches[0],schedule_incoming_attacks=True)
    r['historical_priority_challenger'] = {
        'original_baseline': '.233', 'priority_rules': list(previous),
        'scenario': 'same current L10 naked IR, incoming combat and recovery',
        'evaluated_on_current_runtime': True,
        'seconds_per_mob': None if old is None else old.seconds_per_mob,
        'selected_actions': [dict(x) for x in execution.selected_actions],
        'valid_full_OG_comparison': False,
        'reason': 'Historical .233 priority-only naked actor, not an OG full named gear/talent build.'}
    return r


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--budget',type=int,default=32)
    parser.add_argument('--output',default='WF258_REAL_REPLAY.json')
    args=parser.parse_args()
    result=run(args.budget)
    Path(args.output).write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps({k:result[k] for k in ('status','budget','attempted','evaluated','blocked','seed_count','seed_skipped_by_budget')},indent=2))
    print('winner',result['winner']['score_s_per_mob'] if result['winner'] else None)
    print('challenger',result['historical_priority_challenger']['seconds_per_mob'])
