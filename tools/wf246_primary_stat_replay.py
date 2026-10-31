"""Repeat the existing source-independent joint search on sourced primary stats.

No alternative scorer or guide seeds. The held-out Feral is replayed only
*after* the independent winner has been chosen by the generic search.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.wf245_joint_frontier_replay import replay


def run():
    result = replay(allocations=20, screen_gears=1, finalists=1,
                    policy_cap=24, refinement_budget=8, refinement_rounds=1)
    result['version'] = '0.11.48.246'
    result['search_upgrade'] = ('unchanged .245 balanced frontier; canonical source '
        'STR->AP, AGI->melee crit/Dodge, gear STA->HP now execute in shared '
        'actor/gear/talent/combat/recovery scorer')
    result['source_stat_capture'] = 'wf246_primary_stats_20261011'
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', default='WF246_PRIMARY_STATS_JOINT_REPLAY.json')
    args = p.parse_args()
    result = run()
    Path(args.output).write_text(json.dumps(result, indent=2))
    winner = result['independent_search']['independent_winner']
    print(json.dumps({
        'winner_s_per_mob': winner['seconds_per_mob'],
        'winner_talents': winner['talent_allocation'],
        'winner_gear': winner['gear_id'],
        'winner_policy': [r['action_id'] for r in winner['best_policy']['policy']['rules']],
        'held_out_frozen_feral_s_per_mob': result['held_out_frozen_challenger']['seconds_per_mob'],
        'independent_allocations_evaluated': result['independent_search']['total_independent_evaluated_allocations'],
    }, indent=2))
