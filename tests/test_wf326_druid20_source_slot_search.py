"""Druid L20: legal source-item coordinate search and forged-gear rejection."""
from copy import deepcopy
from src.game.data.forever.gear import select_named_gear
from src.game.data.forever.source_named_gear_proof import audit_named_gear_source
from src.v2.source_persistent_slot_search import _source_slot_proposals,_gear_replace


def _seed():
    return select_named_gear(class_key='druid',level=20,
        stat_weights={'strength':1.,'agility':.3,'stamina':.1},
        role='druid_feral',required_level_policy='observed').as_dict()


def test_druid_l20_slot_proposals_are_real_legal_distinct_items():
    base=_seed()
    proposals,counts=_source_slot_proposals(class_key='druid',level=20,base=base,
                                             per_slot=3,max_proposals=48)
    assert len(proposals)>=25
    assert counts['weapon']>50 and counts['head']>1
    assert len({(slot,item.item_id) for slot,item in proposals})==len(proposals)
    for slot,item in proposals:
        updated=_gear_replace(base,slot,item)
        audit=audit_named_gear_source(class_key='druid',level=20,gear=updated)
        assert audit['equipment_legality_complete'],(slot,item.item_id,audit)
        assert updated['slots'][slot]['item_id']==item.item_id
        assert updated['slots'][slot]['item_id']!=base['slots'][slot]['item_id']


def test_exact_source_stats_slot_and_aggregate_are_fail_closed():
    base=_seed()
    assert audit_named_gear_source(class_key='druid',level=20,gear=base)['equipment_legality_complete']
    bad=deepcopy(base);bad['slots']['head']['strength']+=200
    assert not audit_named_gear_source(class_key='druid',level=20,gear=bad)['equipment_legality_complete']
    bad=deepcopy(base);bad['aggregate_stats']['strength']+=200
    assert not audit_named_gear_source(class_key='druid',level=20,gear=bad)['equipment_legality_complete']
    bad=deepcopy(base);bad['slots']['head']=deepcopy(base['slots']['chest'])
    assert not audit_named_gear_source(class_key='druid',level=20,gear=bad)['equipment_legality_complete']
    bad=deepcopy(base);bad['slots']['ring2']=deepcopy(base['slots']['ring1'])
    assert not audit_named_gear_source(class_key='druid',level=20,gear=bad)['equipment_legality_complete']


def test_missing_acquisition_method_is_not_fake_possession_blocker():
    audit=audit_named_gear_source(class_key='druid',level=20,gear=_seed())
    assert audit['equipment_legality_complete']
    assert audit['sourced_acquisition_methods']==0
    assert audit['acquisition_method_coverage_complete'] is False
    assert 'loot' in audit['note'].lower()


def test_actual_persistent_candidate_preparation_rejects_forged_source_gear():
    import json
    from pathlib import Path
    from src.v2.source_persistent_joint_finalists import prepare_candidate
    fixture=json.loads(Path('evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())
    stage=deepcopy(fixture['finalist']['winner']['stage'])
    stage['gear_policy_result']['winner']['gear']['aggregate_stats']['strength']+=100
    try:
        prepare_candidate(class_key='druid',level=20,stage=stage)
    except ValueError as exc:
        assert 'BLOCKED_NAMED_GEAR_CATALOGUE_LEGALITY_OR_STATS' in str(exc)
    else:
        assert False,'the actual L2 candidate path accepted forged stats'
