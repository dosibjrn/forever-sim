"""Reproduce WF378 Mage L30 Evocation-vs-water paid 100-mob diagnostic.

Not a P4/P5 gear x talent x APL search or a source-verified server tick proof.
"""
from __future__ import annotations
import json
from pathlib import Path
from time import perf_counter, process_time
from src.game.data.forever import build_game_ir_slice
from src.game.model import PolicyCondition, PolicyDefinition, PolicyRuleDefinition
from src.game.multi_pull import evaluate_repeated_pulls


def run() -> dict:
    ir = build_game_ir_slice(class_key='mage', level=30)
    frost = next(a for a in ir.actions if a.family_key == 'frostbolt')
    evo = next(a for a in ir.actions if a.family_key == 'evocation')
    policy = PolicyDefinition(id='wf378:fixed_source_frostbolt_probe',
        label='Frostbolt with mana threshold, no in-combat Evocation',
        rules=(PolicyRuleDefinition('frostbolt', frost.id, conditions=(
            PolicyCondition(kind='resource_threshold', resource_id='mana',
                            operator='gte', value=100.),)),))
    rows = {}
    for incoming in (False, True):
        for allow_channel in (False, True):
            start_wall, start_cpu = perf_counter(), process_time()
            result = evaluate_repeated_pulls(ir_slice=ir, policy=policy, level=30,
                target_health=150., count=100, pack_size=1,
                schedule_incoming_attacks=incoming, recovery_mode='always',
                recovery_action_ids=(None if allow_channel else ()), max_actions=150)
            rows[f'{"incoming" if incoming else "no_incoming"}_{"channel" if allow_channel else "water"}'] = {
                'completed_mobs': sum(p['mob_count'] for p in result.pulls if p['pack_all_defeated']),
                'seconds_per_mob': result.seconds_per_mob,
                'total_s': result.end_time_s - result.start_time_s,
                'recovery_s': sum(p['recovery_s'] for p in result.pulls),
                'combat_s': sum(p['kill_s'] for p in result.pulls),
                'events': sum(p['event_transitions'] for p in result.pulls),
                'wall_s': perf_counter() - start_wall,
                'cpu_s': process_time() - start_cpu,
                'evocation_cooldown_ready_s': result.actor.cooldown_ready_s.get(evo.id),
            }
    return {'checkpoint': 'Mage L30 unrestricted', 'scenario': {
        'target_hp': 150, 'mobs': 100, 'pack_size': 1,
        'fixed_policy': policy.id, 'starting_mana': 750,
        'spirit': 60, 'spirit_source': 'qualified_proxy_not_verified_forever_level30',
        'evocation_tick_source': 'classic_spirit_2s_proxy_not_verified_forever_server_tick',
        'objective': 'actual_100_mob_combat_paid_recovery_survival',
        'not_checkpoint_P4_P5_P6': True}, 'results': rows,
        'improvement_pct_no_incoming': 100 * (1 - rows['no_incoming_channel']['seconds_per_mob'] / rows['no_incoming_water']['seconds_per_mob']),
        'improvement_pct_incoming': 100 * (1 - rows['incoming_channel']['seconds_per_mob'] / rows['incoming_water']['seconds_per_mob'])}


if __name__ == '__main__':
    result = run()
    output = Path('evidence/wf378/WF378_100MOB_DIAGNOSTIC.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))
