"""W248: independent source-legal on-demand scored beam, exact old Feral replay."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_multi_pull_joint import search_joint_repeated_pulls, replay_exact_challenger
from tools.wf243_joint_multi_pull_replay import frozen_policy


def replay(*, max_allocations=36, screen_gears=2, finalists=1, policy_cap=8, beam_width=1):
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads((root/'fixtures/wf243_heldout_feral_l20.json').read_text())
    key, level = fixture['class_key'], fixture['level']
    search = search_joint_repeated_pulls(
        class_key=key, level=level, max_allocations=max_allocations,
        screening_gear_count=screen_gears, finalists=finalists,
        policy_cap=policy_cap, beam_width=beam_width, strategy='beam',
        held_out_allocation=fixture['talent_allocation'], pulls=3)
    ir = build_game_ir_slice(class_key=key, level=level)
    gears = _gear_envelope(key, level, max_gear_candidates=256,
        required_level_policy='observed', include_melee_gear=True, ir_slice=ir)
    matched = [g for g in gears if g['id'] == fixture['gear_id']]
    if len(matched) != 1:
        raise ValueError('held-out gear not unique in canonical source envelope')
    old = replay_exact_challenger(
        class_key=key, level=level, gear=matched[0],
        allocation=fixture['talent_allocation'], policy=frozen_policy(fixture['policy']),
        pulls=3, post_combat_action_ids=(fixture['policy']['provenance']['exit_action_id'],))
    winner = search['independent_winner']
    return {'version': '0.11.48.248', 'status': 'EVALUATED_BOUNDED',
            'independent_search': search, 'held_out_frozen_feral': old,
            'same_engine_and_objective': True,
            'old_build_actually_evaluated': bool(old['seconds_per_mob'] > 0),
            'held_out_not_seeded': search['held_out_not_sampled'],
            'delta_new_minus_old_s_per_mob': winner['seconds_per_mob']-old['seconds_per_mob'],
            'global_optimum_proven': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-allocations', type=int, default=36)
    parser.add_argument('--screen-gears', type=int, default=2)
    parser.add_argument('--finalists', type=int, default=1)
    parser.add_argument('--policy-cap', type=int, default=8)
    parser.add_argument('--beam-width', type=int, default=1)
    parser.add_argument('--output', default='WF248_SOURCE_LEGAL_BEAM_REPLAY.json')
    args = parser.parse_args()
    result = replay(max_allocations=args.max_allocations, screen_gears=args.screen_gears,
                    finalists=args.finalists, policy_cap=args.policy_cap, beam_width=args.beam_width)
    Path(args.output).write_text(json.dumps(result, indent=2))
    winner = result['independent_search']['independent_winner']
    print(json.dumps({'winner': winner['seconds_per_mob'],
                      'talents': winner['talent_allocation'],
                      'policy': [r['action_id'] for r in winner['best_policy']['policy']['rules']],
                      'old_feral': result['held_out_frozen_feral']['seconds_per_mob'],
                      'evaluated_allocations': result['independent_search']['total_independent_evaluated_allocations']}, indent=2))
