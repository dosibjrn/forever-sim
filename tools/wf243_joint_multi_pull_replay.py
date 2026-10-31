"""Source-independent repeated-pull joint search vs frozen .240 Feral build."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.game.model import PolicyDefinition, PolicyRuleDefinition, PolicyCondition
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_multi_pull_joint import search_joint_repeated_pulls, replay_exact_challenger


def frozen_policy(data):
    return PolicyDefinition(
        id=data['id'], label=data['label'],
        rules=tuple(PolicyRuleDefinition(
            id=r['id'], action_id=r['action_id'], phase=r['phase'],
            conditions=tuple(PolicyCondition(**c) for c in r['conditions']),
            provenance=r['provenance']) for r in data['rules']),
        provenance=data['provenance'])


def run(*, allocations=10, screen_gears=3, finalists=2, pulls=3):
    fixture = json.loads((Path(__file__).resolve().parents[1] /
                          'fixtures/wf243_heldout_feral_l20.json').read_text())
    class_key, level = fixture['class_key'], fixture['level']
    old = fixture['talent_allocation']
    search = search_joint_repeated_pulls(
        class_key=class_key, level=level, pulls=pulls,
        max_allocations=allocations, screening_gear_count=screen_gears,
        finalists=finalists, policy_cap=256, held_out_allocation=old, strategy='sample')
    ir = build_game_ir_slice(class_key=class_key, level=level)
    gears = _gear_envelope(class_key, level, max_gear_candidates=256,
                           required_level_policy='observed', include_melee_gear=True,
                           ir_slice=ir)
    matches = [g for g in gears if g['id'] == fixture['gear_id']]
    if len(matches) != 1:
        raise ValueError('held-out original gear ID not unique in current canonical catalogue')
    actual_slots = {k: int(v['item_id']) for k,v in matches[0]['selection'].slots.items()}
    frozen_slots = {k: int(v['item_id']) for k,v in fixture['gear_slots'].items()}
    if actual_slots != frozen_slots:
        raise ValueError('held-out original gear slots differ from source catalogue')
    challenger = replay_exact_challenger(
        class_key=class_key, level=level, gear=matches[0], allocation=old,
        policy=frozen_policy(fixture['policy']), pulls=pulls,
        post_combat_action_ids=(fixture['policy']['provenance']['exit_action_id'],))
    winner = search['independent_winner']
    result = {'version': '0.11.48.243', 'reference': fixture['reference'],
              'reference_single_pull_s_per_mob': fixture['reference_single_pull_s_per_mob'],
              'independent_search': search, 'frozen_held_out_challenger': challenger,
              'held_out_exact_gear_talent_policy': True,
              'same_repeated_pull_objective': True,
              'delta_new_minus_old_s_per_mob': winner['seconds_per_mob']-challenger['seconds_per_mob'],
              'global_optimum_proven': False}
    return result

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--allocations',type=int,default=10)
    parser.add_argument('--screen-gears',type=int,default=3)
    parser.add_argument('--finalists',type=int,default=2)
    parser.add_argument('--pulls',type=int,default=3)
    parser.add_argument('--output',default='WF243_INDEPENDENT_JOINT_REPEATED_PULL.json')
    a=parser.parse_args()
    r=run(allocations=a.allocations,screen_gears=a.screen_gears,finalists=a.finalists,pulls=a.pulls)
    Path(a.output).write_text(json.dumps(r,indent=2))
    w=r['independent_search']['independent_winner']; old=r['frozen_held_out_challenger']
    print(json.dumps({'winner_s_per_mob':w['seconds_per_mob'],
                      'winner_talents':w['talent_allocation'],
                      'winner_gear':w['gear_id'],
                      'winner_policy_actions':[rule['action_id'] for rule in w['best_policy']['policy']['rules']],
                      'old_s_per_mob':old['seconds_per_mob'],
                      'old_gear':old['gear_id'],
                      'independent_allocations':r['independent_search']['allocation_coverage']['sampled'],
                      'states':r['independent_search']['screened_state_count']+r['independent_search']['finalist_state_count'],
                      'policy_evaluations':r['independent_search']['valid_policy_evaluations']},indent=2))
