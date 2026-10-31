"""Druid L20: real Forever Unique-Equipped group, no synthetic item legality."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sqlite3
import pytest

from src.rulesets.forever.items.runtime_selection import available_items,select_gear,gear_overrides
from src.rulesets.forever.items.source_equipment_semantics import (
    source_equipment_semantics,validate_equipped_item_ids,ledger_path)
from src.game.data.forever.gear import select_named_gear
from src.game.data.forever.source_named_gear_proof import audit_named_gear_source
from src.v2.source_persistent_slot_search import _source_slot_proposals,_gear_replace


def test_source_unique_group_evidence_and_denominator():
    evidence=source_equipment_semantics()
    assert len(evidence)==8
    assert evidence[21566].equip_group==evidence[21568].equip_group=='Rune of Battle'
    assert evidence[21566].equip_limit==evidence[21568].equip_limit==1
    assert evidence[273298].equip_group=='Unique item:273298'
    assert evidence[273298].equip_semantics=='EQUIPPABLE_NONCOMBAT_USE'
    assert len(available_items('druid',20,required_level_policy='observed'))==1171
    with pytest.raises(ValueError,match='BLOCKED_SOURCE_UNIQUE_EQUIPPED_GROUP'):
        validate_equipped_item_ids((21566,21568))
    validate_equipped_item_ids((21566,273298))


def test_default_selector_does_not_equip_two_runes_of_battle():
    # This selected both in WF344, despite the same Unique-Equipped group.
    chosen=select_gear('druid',20,'druid_feral',required_level_policy='observed')
    ids=[x.item_id for x in chosen.values()]
    validate_equipped_item_ids(ids)
    assert 21566 in ids
    assert 21568 not in ids
    assert 273298 in ids
    from src.game.data.forever.source_checkpoint_p3 import source_item_l0
    row=next(x for x in available_items('druid',20,required_level_policy='observed') if x.item_id==273298)
    assert source_item_l0(row)['unresolved_effects']==[]
    strict=select_gear('druid',20,'druid_feral',required_level_policy='observed',exclude_unknown_item_effects=True)
    assert {strict['trinket1'].item_id,strict['trinket2'].item_id}=={21566,273298}
    with gear_overrides({'trinket1':21566,'trinket2':21568}):
        with pytest.raises(ValueError,match='BLOCKED_SOURCE_UNIQUE_EQUIPPED_GROUP'):
            select_gear('druid',20,'druid_feral',required_level_policy='observed')


def test_audit_rejects_forged_legal_group_pair_and_coordinate_filters_it():
    named=select_named_gear(class_key='druid',level=20,role='druid_feral',
        stat_weights={'stamina':1},required_level_policy='observed').as_dict()
    rows={x.item_id:x for x in available_items('druid',20,required_level_policy='observed')}
    assert audit_named_gear_source(class_key='druid',level=20,gear=named)['equipment_legality_complete']
    bad=_gear_replace(named,'trinket1',rows[21566])
    with pytest.raises(ValueError,match='BLOCKED_SOURCE_UNIQUE_EQUIPPED_GROUP'):
        _gear_replace(bad,'trinket2',rows[21568])
    # Construct a validly stat-aggregated but illegal pair without using the
    # guarded coordinate mutation. The final source audit must still reject it.
    from src.rulesets.forever.items.runtime_selection import item_payload,effective_level,item_vector
    bad=deepcopy(named)
    for slot,iid in (('trinket1',21566),('trinket2',21568)):
        bad['slots'][slot]=item_payload(rows[iid],display_slot=slot,effective_level=effective_level(rows[iid]))
    stats={}
    for x in bad['slots'].values():
        row=rows[int(x['item_id'])]
        for k,v in item_vector(row).items():stats[k]=stats.get(k,0.)+float(v)
    bad['aggregate_stats']=stats
    audit=audit_named_gear_source(class_key='druid',level=20,gear=bad)
    assert not audit['equipment_legality_complete']
    assert any(x['source_status']=='BLOCKED_SOURCE_UNIQUE_EQUIPPED_GROUP' for x in audit['items'])
    proposals,counts=_source_slot_proposals(class_key='druid',level=20,base=named,
        per_slot=10,max_proposals=200)
    for slot,item in proposals:
        ids=[int(x['item_id']) for k,x in named['slots'].items() if k!=slot]+[int(item.item_id)]
        validate_equipped_item_ids(ids)


def test_source_group_evidence_tampering_rejected(tmp_path,monkeypatch):
    source=ledger_path();staged=tmp_path/'sem.sqlite'
    with sqlite3.connect(source) as a,sqlite3.connect(staged) as b:a.backup(b)
    with sqlite3.connect(staged) as db:
        db.execute("UPDATE source_item_equipment_semantics SET equip_group='Forged' WHERE item_id=21566")
    monkeypatch.setenv('FOREVER_ITEM_EQUIPMENT_SEMANTICS',str(staged))
    with pytest.raises(ValueError,match='ITEM_EQUIPMENT_GROUP_SOURCE_MISMATCH'):
        source_equipment_semantics()


def test_group_limit_inconsistent_with_same_group_rejected(tmp_path,monkeypatch):
    source=ledger_path();staged=tmp_path/'sem.sqlite'
    with sqlite3.connect(source) as a,sqlite3.connect(staged) as b:a.backup(b)
    with sqlite3.connect(staged) as db:
        db.execute("UPDATE source_item_equipment_semantics SET equip_limit=2 WHERE item_id=21568")
    monkeypatch.setenv('FOREVER_ITEM_EQUIPMENT_SEMANTICS',str(staged))
    with pytest.raises(ValueError,match='ITEM_EQUIPMENT_GROUP_SOURCE_MISMATCH'):
        source_equipment_semantics()


def test_independent_p4_p5_replay_uses_legal_trinket_and_new_semantics():
    import json
    root=Path(__file__).resolve().parents[1]
    p4=json.loads((root/'evidence/wf345/WF345_P4_30S.json').read_text())
    p5=json.loads((root/'evidence/wf345/WF345_P5_300S.json').read_text())
    from hashlib import sha256
    # Historical WF345 evidence is pinned to its OWN ledger SHA; WF346 later
    # extended the ledger. Never rewrite the historical source identity.
    assert p4['equipment_semantics_sha256']==p5['equipment_semantics_sha256']
    assert p4['equipment_semantics_sha256']!=sha256(ledger_path().read_bytes()).hexdigest()
    assert p4['item_catalogue_sha256']==p5['item_catalogue_sha256']
    assert p4['staged_source_sha256']==p5['staged_source_sha256']
    assert p4['full_wall_s']<=30 and p5['full_wall_s']<=300
    assert p5['distinct_paid_complete_stages_lower_bound']>p4['distinct_paid_complete_stages_lower_bound']
    assert p4['winner']['actual_100mob_s_per_mob']<=1.01*p5['winner']['actual_100mob_s_per_mob']
    assert p4['winner']['gear']['trinket1']==p5['winner']['gear']['trinket1']==273298
    assert p4['winner']['actual_100mob_events']==p5['winner']['actual_100mob_events']
    for run in (p4,p5):
        validate_equipped_item_ids(run['winner']['gear'].values())
        assert run['total_events']==run['joint_events']+run['persistent_events']
        assert run['winner']['actual_100mob_s_per_mob']>0
        assert run['oracle_seeded'] is False
