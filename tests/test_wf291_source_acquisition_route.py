"""WF291: source entity, local event, and real L2 acquisition-gated route tests."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import shutil
import sqlite3

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_acquisition_events import (
    AcquisitionCharacterState, AcquisitionEvent,
    apply_source_consistent_acquisition, verified_source_acquisition_entities)
from src.v2.source_budgeted_level_route import search_source_bounded_level_route


def _npc_case():
    entities=verified_source_acquisition_entities(class_key='mage',spell_id=122)
    return next(e for e in entities if e['method']=='taught_by_npc' and e['entity_id']==328)


def _mage_state():
    return AcquisitionCharacterState('mage',10,12,400,
                                     learned_spell_ids=frozenset({205,143,2136}))


def _mage_event():
    return AcquisitionEvent('taught_by_npc',122,328,12)


def test_source_verified_entities_are_typed_and_batch_rechecked():
    with sqlite3.connect(DEFAULT_DB) as db:
        rows=db.execute('''SELECT class_key,spell_id,methods_observed_json
            FROM ability_acquisition_evidence WHERE methods_observed_json!='{}'
            ORDER BY class_key,spell_id''').fetchall()
        assert len(rows)==18
        assert db.execute('SELECT COUNT(*) FROM ability_acquisition_entities').fetchone()[0]==405
    seen=set()
    for cls,sid,_ in rows:
        import json
        methods=json.loads(_)
        if not any(k in methods for k in ('taught_by_npc','taught_by_item','reward_from_quest')):
            continue
        entities=verified_source_acquisition_entities(class_key=cls,spell_id=sid)
        assert entities
        seen.add(cls)
    assert seen=={'druid','hunter','mage','priest','rogue','shaman','warlock','warrior'}
    with pytest.raises(ValueError,match='detail'):
        verified_source_acquisition_entities(class_key='paladin',spell_id=122)


def test_local_trainer_transition_charges_price_and_records_non_world_status():
    state,record=apply_source_consistent_acquisition(_mage_state(),_mage_event())
    assert state.copper==0
    assert 122 in state.learned_spell_ids
    assert record['source_entity_id']==328
    assert record['local_preconditions_checked'] is True
    assert record['world_route_proven'] is False
    assert record['actual_player_event_observed'] is False
    with pytest.raises(ValueError,match='already learned'):
        apply_source_consistent_acquisition(state,_mage_event())


@pytest.mark.parametrize('state,event,error',[ 
    (AcquisitionCharacterState('mage',9,12,400),_mage_event(),'level'),
    (AcquisitionCharacterState('mage',10,12,399),_mage_event(),'currency'),
    (AcquisitionCharacterState('mage',10,1519,400),_mage_event(),'zone'),
    (_mage_state(),AcquisitionEvent('taught_by_npc',122,328,1519),'zone'),
    (_mage_state(),AcquisitionEvent('taught_by_npc',122,999999,12),'not in verified'),
    (_mage_state(),AcquisitionEvent('reward_from_quest',122,328),'not in verified'),
    (_mage_state(),AcquisitionEvent('used_by_item',122,328),'unsupported'),
])
def test_bad_trainer_event_is_rejected(state,event,error):
    with pytest.raises(ValueError,match=error):
        apply_source_consistent_acquisition(state,event)


def test_quest_and_item_are_distinct_methods_not_free_spells():
    quest=AcquisitionEvent('reward_from_quest',71,1498)
    item=AcquisitionEvent('taught_by_item',71,6619)
    initial=AcquisitionCharacterState('warrior',10,12,0)
    with pytest.raises(ValueError,match='quest completion'):
        apply_source_consistent_acquisition(initial,quest)
    with pytest.raises(ValueError,match='not in inventory'):
        apply_source_consistent_acquisition(initial,item)
    acquired,rec=apply_source_consistent_acquisition(
        replace(initial,completed_quest_ids=frozenset({1498})),quest)
    assert 71 in acquired.learned_spell_ids and rec['method']=='reward_from_quest'
    acquired,rec=apply_source_consistent_acquisition(
        replace(initial,inventory_item_ids=frozenset({6619})),item)
    assert 71 in acquired.learned_spell_ids and 6619 not in acquired.inventory_item_ids
    assert rec['method']=='taught_by_item' and not rec['world_route_proven']


def test_stale_source_entity_cannot_authorize_local_event(tmp_path):
    path=tmp_path/'abilities.sqlite'
    shutil.copy2(DEFAULT_DB,path)
    with sqlite3.connect(path) as db:
        db.execute('''UPDATE ability_acquisition_entities SET entity_name='Fake trainer'
            WHERE class_key='mage' AND spell_id=122 AND entity_id=328''')
        db.commit()
    with pytest.raises(ValueError,match='source mismatch'):
        apply_source_consistent_acquisition(_mage_state(),_mage_event(),db_path=path)


def test_local_acquisition_proof_is_not_accepted_as_world_route():
    from src.game.level_legality import LevelState, validate_level_state
    state=LevelState('mage',10,'human',{},('frost_nova:122',))
    # Race from actual source actor; this test must never rely on assumed race.
    from src.game.data.forever.registry import build_game_ir_slice
    ir=build_game_ir_slice(class_key='mage',level=10)
    state=replace(state,race_key=ir.actor.metadata.get('race_key'))
    with pytest.raises(ValueError,match='world acquisition not verified'):
        validate_level_state(state,require_world_acquisition=True)


def test_acquisition_gates_existing_real_l2_route_and_persists_learned_rank():
    result=search_source_bounded_level_route(class_key='mage',start_level=10,end_level=11,
        max_active_paths=1,max_children_per_path=1,max_l2_per_state=10,
        max_events_per_state=2000,max_total_events=4000,max_total_l2_attempts=20,
        initial_acquisition_state=_mage_state(),acquisition_events_by_level={10:(_mage_event(),)})
    assert result['bounded_contiguous_levels']==2
    assert result['source_player_action_filter_applied'] is True
    assert result['source_consistent_local_acquisition_events']==1
    assert result['accepted_class_level_checkpoints']==0
    assert result['full_route_complete'] is False
    assert result['compute']['l2_attempts']>=3
    assert result['compute']['event_transitions']>0
    assert [step['level'] for step in result['selected_route']]==[10,11]
    assert result['selected_route'][0]['source_acquisition_events'][0]['spell_id']==122
    assert result['selected_route'][1]['source_acquisition_events']==[]
    assert all(step['world_acquisition_verified'] is False for step in result['selected_route'])
    assert all(step['scratch_verification_complete'] for step in result['selected_route'])
    # The same IR can be searched only with explicitly acquired source IDs.
    blocked=search_source_bounded_level_route(class_key='mage',start_level=10,end_level=10,
        max_active_paths=1,max_children_per_path=1,max_l2_per_state=4,
        max_events_per_state=500,max_total_events=500,max_total_l2_attempts=4,
        initial_acquisition_state=AcquisitionCharacterState('mage',10,12,400),
        acquisition_events_by_level={10:(_mage_event(),)})
    assert blocked['accepted_class_level_checkpoints']==0
    assert all(set(step['source_action_ids']) <= {'frost_nova:122'}
               for step in blocked['selected_route'])
    assert all(step['world_acquisition_verified'] is False for step in blocked['selected_route'])


def test_acquisition_attempts_consume_shared_event_budget_even_if_failed():
    result=search_source_bounded_level_route(class_key='mage',start_level=10,end_level=10,
        max_active_paths=1,max_children_per_path=1,max_l2_per_state=10,
        max_events_per_state=500,max_total_events=2,max_total_l2_attempts=10,
        initial_acquisition_state=_mage_state(),
        acquisition_events_by_level={10:(_mage_event(),_mage_event())})
    assert result['accepted_class_level_checkpoints']==0
    assert result['compute']['acquisition_event_attempts']==2
    assert result['compute']['charged_total_events']==2
    assert result['compute']['l2_attempts']==0
    assert result['failures'][0]['reason']=='SOURCE_ACQUISITION_EVENT_BLOCKED'


def test_index_data_only_tamper_invalidates_event_authority(tmp_path):
    path=tmp_path/'abilities.sqlite'
    shutil.copy2(DEFAULT_DB,path)
    with sqlite3.connect(path) as db:
        db.execute('''UPDATE spell_index SET raw_listview_json='{}'
            WHERE class_key='mage' AND spell_id=122 AND kind='abilities' ''')
        db.commit()
    with pytest.raises(ValueError,match='missing/stale acquisition evidence'):
        apply_source_consistent_acquisition(_mage_state(),_mage_event(),db_path=path)
