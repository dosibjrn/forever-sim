"""WF438 gate: reclaim unused Top-N time for new source-legal search candidates."""
from pathlib import Path
from unittest.mock import patch
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import (
    search_bounded_joint_frontier, source_cold_start_stage)

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_druid_l30_talents_70338.sqlite'


def test_search_only_reclaims_unused_refinement_budget_into_unique_legal_frontier():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    stage=source_cold_start_stage(class_key='druid',level=30,source_ir=ir,gear_role='druid_feral')
    calls=[]
    def short_score(candidate, *, mobs, **kw):
        assert mobs <= 4, '100_MOB_FORBIDDEN_IN_SEARCH'
        calls.append((candidate.allocation,mobs))
        return {'status':'COMPLETE','mean_s_per_mob':20.+len(calls)*0.001,
                'events':15,'elapsed_cpu_s':0.0001,'mob_completed':mobs}
    def empty_refinement(*, screened, **kwargs):
        return screened,{'rounds_completed':0,'stat_probes':0,'gear_probes':0,
                         'policy_probes':0,'paid_evaluations':0,'events':0,
                         'worker_cpu_s':0.,'rows':[]}
    with patch('src.v2.source_bounded_joint_frontier._quick_joint_evaluation',side_effect=short_score), \
         patch('src.v2.source_bounded_joint_frontier._refine_screened_top_n',side_effect=empty_refinement):
        result=search_bounded_joint_frontier(class_key='druid',level=30,source_ir=ir,
            seed_stage=stage,bonus_talent_points=5,max_talents=60,
            max_gear_moves=8,max_policies=5,max_recovery_policies=2,
            max_paid_builds=1500,max_cpu_s=10.,screen_mobs=2,
            search_only=True,screen_budget_fraction=.45,
            refinement_top_n=4,refinement_rounds=1)
    assert result.get('backfill_screen_candidates',0)>0, 'unused refinement time was not reclaimed'
    assert result['screen_budget_fraction_effective']==.45
    assert result['backfill_screen_candidates'] == result['initial_frontier_paid_candidates'] - result['first_pass_screen_candidates']
    assert result['unique_full_builds'] >= result['first_pass_screen_candidates'] + result['backfill_screen_candidates']
    assert result['complete_100mob_candidates']==0
    assert result['wall_s']<=11.0
