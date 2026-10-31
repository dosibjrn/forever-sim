"""Warrior L30 P2 source legality, negative cases and Druid isolation."""
from __future__ import annotations
import json,sqlite3
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import (P2Checkpoint,evaluate_p2,
    evaluate_p2_allocation_l0,check_structural_allocation)
from tools.wf362_stage_warrior30_talents import SOURCE,TARGET,BASE,stage

@pytest.fixture(scope='module')
def prepared():
    stage()
    ir=build_game_ir_slice(class_key='warrior',level=30,ability_db_path=TARGET)
    cp=P2Checkpoint('warrior',30)
    cert=evaluate_p2(ir,cp,source_observations_path=SOURCE,
        spellbook_path=SOURCE.parents[2]/'evidence/wf361/warrior_spellbook_70338_level1_30.json')
    return ir,cp,cert

def test_source_catalogue_complete_current_and_retired(prepared):
    ir,_,cert=prepared;data=json.loads(SOURCE.read_text())
    assert len(ir.talents)==52
    assert len(data['observations'])==44
    assert len(data['retired_indexed_talent_ids'])==4
    assert {t.id for t in ir.talents}=={r['talent_id'] for r in data['catalogue']}
    assert not {t.id for t in ir.talents}&set(data['retired_indexed_talent_ids'])
    assert {t.tree_key for t in ir.talents}=={'arms','fury','protection'}
    assert ir.provenance['talent_tree_rules']['points_per_row']==5

def test_reachable_exact_denominator(prepared):
    ir,cp,cert=prepared
    assert cert['p2_pass'] and len(cert['rank_rows'])==117
    assert cert['l0_scored_reachable_rank_count']==117
    assert not cert['blocked'] and not cert['source_rank_mismatches']
    assert not cert['unknown_position_families']
    assert all(sum(row['witness'].values())<=21 for row in cert['rank_rows'])
    assert sum(t.metadata['row']>=5 for t in ir.talents)==8
    assert all(row['tier_row']<=4 for row in cert['rank_rows'])
    assert all(row['rank']==1 for row in cert['rank_rows'] if row['tier_row']==4)

def test_all_rank_witnesses_compose(prepared):
    ir,cp,cert=prepared
    for row in cert['rank_rows']:
        result=evaluate_p2_allocation_l0(cert,ir,row['witness'],cp)
        assert result['rankable'] and result['effects']
        assert result['scalar_s_per_mob_predicted'] is False

def test_mixed_trees_and_interaction_ledger(prepared):
    ir,cp,cert=prepared
    allocation={'cruelty':5,'improved_rend':3,'improved_bloodrage':2,
                'deflection':5,'booming_voice':5,'shield_specialization':1}
    assert sum(allocation.values())==21
    result=evaluate_p2_allocation_l0(cert,ir,allocation,cp)
    assert result['rankable'] and len(result['effects'])==6
    assert result['point_spend']==21

def test_reject_tier_skip_and_prerequisite(prepared):
    ir,cp,cert=prepared
    with pytest.raises(ValueError,match='P2_TIER_GATE'):
        check_structural_allocation(ir,{'weaponmaster':1},cp)
    with pytest.raises(ValueError,match='P2_PREREQUISITE_GATE'):
        check_structural_allocation(ir,{'improved_tactical_mastery':1,
            'improved_rend':3,'deflection':5,'improved_heroic_strike':2,
            'anger_management':1},cp)
    with pytest.raises(ValueError,match='P2_TALENT_RANK_INVALID'):
        check_structural_allocation(ir,{'cruelty':6},cp)
    with pytest.raises(ValueError,match='P2_UNKNOWN_TALENT'):
        check_structural_allocation(ir,{'toughness':1},cp)

def test_conditional_effects_not_silent_zero(prepared):
    ir,cp,cert=prepared
    rows={(r['talent_id'],r['rank']):r for r in cert['rank_rows']}
    assert rows['sweeping_strikes',1]['l0_effects'][0]['context_status']=='ZERO_SOLO_NO_COMPETING_THREAT_TARGET'
    assert any(e['domain']=='weapon_conditional_extra_attack_chance_pct'
        for e in rows['weaponmaster',1]['l0_effects'])
    assert any(e['domain']=='out_of_combat_rage_loss_reduction_pct'
        for e in rows['anger_management',1]['l0_effects'])
    assert rows['weaponmaster',1]['context_uncertainty']
    assert cert['l2_unsupported_scored_rank_count']>=100

def test_canonical_sqlite_unmodified_and_staged_integrity(prepared):
    with sqlite3.connect(BASE) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoint_talent_source_catalogue'").fetchone()
    with sqlite3.connect(TARGET) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT count(*) FROM checkpoint_talent_source_catalogue').fetchone()[0]==1

def test_druid_l30_existing_staged_p2_unchanged():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    db=root/'data/forever/staged_druid_l30_talents_70338.sqlite'
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
    cert=evaluate_p2(ir,P2Checkpoint('druid',30),
        source_observations_path=root/'evidence/wf350/druid_l30_source_talent_catalogue_70338.json',
        spellbook_path=root/'evidence/wf348/druid_spellbook_70338_level1_30.json')
    assert cert['p2_pass'] and cert['known_reachable_rank_count']==117

def test_staged_source_hash_fails_closed(prepared,tmp_path):
    import shutil
    db=tmp_path/'tampered.sqlite';shutil.copyfile(TARGET,db)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE checkpoint_talent_source_catalogue SET source_json=source_json||' '")
    with pytest.raises(ValueError,match='STAGED_TALENT_SOURCE_HASH_MISMATCH'):
        build_game_ir_slice(class_key='warrior',level=30,ability_db_path=db)

def test_missing_current_talent_fails_closed(prepared,tmp_path):
    import hashlib,shutil
    db=tmp_path/'incomplete.sqlite';shutil.copyfile(TARGET,db)
    with sqlite3.connect(db) as con:
        raw=con.execute('SELECT source_json FROM checkpoint_talent_source_catalogue').fetchone()[0]
        data=json.loads(raw)
        data['catalogue']=[r for r in data['catalogue'] if r['talent_id']!='cruelty']
        data['observations']=[r for r in data['observations'] if r['talent_id']!='cruelty']
        new=json.dumps(data,sort_keys=True)
        con.execute('UPDATE checkpoint_talent_source_catalogue SET source_json=?,source_sha256=?',
                    (new,hashlib.sha256(new.encode()).hexdigest()))
    with pytest.raises(ValueError,match='STAGED_TALENT_SOURCE_INVENTORY_MISMATCH'):
        build_game_ir_slice(class_key='warrior',level=30,ability_db_path=db)
