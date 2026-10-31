"""Source-only whole-gear search proposals: no historic winner seeds."""
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_bounded_joint_frontier import source_cold_start_stage
from src.v2.source_persistent_slot_search import _source_stat_package_proposals
from src.game.data.forever.source_checkpoint_p3_swaps import substituted_multi_stage
from src.game.data.forever.source_named_gear_proof import audit_named_gear_source


def test_stat_package_frontier_is_reachable_and_replaces_multiple_slots():
    ir = build_game_ir_slice(class_key='druid',level=20)
    seed = source_cold_start_stage(class_key='druid',level=20,source_ir=ir,gear_role='druid_feral')
    base = seed['gear_policy_result']['winner']['gear']
    proposals,report = _source_stat_package_proposals(class_key='druid',level=20,base=base,max_packages=4)
    assert proposals and len(proposals)<=4
    assert any(len(changes)>1 for _,changes in proposals)
    assert report['authority']=='CANONICAL_SOURCE_SQLITE'
    assert report['historical_winner_as_seed'] is False
    assert 'spell_power' in {k for k,_ in proposals}
    for label,changes in proposals:
        altered=substituted_multi_stage(stage=seed,class_key='druid',level=20,swaps=changes)
        gear=altered['gear_policy_result']['winner']['gear']
        assert audit_named_gear_source(class_key='druid',level=20,gear=gear)['equipment_legality_complete']
        assert gear['item_count']==len(gear['slots'])
        assert len({v['item_id'] for v in gear['slots'].values()})==len(gear['slots'])


def test_stat_package_frontier_has_no_class_specific_druid_branch():
    ir=build_game_ir_slice(class_key='mage',level=30)
    seed=source_cold_start_stage(class_key='mage',level=30,source_ir=ir,gear_role='mage')
    props,report=_source_stat_package_proposals(class_key='mage',level=30,
        base=seed['gear_policy_result']['winner']['gear'],max_packages=3)
    assert len(props)>=1
    for _,changes in props:
        altered=substituted_multi_stage(stage=seed,class_key='mage',level=30,swaps=changes)
        assert altered['gear_policy_result']['winner']['gear']['item_count']>=12
