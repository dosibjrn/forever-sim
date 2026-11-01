"""Source-pinned Druid L30 Talented ON Insect Swarm 100mob comparison.

A bounded same-allocation, same-gear diagnostic, NOT a cold P4/P5 or NPC-certified proof.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.model import PolicyCondition
from src.game.policy_evolution import from_source_rules
from src.v2.source_bounded_joint_frontier import (bounded_full_point_talent_frontier,
    source_talent_unlock_witnesses,_prepare_joint_policy_candidate)
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'


def run():
    root,_=compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,
        ability_db_path=DB))
    allocation=next(a for a in bounded_full_point_talent_frontier(root,level=30,
        max_frontier=16,bonus_talent_points=5)[0] if a.get('insect_swarm')==1)
    selected,_=apply_talent_selection(root,allocation,level=30,bonus_talent_points=5)
    stage=json.loads((ROOT/'evidence/wf360/WF360_L30_P4_30S.json').read_text())['winner_stage']
    witness=next(w for w in source_talent_unlock_witnesses(root,selected,stage)
        if w['action_id']=='insect_swarm:24974')
    without=from_source_rules(selected,[
        ('wrath:5180',(PolicyCondition(kind='mode_state',operator='eq',value='caster'),)),
        ('cancel_mode:cat',(PolicyCondition(kind='mode_state',operator='eq',value='cat'),))],
        provenance='heldout_same_build_without_insect_cast')
    rows={}
    for label,policy in (('insect_swarm_plus_wrath',witness['policy']),
                         ('wrath_only_same_full_build',without)):
        candidate=_prepare_joint_policy_candidate(class_key='druid',level=30,
            stage=stage,allocation=allocation,source_ir=root,
            allow_partial_gear_stats=True,policy_label=label,policy=policy,
            bonus_talent_points=5)
        result=evaluate_persistent_candidate(candidate,level=30,mobs=100,
            max_total_events=200000)
        if result['status']!='COMPLETE' or result['count']!=100:
            raise RuntimeError((label,result))
        rows[label]={'mean_s_per_mob':result['mean_s_per_mob'],
            'total_s':result['total_s'], 'events':result['events'],
            'combat_s':result['combat_s'],'recovery_s':result['recovery_s'],
            'action_counts':result['source_action_counts'],
            'policy_rules':[r.action_id for r in policy.rules]}
    return {'parent':'WF423','status':'BOUNDED_PAID_DIAGNOSTIC_NOT_CHECKPOINT',
        'class_key':'druid','level':30,'talented_enabled':True,
        'talent_point_budget':26,'allocation':allocation,
        'source_db_sha256':hashlib.sha256(DB.read_bytes()).hexdigest(),
        'source_stage':'evidence/wf360/WF360_L30_P4_30S.json winner_stage',
        'scope':'same_gear_same_talents_same_source_non_cold_persistent_100mob',
        'forever_named_yeti_enemy_attested':False,
        'source_known_issues':['periodic_tick_interval_classic_proxy_not_forever_verified',
            'insect_swarm_spell_power_coefficient_not_source_verified',
            'caster_form_restriction_source_proxy','encounter_is_not_named_forever_yeti',
            'talent_search_not_exhaustive'],
        'results':rows,
        'difference_s_per_mob':rows['insect_swarm_plus_wrath']['mean_s_per_mob']-
            rows['wrath_only_same_full_build']['mean_s_per_mob']}


if __name__=='__main__':
    data=run()
    out=ROOT/'evidence/wf424/WF424_DRUID_L30_INSECT_SWARM_100MOB.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(data,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
    print(json.dumps({'artifact':str(out),'results':data['results'],
        'difference_s_per_mob':data['difference_s_per_mob']},indent=2))
