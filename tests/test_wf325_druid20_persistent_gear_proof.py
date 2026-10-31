from pathlib import Path
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


def test_persistent_real_runtime_charges_event_budget_even_when_incomplete(tmp_path,monkeypatch):
    import sqlite3
    import json
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    from src.game.data.forever.source_db_scope import ability_source_scope
    from src.game.data.forever.source_observed_rank_parity import ingest_observations
    from tools.wf321_ingest_control_observations import ingest as ingest_control
    from src.game.data.forever.registry import build_game_ir_slice
    from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
    stage_db=tmp_path/'stage.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as original,sqlite3.connect(stage_db) as dst:
        original.backup(dst)
    ingest_observations(stage_db,Path('evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json'))
    ingest_control(stage_db,Path('evidence/wf321/druid_l20_control_observations.json'))
    # WF324's archived equipment combination predates source Unique-Equipped legality.
    # Budget regression uses the current source-legal paid replay.
    sample=json.loads(Path('evidence/wf325/WF325_REPLAYED_BUDGETED_L2_AND_100MOB.json').read_text())['finalist']['winner']['stage']
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-13')
    with ability_source_scope(stage_db):
        source=build_game_ir_slice(class_key='druid',level=20,ability_db_path=stage_db)
        prepared=prepare_candidate(class_key='druid',level=20,stage=sample,source_ir=source)
        tiny=evaluate_persistent_candidate(prepared,level=20,mobs=100,max_total_events=5)
        assert tiny['status']=='BLOCKED_EVALUATION_COMPUTE_BUDGET'
        assert 0 < tiny['events'] <= 5
        assert tiny['mob_completed']<100
        bounded=evaluate_persistent_candidate(prepared,level=20,mobs=100,max_total_events=14000,max_cpu_s=8)
        assert bounded['status']=='COMPLETE'
        assert bounded['events']<=14000
        assert bounded['elapsed_cpu_s']>0
        assert bounded['count']==100


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
