"""WF399: source-IR 2D search must qualify longer survival before 100mob promotion."""
import json
from pathlib import Path

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import search_bounded_joint_frontier

ROOT=Path(__file__).resolve().parents[1]


def _source():
    ir=build_game_ir_slice(class_key='druid',level=30,
        ability_db_path=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite')
    stage=json.loads((ROOT/'evidence/wf351/WF351_L30_SEED_STAGE.json').read_text())
    # A published source-legal 21-point allocation, not a partial 16-point seed.
    stage['allocation']={'furor':5,'ferocity':5,'genesis':5,'naturalist':5,'feral_instinct':1}
    return ir,stage


def test_qualification_must_be_strictly_between_screen_and_finalist_horizon():
    ir,stage=_source()
    for invalid in (4,100,101):
        with pytest.raises(ValueError,match='INVALID_JOINT_SEARCH_BUDGET'):
            search_bounded_joint_frontier(class_key='druid',level=30,
                source_ir=ir,seed_stage=stage,max_talents=1,
                screen_mobs=4,finalist_mobs=100,pack_size=2,
                qualification_mobs=invalid)


def test_real_2d_qualification_is_paid_and_only_100mob_winner_is_accepted():
    ir,stage=_source()
    result=search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,max_talents=1,max_gear_moves=0,
        max_policies=2,max_recovery_policies=1,max_paid_builds=3,
        max_cpu_s=48.,per_candidate_wall_s=24.,screen_then_finalists=True,
        max_finalists=1,pack_size=2,qualification_mobs=12,max_qualifiers=2)
    assert result['qualification_mobs']==12
    assert result['qualification_evaluated_candidates']>=1
    assert result['qualification_complete_candidates']>=1
    assert result['qualification_events']>0
    assert result['complete_100mob_candidates']>=1, result
    assert result['winner']['status']=='COMPLETE'
    assert result['winner']['mobs']==100
    assert result['winner']['full_events']>0
    assert result['source_legal_gear_universe_verified'] is False
    assert result['eligible_for_checkpoint_acceptance'] is False


def test_failed_intermediate_survival_never_promotes_to_100mob(monkeypatch):
    """Only a COMPLETE paid intermediate horizon can consume a full finalist."""
    from src.v2 import source_bounded_joint_frontier as frontier
    ir,stage=_source()
    seen=[]

    def paid_runtime(candidate, *, mobs, **kwargs):
        seen.append((mobs,candidate.policy.id))
        if mobs==12 and candidate.policy.id.endswith(':stateful:claw:28'):
            return {'status':'BLOCKED_SURVIVAL','events':100}
        return {'status':'COMPLETE','mean_s_per_mob':20.0,
                'events':100+mobs,'elapsed_cpu_s':.01,'mob_completed':mobs}

    monkeypatch.setattr(frontier,'isolated_joint_evaluation',paid_runtime)
    result=frontier.search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,max_talents=1,max_gear_moves=0,
        max_policies=2,max_recovery_policies=1,max_paid_builds=2,
        max_cpu_s=60.,screen_then_finalists=True,max_finalists=1,
        pack_size=2,qualification_mobs=12,max_qualifiers=2)
    assert result['qualification_evaluated_candidates']==2
    assert result['qualification_complete_candidates']==1
    assert result['complete_100mob_candidates']==1
    assert sum(mobs==100 for mobs,_ in seen)==1
    assert result['winner']['status']=='COMPLETE'
    assert any(row.get('qualification_status')=='BLOCKED_SURVIVAL'
               and row['status']=='NOT_FULL_EVALUATED_QUALIFICATION_FAILED_OR_BUDGET'
               for row in result['rows'])


def test_three_paid_phase_wall_times_partition_actual_wall(monkeypatch):
    """P4/P5 wall reporting must not count qualification twice."""
    from src.v2 import source_bounded_joint_frontier as frontier
    ir,stage=_source()

    def paid_runtime(candidate, *, mobs, **kwargs):
        if mobs==12:
            import time
            time.sleep(.05)
        return {'status':'COMPLETE','mean_s_per_mob':20.,
                'events':100+mobs,'elapsed_cpu_s':.01,'mob_completed':mobs}

    monkeypatch.setattr(frontier,'isolated_joint_evaluation',paid_runtime)
    result=frontier.search_bounded_joint_frontier(class_key='druid',level=30,
        source_ir=ir,seed_stage=stage,max_talents=1,max_gear_moves=0,
        max_policies=2,max_recovery_policies=1,max_paid_builds=2,
        max_cpu_s=60.,screen_then_finalists=True,max_finalists=1,
        pack_size=2,qualification_mobs=12,max_qualifiers=2)
    assert abs(result['wall_s']-(result['screen_phase_wall_s']+
               result['qualification_phase_wall_s']+
               result['finalist_phase_wall_s'])) < .02
