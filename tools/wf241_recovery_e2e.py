"""Run real sourced mode/policy search with incoming swings and mixed recovery."""
from __future__ import annotations
import json
from pathlib import Path
from src.v2.source_mode_search import evaluate_discovered_mode_search
from src.game.data.forever.registry import build_game_ir_slice
from src.game.runtime import ActorState
from src.game.recovery import recover_actor_to_full

cases = []
for level, rear, max_policies in ((20, None, 16), (24, None, 256), (24, 'behind', 1024)):
    result = evaluate_discovered_mode_search(class_key='druid', level=level,
        schedule_incoming_attacks=True, max_policies_per_path=max_policies,
        attacker_relative_position=rear)
    w = result['winner']
    cases.append({'level': level, 'geometry': rear or 'unknown_front_default',
                  'candidate_count': result['candidate_count'],
                  'evaluated_count': result['evaluated_count'],
                  'seconds_per_mob': w['seconds_per_mob'],
                  'kill_s': w['combat_kill_s'], 'recovery_s': w['recovery_s'],
                  'policy_id': w['policy_id'],
                  'selected_actions': [a['action_id'] for a in w['selected_actions']]})

ir = build_game_ir_slice(class_key='priest', level=20)
actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
actor.resources.update({'health':250.0,'mana':490.0})
renew = next(a for a in ir.actions if a.family_key == 'renew')
renew_result = recover_actor_to_full(actor=actor, level=20, actions=(renew,), start_time_s=0)

old = {(20, 'unknown_front_default'): {'seconds_per_mob':35.52391304347826,'recovery_s':10.52391304347826},
       (24, 'unknown_front_default'): {'seconds_per_mob':26.46703687975696,'recovery_s':9.46703687975696},
       (24, 'behind'): {'seconds_per_mob':25.46703687975696,'recovery_s':9.46703687975696}}
for c in cases:
    prior = old[(c['level'],c['geometry'])]
    c['prior_v240_same_policy_envelope'] = prior
    c['recovery_reduction_s'] = prior['recovery_s'] - c['recovery_s']

payload = {'version':'0.11.48.241',
           'scope':'sourced_mode_policy_combat_and_recovery; not gear×talent global optimum',
           'cases':cases,
           'priest_renew': {'heal_action_sequence':renew_result.provenance['heal_action_sequence'],
                            'total_s':renew_result.total_s,
                            'hot_heal_events':sum(e['kind']=='Heal' and e['payload'].get('periodic',False) for e in renew_result.heal_events)},
           'limitations':['existing active HoT from combat is not rehydrated into recovery runtime',
                          'remaining HoT ticks are not carried into next pull',
                          'vendor food/water tiers are the existing shared authority, not new source ingest',
                          'source coverage, route and full leveling fidelity incomplete']}
Path('WF241_RECOVERY_E2E.json').write_text(json.dumps(payload,indent=2))
print(json.dumps(payload,indent=2))
