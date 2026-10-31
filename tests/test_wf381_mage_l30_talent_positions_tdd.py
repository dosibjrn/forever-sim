"""WF381 source-stage RED: positions must reach canonical SQLite -> GameIR."""
from __future__ import annotations
from pathlib import Path
import json, shutil, sqlite3
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint,evaluate_p2,check_structural_allocation

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'evidence/wf381/mage_talent_positions_70374.json'


def _db(tmp_path, data=None):
    db=tmp_path/'staged.sqlite'
    shutil.copyfile(DEFAULT_DB,db)
    payload=(data if data is not None else json.loads(SOURCE.read_text()))
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE checkpoint_talent_source_positions (class_key TEXT NOT NULL,source_build TEXT NOT NULL,min_level INTEGER NOT NULL,source_sha256 TEXT NOT NULL,source_json TEXT NOT NULL,PRIMARY KEY(class_key,source_build,min_level))')
        import hashlib
        raw=json.dumps(payload,sort_keys=True)
        c.execute('INSERT INTO checkpoint_talent_source_positions VALUES (?,?,?,?,?)',('mage',payload['source_build'],30,hashlib.sha256(raw.encode()).hexdigest(),raw))
    return db


def test_all_54_current_mage_talents_are_scoped_from_sqlite(tmp_path):
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=_db(tmp_path),use_runes=False)
    source=json.loads(SOURCE.read_text())
    actual={t.id:t for t in ir.talents}
    assert set(actual)=={r['talent_id'] for r in source['talents']}
    assert all(actual[r['talent_id']].tree_key==r['tree_key'] and
               actual[r['talent_id']].metadata['row']==r['row'] and
               actual[r['talent_id']].max_rank==r['max_rank'] for r in source['talents'])
    assert actual['heating_up'].prerequisite=={'talent_id':'pyroblast','required_rank':1}
    assert actual['fingers_of_frost'].prerequisite=={'talent_id':'ice_lance','required_rank':1}
    assert all(len(t.ranks)==t.max_rank for t in actual.values())
    assert all(not r.modifiers for t in actual.values() if t.metadata.get('source_position_only')
               for r in t.ranks)


def test_p2_legal_allocation_uses_current_tiers_and_prerequisites(tmp_path):
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=_db(tmp_path),use_runes=False)
    checkpoint=P2Checkpoint('mage',30,source_build='1.60.1.70374')
    check_structural_allocation(ir,{'improved_frostbolt':5,'elemental_precision':5,
                                    'ice_lance':1,'frost_channeling':3,'shatter':3,
                                    'frostbite':3,'fingers_of_frost':1},checkpoint)
    with pytest.raises(ValueError,match='P2_PREREQUISITE_GATE'):
        check_structural_allocation(ir,{'improved_frostbolt':5,'elemental_precision':5,
                                        'frost_channeling':3,'shatter':3,
                                        'frostbite':3,'piercing_ice':1,'fingers_of_frost':1},checkpoint)
    result=evaluate_p2(ir,checkpoint)
    assert result['p2_pass']  # sourced L0 proxies, NOT L2 execution or a P1 build certificate
    assert len(result['unknown_position_families'])==0
    assert result['l0_scored_reachable_rank_count']==result['known_reachable_rank_count']==121
    assert not result['spellbook_scoped_l0_completeness_checked']


def test_malformed_source_prerequisite_fails_closed(tmp_path):
    source=json.loads(SOURCE.read_text())
    next(r for r in source['talents'] if r['talent_id']=='heating_up')['requires']=['nonexistent']
    with pytest.raises(ValueError,match='STAGED_TALENT_'):
        build_game_ir_slice(class_key='mage',level=30,ability_db_path=_db(tmp_path,source),use_runes=False)


def test_reproducible_staged_sqlite_preserves_default(tmp_path):
    from hashlib import sha256
    from tools.wf381_stage_mage_talent_positions import stage
    before=sha256(DEFAULT_DB.read_bytes()).hexdigest()
    result=stage(source=SOURCE, base=DEFAULT_DB, target=tmp_path/'source_stage.sqlite')
    assert result['positions']==54
    assert result['source_build']=='1.60.1.70374'
    assert result['sqlite_integrity']=='ok'
    assert result['base_sha256']==before==sha256(DEFAULT_DB.read_bytes()).hexdigest()
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=tmp_path/'source_stage.sqlite')
    assert all(t.metadata.get('source_position_only') for t in ir.talents)


def test_all_121_reachable_ranks_have_sourced_context_l0_without_faking_l2(tmp_path):
    from src.game.data.forever.source_checkpoint_p2 import evaluate_p2_allocation_l0
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=_db(tmp_path))
    checkpoint=P2Checkpoint('mage',30,source_build='1.60.1.70374')
    p2=evaluate_p2(ir,checkpoint)
    assert p2['known_reachable_rank_count']==121
    assert p2['l0_scored_reachable_rank_count']==121
    assert not p2['blocked'] and not p2['unknown_position_families']
    assert all(not r.modifiers for t in ir.talents for r in t.ranks)
    assert any(e['domain']=='cooldown_reduction_s' and e['target']=='fire_blast'
               for r in p2['rank_rows'] if r['talent_id']=='wake_of_fire' for e in r['l0_effects'])
    assert any(e['domain']=='damage_against_frozen_pct' and e['target']=='ice_lance'
               for r in p2['rank_rows'] if r['talent_id']=='ice_lance' for e in r['l0_effects'])
    witness=next(r['witness'] for r in p2['rank_rows'] if r['talent_id']=='fingers_of_frost')
    result=evaluate_p2_allocation_l0(p2,ir,witness,checkpoint)
    assert result['rankable'] and not result['scalar_s_per_mob_predicted']
