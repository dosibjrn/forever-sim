"""WF245 source-independent, balanced policy + legal local frontier replay."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.wf244_joint_multi_pull_replay import run


def replay(*, allocations=20, screen_gears=1, finalists=1, policy_cap=24,
           refinement_budget=8, refinement_rounds=1):
    result = run(allocations=allocations, screen_gears=screen_gears,
                 finalists=finalists, policy_cap=policy_cap,
                 refinement_budget=refinement_budget,
                 refinement_rounds=refinement_rounds)
    result['version'] = '0.11.48.245'
    result['search_upgrade'] = ('balanced source-policy frontier per mode; '
                                'legal score-directed local talent frontier')
    result['budgets']['refinement_budget'] = refinement_budget
    result['budgets']['refinement_rounds'] = refinement_rounds
    result['budgets']['source_policy_frontier_truncated'] = True
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--allocations', type=int, default=20)
    p.add_argument('--screen-gears', type=int, default=1)
    p.add_argument('--finalists', type=int, default=1)
    p.add_argument('--policy-cap', type=int, default=24)
    p.add_argument('--refinement-budget', type=int, default=8)
    p.add_argument('--refinement-rounds', type=int, default=1)
    p.add_argument('--output', default='WF245_INDEPENDENT_JOINT_REPLAY.json')
    args = p.parse_args()
    result = replay(allocations=args.allocations, screen_gears=args.screen_gears,
        finalists=args.finalists, policy_cap=args.policy_cap,
        refinement_budget=args.refinement_budget, refinement_rounds=args.refinement_rounds)
    Path(args.output).write_text(json.dumps(result, indent=2))
    winner = result['independent_search']['independent_winner']
    print(json.dumps({'winner_s_per_mob': winner['seconds_per_mob'],
                      'winner_talents': winner['talent_allocation'],
                      'winner_gear': winner['gear_id'],
                      'winner_policy': [r['action_id'] for r in winner['best_policy']['policy']['rules']],
                      'old_held_out_s_per_mob': result['held_out_frozen_challenger']['seconds_per_mob'],
                      'evaluated_independent_allocations': result['independent_search']['total_independent_evaluated_allocations']}, indent=2))
