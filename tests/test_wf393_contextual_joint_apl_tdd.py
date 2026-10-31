"""WF393: source-generated contextual APLs must compete in the paid joint frontier."""
from dataclasses import replace
import json
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.policy_evolution import _identity
from src.v2.source_persistent_joint_finalists import prepare_candidate
import src.v2.source_bounded_joint_frontier as joint

ROOT=Path(__file__).resolve().parents[1]
MAGE=ROOT/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'
DRUID=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'


def _mage_stage(ir):
    evidence=ROOT/'evidence/wf383/WF383_MAGE_L30_WAND_GEAR_100MOB.json'
    gear=json.loads(evidence.read_text())['baseline']['gear']
    return joint.source_gear_seed_stage(gear=gear,ir=ir,source_evidence=str(evidence))


def test_source_joint_frontier_generates_and_mutates_contextual_apls_without_legacy_seeds():
    for class_key,db in (('mage',MAGE),('druid',DRUID)):
        ir=build_game_ir_slice(class_key=class_key,level=30,ability_db_path=db)
        if class_key=='mage':stage=_mage_stage(ir)
        else:stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
        frontier=joint.source_joint_policy_frontier(ir,stage,max_policies=16)
        assert len(frontier)>=8
        origins={origin for origin,policy in frontier}
        assert 'incumbent' in origins
        assert any('scratch' in origin for origin in origins)
        assert any('mutation' in origin for origin in origins)
        assert len({_identity(policy) for _,policy in frontier})==len(frontier)
        assert any(len(p.rules)>=2 and any(r.conditions for r in p.rules)
                   for _,p in frontier)
        ids={a.id for a in ir.actions}
        assert all(all(r.action_id in ids for r in p.rules) for _,p in frontier)


def test_real_100mob_joint_search_executes_conditional_apls_not_only_single_fallbacks():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
    stage=_mage_stage(ir)
    result=joint.search_bounded_joint_frontier(class_key='mage',level=30,
        source_ir=ir,seed_stage=stage,max_talents=1,max_gear_moves=0,
        max_policies=10,max_recovery_policies=1,max_paid_builds=10,
        max_cpu_s=22.,per_candidate_wall_s=3.)
    assert result['paid_candidates']==10
    assert result['complete_100mob_candidates']>=2
    assert result['events']>0
    assert len({r['policy_signature'] for r in result['rows']})>=8
    conditional=[r for r in result['rows'] if len(r['policy_ir']['rules'])>=2
                 and any(rule['conditions'] for rule in r['policy_ir']['rules'])]
    assert conditional, 'actual paid search must evaluate multi-rule contextual APLs'
    assert any(r['status']=='COMPLETE' and r['mobs']==100 for r in conditional)
    assert any('mutation' in r['policy_origin'] for r in result['rows'])
    assert any('scratch' in r['policy_origin'] for r in result['rows'])
    assert not result['eligible_for_checkpoint_acceptance']


def test_completed_conditional_joint_policy_replays_same_canonical_100mob():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
    stage=_mage_stage(ir)
    result=joint.search_bounded_joint_frontier(class_key='mage',level=30,
        source_ir=ir,seed_stage=stage,max_talents=1,max_gear_moves=0,
        max_policies=10,max_recovery_policies=1,max_paid_builds=10,
        max_cpu_s=22.,per_candidate_wall_s=3.)
    row=next(r for r in result['rows'] if r.get('status')=='COMPLETE'
             and len(r['policy_ir']['rules'])>=2
             and any(rule['conditions'] for rule in r['policy_ir']['rules']))
    compiled,_=compile_talent_runtime(ir)
    frontier=joint.source_joint_policy_frontier(compiled,stage,max_policies=10)
    policy=next(p for _,p in frontier if _identity(p)==row['policy_signature'])
    candidate=prepare_candidate(class_key='mage',level=30,stage=stage,
        source_ir=compiled,allocation_override=row['allocation'],allow_partial_gear_stats=True)
    replay=joint.isolated_joint_evaluation(replace(candidate,policy=policy),
        level=30,mobs=100,timeout_s=4.)
    assert replay['status']=='COMPLETE'
    assert abs(replay['mean_s_per_mob']-row['seconds_per_mob'])<1e-8
    assert replay['events']==row['full_events']


def test_druid_source_apls_respect_seed_opening_form_and_include_cat_damage_priority():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DRUID)
    stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    cat=next(mode for mode in ir.modes if mode.id=='cat')
    assert stage['gear_policy_result']['winner']['winner']['prefix'][0]=='cat_form:768'
    frontier=joint.source_joint_policy_frontier(ir,stage,max_policies=16)
    assert all(rule.action_id in cat.enabled_action_ids
               for _,policy in frontier for rule in policy.rules), (
        'caster/bear actions are not legal Cat Form continuations after the sourced opening')
    assert any(len(policy.rules)>=2 and any(rule.conditions for rule in policy.rules)
               for _,policy in frontier)
    assert any(any(rule.action_id=='rake:1822' for rule in policy.rules)
               for _,policy in frontier)


def test_druid_cat_contextual_policy_completes_real_100mob_not_timeout():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DRUID)
    stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    result=joint.search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,max_talents=1,max_gear_moves=0,
        max_policies=8,max_recovery_policies=1,max_paid_builds=8,
        max_cpu_s=32.,per_candidate_wall_s=5.)
    conditional=[r for r in result['rows'] if len(r['policy_ir']['rules'])>=2
                 and any(rule['conditions'] for rule in r['policy_ir']['rules'])]
    assert conditional
    assert any(r['status']=='COMPLETE' and r['mobs']==100 for r in conditional)
    assert result['events']>0


def test_source_damage_priority_prefers_highest_legal_rank_without_dropping_lower_ranks():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DRUID)
    stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    contextual=joint._source_opening_context_ir(ir,stage)
    pairs,attacks=joint._source_damage_priority_specs(contextual)
    assert {'claw:20','claw:28'} <= {a.id for a in attacks}
    rake_filler=[second.id for first,second in pairs if first.id=='rake:1822'
                 and second.family_key=='claw']
    assert rake_filler[:2]==['claw:28','claw:20']
    frontier=joint.source_joint_policy_frontier(ir,stage,max_policies=4)
    assert [r.action_id for r in frontier[1][1].rules]==['rake:1822','claw:28']


def test_mage_scratch_source_apl_is_paid_and_can_complete_100mob():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=MAGE)
    stage=_mage_stage(ir)
    frontier=joint.source_joint_policy_frontier(ir,stage,max_policies=8)
    first_scratch=next(policy for origin,policy in frontier if origin=='scratch')
    assert first_scratch.rules, 'empty no-cast APL must not monopolize early scratch budget'
    result=joint.search_bounded_joint_frontier(class_key='mage',level=30,
        source_ir=ir,seed_stage=stage,max_talents=1,max_gear_moves=0,
        max_policies=8,max_recovery_policies=1,max_paid_builds=8,
        max_cpu_s=12.,per_candidate_wall_s=3.)
    assert any(row['policy_origin']=='scratch' and row['status']=='COMPLETE'
               and row['mobs']==100 for row in result['rows'])
