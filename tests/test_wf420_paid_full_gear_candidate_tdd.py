"""WF420: gear package selection is actually paid in CombatRuntime."""
from pathlib import Path
import json
from tools.wf420_druid20_independent_full_replay import rebuild_result_winner
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import source_cold_start_stage,_recovery_variants
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate


def test_source_full_gear_package_is_paid_and_improves_actual_hundred_mobs():
    evidence,candidate,recovery=rebuild_result_winner()
    winner=evidence['winner']
    assert winner['gear_move']=='source_stat_package:spell_power'
    assert sum(winner['allocation'].values())==16
    result=evaluate_persistent_candidate(candidate,level=20,mobs=100,
                                         recovery_policy=recovery,max_wall_s=15.)
    assert result['status']=='COMPLETE' and result['count']==100
    assert abs(result['mean_s_per_mob']-winner['seconds_per_mob'])<1e-9
    assert result['events']==winner['full_events']

    ir=build_game_ir_slice(class_key='druid',level=20)
    stage=source_cold_start_stage(class_key='druid',level=20,
                                  source_ir=ir,gear_role='druid_feral')
    base=prepare_candidate(class_key='druid',level=20,source_ir=ir,stage=stage,
                           allocation_override=winner['allocation'],bonus_talent_points=5,
                           allow_partial_gear_stats=True)
    recovery0=dict(_recovery_variants(base.ir,stage,3))[winner['recovery']]
    old=evaluate_persistent_candidate(base,level=20,mobs=100,
                                      recovery_policy=recovery0,max_wall_s=15.)
    assert old['status']=='COMPLETE' and old['count']==100
    assert result['mean_s_per_mob']<old['mean_s_per_mob']


def test_stat_sensitivity_evidence_never_fakes_positive_values():
    path=Path(__file__).resolve().parents[1]/'evidence/wf420/WF420_P4_INDEPENDENT_100MOB_AND_STAT_PROBE.json'
    data=json.loads(path.read_text())
    assert data['replay']['exact_result'] is True
    assert data['p3_status'].startswith('NOT_CERTIFIED')
    measurements=data['source_100mob_stat_sensitivity_fixed_best_recovery']
    assert measurements['spell_power']['weight_s_saved_per_mob_per_unit']>0
    assert measurements['stamina']['weight_s_saved_per_mob_per_unit']>0
    assert measurements['armor']['weight_s_saved_per_mob_per_unit']==0
