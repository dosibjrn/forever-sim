from src.game.data.forever.gear import select_named_gear
from src.game.data.forever.source_named_gear_proof import audit_named_gear_source
from src.v2.source_persistent_joint_finalists import persistent_winner_source_manifest


def test_real_druid_l20_gear_legal_but_method_unverified():
    gear=select_named_gear(class_key='druid',level=20,
                           stat_weights={'strength':2,'agility':2,'stamina':1},
                           role='druid_feral',required_level_policy='observed').as_dict()
    proof=audit_named_gear_source(class_key='druid',level=20,gear=gear)
    assert proof['selected_slots'] >= 10
    assert proof['legal_slots']==proof['selected_slots']
    assert proof['equipment_legality_complete'] is True
    assert proof['sourced_acquisition_methods']==0
    assert proof['acquisition_method_coverage_complete'] is False
    assert proof['formal_gear_acceptance'] is False
    assert all(row['availability_status']=='UNKNOWN_ACQUISITION_METHOD' for row in proof['items'])


def test_item_name_or_level_tampering_is_not_source_valid():
    gear=select_named_gear(class_key='druid',level=20,
                           stat_weights={'strength':2,'agility':2,'stamina':1},
                           role='druid_feral',required_level_policy='observed').as_dict()
    key=next(iter(gear['slots']))
    gear['slots'][key]['name']='forged fake item name'
    proof=audit_named_gear_source(class_key='druid',level=20,gear=gear)
    assert proof['equipment_legality_complete'] is False
    assert proof['formal_gear_acceptance'] is False


def test_no_gear_or_no_winner_fails_closed():
    assert persistent_winner_source_manifest(class_key='druid',level=20,winner=None)['formal_checkpoint_accepted'] is False
    try:
        audit_named_gear_source(class_key='druid',level=20,gear={})
    except ValueError as e:
        assert 'BLOCKED_MISSING_NAMED_ITEM_SLOTS' in str(e)
    else:
        assert False


def test_gear_stat_and_slot_forgery_fails_before_l2():
    from copy import deepcopy
    gear=select_named_gear(class_key='druid',level=20,
        stat_weights={'strength':2,'agility':2,'stamina':1},
        role='druid_feral',required_level_policy='observed').as_dict()
    assert audit_named_gear_source(class_key='druid',level=20,gear=gear)['equipment_legality_complete']
    fake=deepcopy(gear);fake['aggregate_stats']['strength']+=100
    assert not audit_named_gear_source(class_key='druid',level=20,gear=fake)['equipment_legality_complete']
    fake=deepcopy(gear);fake['slots']['chest']['strength']+=100
    assert not audit_named_gear_source(class_key='druid',level=20,gear=fake)['equipment_legality_complete']
    fake=deepcopy(gear);fake['slots']['chest']=deepcopy(fake['slots']['head'])
    assert not audit_named_gear_source(class_key='druid',level=20,gear=fake)['equipment_legality_complete']
    fake=deepcopy(gear);fake['slots']['ring2']=deepcopy(fake['slots']['ring1'])
    assert not audit_named_gear_source(class_key='druid',level=20,gear=fake)['equipment_legality_complete']
