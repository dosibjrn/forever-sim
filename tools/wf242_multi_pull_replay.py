"""Reproduce source-policy repeated-pull results with real combat/recovery."""
from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.game.data.forever.registry import build_game_ir_slice
from src.game.multi_pull import search_repeated_pull_policies, evaluate_repeated_pulls
from src.shared.leveling.objective import representative_hp


def run():
    results = {'software_version': '0.11.48.242', 'scenario': '3 source-backed consecutive pulls with source-cadenced incoming enemy attacks',
               'search_scope': 'all canonical policy seeds per level; naked Game IR gear and talents; no independent full joint search',
               'comparisons': []}
    for level in (20, 24):
        ir = build_game_ir_slice(class_key='druid', level=level)
        search = search_repeated_pull_policies(ir_slice=ir, level=level, target_health=representative_hp(level))
        policy = next(p for p in ir.policies if p.id == search['winner']['policy_id'])
        kwargs = dict(ir_slice=ir, policy=policy, level=level, target_health=representative_hp(level),
                      count=3, pre_combat_action_ids=tuple(search['winner']['entry_action_ids']),
                      post_combat_action_ids=tuple(search['winner']['exit_action_ids']))
        real = evaluate_repeated_pulls(**kwargs)
        control = evaluate_repeated_pulls(**kwargs, carry_actor_periodics=False)
        results['comparisons'].append({
            'level': level, 'source_target_hp': representative_hp(level),
            'policy_search': search,
            'winner_real_s_per_mob': real.seconds_per_mob,
            'winner_old_drop_counterfactual_s_per_mob': control.seconds_per_mob,
            'delta_s_per_mob': control.seconds_per_mob - real.seconds_per_mob,
            'relative_improvement_pct': 100*(control.seconds_per_mob-real.seconds_per_mob)/control.seconds_per_mob,
            'counterfactual_pulls': list(control.pulls),
        })
    return results


if __name__ == '__main__':
    output = run()
    path = Path('WF242_MULTI_PULL_POLICY_EVIDENCE.json')
    path.write_text(json.dumps(output, indent=2))
    print(json.dumps([{'level': r['level'], 'winner': r['policy_search']['winner']['policy_id'],
                       'real': r['winner_real_s_per_mob'], 'control': r['winner_old_drop_counterfactual_s_per_mob'],
                       'candidates': r['policy_search']['candidate_count']}
                      for r in output['comparisons']], indent=2))
