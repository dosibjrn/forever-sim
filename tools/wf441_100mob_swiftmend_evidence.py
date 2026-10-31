"""Real fixed-policy 100-mob end-to-end diagnostic, NOT a search optimum."""
from pathlib import Path
import argparse,json
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.model import PolicyDefinition,PolicyRuleDefinition,PolicyCondition
from src.game.multi_pull import evaluate_repeated_pulls

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
FILL={'furor':5,'natural_shapeshifter':3,'naturalist':2,'natures_focus':5,'swiftmend':1}

def evidence():
    ir=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB))[0]
    ir=apply_talent_selection(ir,FILL,level=30,bonus_talent_points=5)[0]
    hot=next(a for a in ir.actions if a.family_key=='rejuvenation')
    swift=next(a for a in ir.actions if a.family_key=='swiftmend')
    wrath=next(a for a in ir.actions if a.family_key=='wrath')
    aura=hot.effects[0].aura_id
    policy=PolicyDefinition('wf441_hot_full_duration_100mob','HoT/SW/DPS',rules=(
        PolicyRuleDefinition('rejuvenation',hot.id,conditions=(
            PolicyCondition(kind='aura_missing',scope='actor',aura_id=aura),)),
        PolicyRuleDefinition('swiftmend',swift.id),
        PolicyRuleDefinition('wrath',wrath.id)))
    run=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=30,
        target_health=200.,count=100,schedule_incoming_attacks=True,
        recovery_mode='always',max_actions=128)
    summary={'source_build':'1.60.1.70338','level':30,'talent_bonus_points':5,
        'fixed_talents':FILL,'policy':policy.id,'target_health':200.,
        'requested_mob_count':100,'pulls':len(run.pulls),
        'actual_mob_count':sum(p['mob_count'] for p in run.pulls),
        'all_targets_defeated':all(p['pack_all_defeated'] for p in run.pulls),
        'swiftmend_used_in_pulls':sum(any(a['action_id']==swift.id for a in p['selected_actions'])
            for p in run.pulls),'seconds_per_mob':run.seconds_per_mob,
        'incoming_attacks_enabled':True,'recovery_mode':'always',
        'scope':'MECHANICS_DIAGNOSTIC_NOT_OPTIMAL_SEARCH_NOT_P2_CERTIFICATION'}
    if not summary['all_targets_defeated'] or summary['actual_mob_count']!=100 or summary['swiftmend_used_in_pulls']!=100:
        raise AssertionError('WF441_100MOB_END_TO_END_FAILURE')
    return summary
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();result=evidence();args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(result)
