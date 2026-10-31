"""Real Forever W3 talent x gear x ordered-policy scorer, no OG seeding.

Optional held-out Mage talent/priority fixture is evaluated AFTER independent
search, as one separately charged real simulator call. The historical gear
was unnamed, so this is NOT a complete OG-build apples-to-apples comparison.
"""
import argparse
import json
from pathlib import Path

from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents


def _heldout_mage_l20(winner_stage):
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.talents import apply_talent_selection
    from src.game.gear import apply_gear_selection
    from src.game.model import PolicyDefinition, PolicyRuleDefinition
    from src.v2.generic_backend import _policy_combat_evaluation
    source=build_game_ir_slice(class_key='mage',level=20)
    # Frozen legacy .250 candidate. No part of this fixture enters discovery.
    old_talents={'improved_frostbolt':5,'elemental_precision':5,'ice_lance':1}
    talented,_=apply_talent_selection(source,old_talents,level=20)
    gear=winner_stage['gear_policy_result']['winner']['gear']
    if not gear:
        return {'status':'NO_NAMED_GEAR_TO_COMPARE','evaluated_independently':False}
    geared,_=apply_gear_selection(talented,aggregate_stats=gear['aggregate_stats'],
        selected_items=tuple(gear['slots'].values()),source='canonical_sqlite_forever_catalogue')
    actions=[a for a in geared.actions if a.family_key=='frostbolt']
    if len(actions)!=1:
        raise ValueError('historical Frostbolt-only policy cannot be uniquely sourced')
    policy=PolicyDefinition(id='heldout-mage-l20-frostbolt-only',label='Frozen old Frostbolt-only',
        rules=(PolicyRuleDefinition(id='frostbolt-only',action_id=actions[0].id),),
        provenance={'authority':'historical_frozen_challenger','search_performed':False})
    result,execution,details=_policy_combat_evaluation(geared,level=20,
        policy_override=policy,schedule_incoming_attacks=True)
    return {'status':'EVALUATED' if result is not None else 'BLOCKED_NO_KILL',
            'evaluated_independently':True,'real_simulator_attempts':1,
            'baseline':'v0.11.48.250 historical Mage L20 talents + Frostbolt-only policy',
            'talents':old_talents,'policy':policy.as_dict(),
            'gear':gear,'same_named_gear_as_new_winner':True,
            'same_scenario_objective':True,'valid_full_OG_comparison':False,
            'incomparable_reason':'Historical OG equipment was an unnamed analytic fixture; its exact items and travel objective cannot be replayed.',
            'seconds_per_mob':result.seconds_per_mob if result else None,
            'kill_s':execution.timeline.target_death_s if execution else None,
            'recovery_s':details['recovery']['total_s'] if result else None,
            'selected_actions':[dict(x) for x in execution.selected_actions] if execution else []}


def run(class_key='mage',level=20,budget=480,per_talent=80,heldout=False):
    reserve=1 if heldout and class_key=='mage' and level==20 else 0
    if budget<=reserve:
        raise ValueError('budget too small for held-out real simulator attempt')
    result=run_source_budgeted_joint_talents(class_key=class_key,level=level,
        max_evaluations=budget-reserve,evaluations_per_talent=per_talent,
        initial_search=24,search_per_gear=24,max_gear_states=2)
    if reserve:
        result['heldout_challenger']=_heldout_mage_l20(result['winner'])
    result['search_budget']=budget-reserve
    result['reserved_challenger_attempts']=reserve
    result['total_real_simulator_attempts']=result['attempted']+reserve
    result['total_budget_including_challenger']=budget
    assert result['total_real_simulator_attempts']<=budget
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--class-key',default='mage')
    p.add_argument('--level',type=int,default=20)
    p.add_argument('--budget',type=int,default=480)
    p.add_argument('--per-talent',type=int,default=80)
    p.add_argument('--heldout',action='store_true')
    p.add_argument('--output',default='WF260_JOINT_REPLAY.json')
    a=p.parse_args()
    r=run(a.class_key,a.level,a.budget,a.per_talent,a.heldout)
    Path(a.output).write_text(json.dumps(r,indent=2,default=str)+'\n')
    print(json.dumps({k:r[k] for k in ('status','budget','attempted','evaluated','blocked',
          'talent_states_evaluated','legal_talent_states_discovered')}|{
          'winner':None if r['winner'] is None else {
              'allocation':r['winner']['allocation'],'score_s_per_mob':r['winner']['score_s_per_mob'],
              'gear':r['winner']['gear_policy_result']['winner']['gear'] is not None},
          'heldout_s_per_mob':r.get('heldout_challenger',{}).get('seconds_per_mob')}))
