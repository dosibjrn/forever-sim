"""WF426: source chance-stat gear must be a paid, legal cold-search axis.

No item IDs are used by the optimizer. The explicit known source item ID is
used only as an independent regression witness for canonical item data.
"""
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.v2.source_bounded_joint_frontier import source_cold_start_stage
from src.v2.source_persistent_slot_search import _source_stat_package_proposals
from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
from src.rulesets.forever.items.runtime_selection import available_items,item_scoring_vector
from src.game.data.forever.source_named_gear_proof import audit_named_gear_source


def _source():
    ir=build_game_ir_slice(class_key='druid',level=20)
    stage=source_cold_start_stage(class_key='druid',level=20,source_ir=ir,gear_role='druid_feral')
    return ir,stage


def test_cold_two_stat_packages_include_actual_source_crit_item():
    ir,stage=_source()
    base=stage['gear_policy_result']['winner']['gear']
    proposals,report=_source_stat_package_proposals(class_key='druid',level=20,
        base=base,max_packages=2)
    assert [axis for axis,_ in proposals]==['spell_power','crit']
    crit=dict(proposals)['crit']
    assert 'hands' in crit
    selected=substituted_multi_stage(stage=stage,class_key='druid',level=20,swaps=crit)
    gear=selected['gear_policy_result']['winner']['gear']
    assert gear['slots']['hands']['item_id']==7348  # independent source witness
    assert gear['slots']['hands']['crit_rating']==14
    assert audit_named_gear_source(class_key='druid',level=20,gear=gear)['equipment_legality_complete']
    assert report['historical_winner_as_seed'] is False


def test_source_absent_hit_does_not_consume_quota_or_fabricate_positive_hit():
    ir,stage=_source()
    base=stage['gear_policy_result']['winner']['gear']
    items=available_items('druid',20,required_level_policy='observed')
    assert not any(item_scoring_vector(item)['hit']>0 for item in items)
    proposals,_=_source_stat_package_proposals(class_key='druid',level=20,
        base=base,max_packages=4)
    assert 'hit' not in dict(proposals)
    assert 'crit' in dict(proposals)


def test_crit_package_changes_actual_100mob_runtime_not_only_gear_score():
    ir,stage=_source()
    proposals,_=_source_stat_package_proposals(class_key='druid',level=20,
        base=stage['gear_policy_result']['winner']['gear'],max_packages=2)
    crit_stage=substituted_multi_stage(stage=stage,class_key='druid',level=20,
        swaps=dict(proposals)['crit'])
    selection={'furor':5,'ferocity':5,'improved_wrath':5,'feral_instinct':1}
    results=[]
    for current in (stage,crit_stage):
        candidate=prepare_candidate(class_key='druid',level=20,stage=current,
            allocation_override=selection,source_ir=ir,bonus_talent_points=5,
            allow_partial_gear_stats=True)
        result=evaluate_persistent_candidate(candidate,level=20,mobs=100,
            max_wall_s=15.)
        assert result['status']=='COMPLETE' and result['count']==100
        results.append((result,candidate))
    assert results[1][1].ir.actor.base_stats['spell_crit_chance'] >= .01
    assert results[0][0]['events']>0 and results[1][0]['events']>0
    assert abs(results[0][0]['mean_s_per_mob']-results[1][0]['mean_s_per_mob'])>1e-6


def test_source_chance_axis_is_class_neutral_and_legal_at_level_30():
    for class_key,role in (('mage','mage'),('druid','druid_balance')):
        ir=build_game_ir_slice(class_key=class_key,level=30)
        stage=source_cold_start_stage(class_key=class_key,level=30,
            source_ir=ir,gear_role=role)
        props,_=_source_stat_package_proposals(class_key=class_key,level=30,
            base=stage['gear_policy_result']['winner']['gear'],max_packages=3)
        assert 'crit' in dict(props)
        changed=substituted_multi_stage(stage=stage,class_key=class_key,
            level=30,swaps=dict(props)['crit'])
        gear=changed['gear_policy_result']['winner']['gear']
        assert audit_named_gear_source(class_key=class_key,level=30,
            gear=gear)['equipment_legality_complete']
        assert sum(float(x['crit_rating']) for x in gear['slots'].values())>0
