"""Source legality and contextual Top5 challenger frontier regressions."""
import json
from pathlib import Path
import pytest
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
from tools.wf358_l30_p3_top5_replay import source_legal_proposals,STAGE,PRIOR


def stage():return json.loads(STAGE.read_text())


def test_paired_offhand_can_be_added_to_2h_stage():
    before=stage()
    assert 'offhand' not in before['gear_policy_result']['winner']['gear']['slots']
    after=substituted_multi_stage(stage=before,class_key='druid',level=30,
                                  swaps={'weapon':2816,'offhand':285348})
    gear=after['gear_policy_result']['winner']['gear']
    assert gear['slots']['weapon']['item_id']==2816
    assert gear['slots']['offhand']['item_id']==285348
    assert gear['item_count']==len(gear['slots'])==18
    assert 'offhand' not in before['gear_policy_result']['winner']['gear']['slots']


def test_offhand_cannot_be_free_item_without_weapon_swap():
    with pytest.raises(ValueError,match='UNPAIRED_OFFHAND'):
        substituted_multi_stage(stage=stage(),class_key='druid',level=30,
                                swaps={'offhand':285348})


def test_offhand_cannot_pair_with_twohander():
    with pytest.raises(ValueError,match='P3_SWAP_ILLEGAL_EQUIPMENT'):
        substituted_multi_stage(stage=stage(),class_key='druid',level=30,
                                swaps={'weapon':279844,'offhand':285348})


def test_duplicate_ring_is_not_legal():
    with pytest.raises(ValueError):
        substituted_multi_stage(stage=stage(),class_key='druid',level=30,
                                swaps={'ring1':13097})


def test_p3_frontier_uses_only_source_legal_and_keeps_unknown():
    inv=checkpoint_item_l0(class_key='druid',level=30)
    jobs,counts,unknown,paired=source_legal_proposals(stage(),inv,json.loads(PRIOR.read_text()))
    assert inv['legal_item_count']==1974
    assert len(counts)==18
    assert set(counts)==set(inv['slot_frontiers'])
    assert counts['offhand']>0 and unknown['trinket1']>0
    assert any(x['slot']=='offhand' and x['swaps'].get('weapon')==paired for x in jobs)
    legal={(r['item_id'],slot) for r in inv['source_items'] for slot in r['slots']}
    assert all((j['item_id'],j['slot']) in legal for j in jobs)
    assert any(j['unresolved_effects'] for j in jobs)


def test_empirical_model_uses_real_complete_swaps_and_reports_uncertainty():
    from src.game.data.forever.source_checkpoint_p3_empirical_weights import fit_swap_weights
    root=Path(__file__).resolve().parents[1]
    evidence=json.loads((root/'evidence/wf358/WF358_L30_P3_TOP5_DIRECT_REPLAYS.json').read_text())
    model=fit_swap_weights(stage=stage(),results=evidence['results'],
        baseline_s_per_mob=evidence['baseline']['mean_s_per_mob'],class_key='druid',level=30)
    assert model['status']=='MEASURED_100MOB_REGULARIZED_NONLINEAR_UNCERTAINTY'
    assert model['n']>=8
    assert model['cv_mae_s_per_mob']>=0
    assert all('status' in w for w in model['weights'].values())
    assert all('actual_improvement_s_per_mob' in r for r in model['per_item'])


def test_empirical_model_does_not_promote_unresolved_item_to_measured():
    from src.game.data.forever.source_checkpoint_p3_empirical_weights import fit_swap_weights
    root=Path(__file__).resolve().parents[1]
    evidence=json.loads((root/'evidence/wf358/WF358_L30_P3_TOP5_DIRECT_REPLAYS.json').read_text())
    unresolved={'slot':'trinket1','item_id':271905,'swaps':{'trinket1':271905},
                'unresolved_effects':['unknown_proc'],
                'result':{'status':'COMPLETE','mean_s_per_mob':1.}}
    model=fit_swap_weights(stage=stage(),results=evidence['results']+[unresolved],
        baseline_s_per_mob=evidence['baseline']['mean_s_per_mob'],class_key='druid',level=30)
    assert not any(r['item_id']==271905 for r in model['per_item'])


def test_contextual_report_is_explicitly_not_a_global_top5_certificate():
    from tools.wf358_l30_p3_empirical_report import run
    report=run()
    assert report['p3_status'].startswith('FAIL_')
    assert report['l0_item_count']==report['legal_item_count']==1974
    assert len(report['slots'])==18
    assert all(x['ranking_scope']=='MEASURED_CHALLENGERS_NOT_ALL_SOURCE_ITEMS'
               for x in report['slots'].values())
    assert report['slots']['relic']['all_source_legal_proxy']['evaluated_legal_equipment_packages']==1
    assert report['slots']['shirt']['all_source_legal_proxy']['evaluated_legal_equipment_packages']==2
    assert report['slots']['offhand']['all_source_legal_proxy']['evaluated_legal_equipment_packages']>0
    assert report['slots']['trinket1']['all_source_legal_proxy']['unidentified_item_count']>0
    assert report['slots']['ring1']['all_source_legal_proxy']['evaluated_legal_equipment_packages'] < report['slots']['ring1']['legal_item_count']
    for slot,section in report['slots'].items():
        rows=section['all_source_legal_proxy']['known_component_top5']
        assert len(rows)==min(5,section['all_source_legal_proxy']['evaluated_legal_equipment_packages'])
        assert all('source_url' in r and 'stat_contributions' in r and 'unidentified_stats' in r for r in rows)
        assert all(r['full_proxy_certainty'] or r['unidentified_stats'] or r['unresolved_source_effects'] for r in rows)



def test_controlled_100mob_weights_do_not_zero_survival_discontinuity():
    from src.game.data.forever.source_checkpoint_p3_causal_summary import summarize_causal_probes
    root=Path(__file__).resolve().parents[1]
    raw=json.loads((root/'evidence/wf358/WF358_L30_CAUSAL_STAT_100MOB.json').read_text())
    result=summarize_causal_probes(raw)
    assert result['completed']<result['attempted']
    assert result['axes']['strength']['weight_s_saved_per_mob_per_raw_unit'] is None
    assert result['axes']['agility']['weight_s_saved_per_mob_per_raw_unit'] is None
    assert result['axes']['healing']['weight_s_saved_per_mob_per_raw_unit'] is None
    assert result['axes']['weapon_dps']['weight_s_saved_per_mob_per_raw_unit']>0
    assert result['axes']['health_regeneration_per_5s']['weight_s_saved_per_mob_per_raw_unit']>0
    assert result['axes']['crit']['status']=='OBSERVED_ZERO_ONLY_IN_TESTED_RANGE'
