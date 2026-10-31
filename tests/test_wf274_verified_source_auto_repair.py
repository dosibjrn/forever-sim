"""Synthetic capture fixture + real preexisting executor (NOT live Forever fetch)."""
import hashlib
import json
import sqlite3
import zlib

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from tools.parse_verified_detail_to_staging import (
    SourceRepairBlocked,parse_into_staging)
from tools.compare_staged_ability_search import compare

SEARCH_SCENARIO={'mode_id':'cat','target_health':484,'pulls':3,
    'pre_combat_action_ids':('cat_form:768',),
    'post_combat_action_ids':('cancel_mode:cat',),
    'prepared_first_pull_resources':{'energy':100,'rage':0},
    'travel_time_s':2.2,'max_policies':28}

SCENARIO={
    'target_health':484,'count':2,
    'pre_combat_action_ids':('cat_form:768',),
    'post_combat_action_ids':('cancel_mode:cat',),
    'prepared_first_pull_resources':{'energy':100,'rage':0},
    'recovery_mode':'threshold','retain_mode_between_pulls':True,
    'travel_time_s':2.2,'apply_target_defense':True,
}


def _db(tmp_path):
    target=tmp_path/'staging.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(target) as dst:
        src.backup(dst)
    return target


def _synthetic_detail(conn,sid,text,*,cost='40 Energy',level=24,wrong_page=False):
    # This manufactured capture is ONLY for deterministic gating tests.
    # The production path refuses absent snapshots and validates real SHA/URL.
    batch=conn.execute('SELECT batch_id FROM spell_index WHERE spell_id=?',(sid,)).fetchone()[0]
    url=f'https://www.wowhead.com/forever/spell={1 if wrong_page else sid}'
    name=conn.execute('SELECT name FROM spell_index WHERE spell_id=?',(sid,)).fetchone()[0]
    body=f'{name} - Spell - Forever\nRank 1\nRequires level {level}\n{cost}\nInstant\n{text}\nSpell Details'
    html=f'<html><head><title>{name} - Spell - Forever</title></head><body>{body}</body></html>'.encode()
    digest=hashlib.sha256(html).hexdigest()
    conn.execute('''INSERT OR REPLACE INTO spell_details
       (batch_id,spell_id,source_url,page_title,raw_page_text,html_sha256,captured_at,details_verified)
       VALUES (?,?,?,?,?,?,?,1)''',(batch,sid,f'https://www.wowhead.com/forever/spell={sid}',
       f'{name} - Spell - Forever',body,digest,'2026-10-12T00:00:00Z'))
    conn.execute('''INSERT OR REPLACE INTO spell_detail_snapshots
      (batch_id,spell_id,final_url,http_status,html_sha256,html_bytes,html_zlib)
      VALUES (?,?,?,?,?,?,?)''',(batch,sid,url,200,digest,len(html),zlib.compress(html)))


def _text(sid,damage=123):
    return f'Rake the target for {damage} damage and an additional 48 damage over 9 sec. Awards 1 combo point.' if sid==1822 else 'Rake the target for 31 damage and an additional 63 damage over 9 sec. Awards 1 combo point.'


def test_verified_detail_changes_typed_sqlite_and_real_multi_pull(tmp_path):
    db=_db(tmp_path)
    old=_db(tmp_path.parent / "baseline") if False else tmp_path/"canonical.sqlite"
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(old) as dst:src.backup(dst)
    with sqlite3.connect(db) as con:_synthetic_detail(con,1822,_text(1822,123))
    repaired=parse_into_staging(db,spell_ids=(1822,))
    assert repaired[0]['changed']
    assert 'for 123 damage' in repaired[0]['after']
    result=compare(canonical_db=old,staged_db=db,class_key='druid',level=27,
                   **SEARCH_SCENARIO)
    assert result['changed_spell_ids']==[1822]
    assert result['arms']['canonical']['evaluated_count']==28
    assert result['arms']['staging']['evaluated_count']==28
    assert result['arms']['staging']['winner']['seconds_per_mob'] < result['arms']['canonical']['winner']['seconds_per_mob']
    assert not result['promoted']
    with sqlite3.connect(db) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT semantic_type FROM ability_semantic_source_facts WHERE spell_id=1822').fetchone()[0]=='melee_direct_periodic_combo'


def test_missing_actual_source_snapshot_never_promotes(tmp_path):
    db=_db(tmp_path)
    with pytest.raises(SourceRepairBlocked,match='DETAIL_NOT_VERIFIED'):
        parse_into_staging(db,spell_ids=(1822,))


def test_wrong_page_identity_and_corrupt_hash_are_blocked(tmp_path):
    db=_db(tmp_path)
    with sqlite3.connect(db) as con:_synthetic_detail(con,1822,_text(1822),wrong_page=True)
    with pytest.raises(SourceRepairBlocked,match='DETAIL_NOT_VERIFIED'):
        parse_into_staging(db,spell_ids=(1822,))
    with sqlite3.connect(db) as con:
        con.execute('UPDATE spell_detail_snapshots SET final_url=? WHERE spell_id=1822',('https://www.wowhead.com/forever/spell=1822',))
        con.execute('UPDATE spell_detail_snapshots SET html_sha256=? WHERE spell_id=1822',('0'*64,))
    with pytest.raises(SourceRepairBlocked,match='DETAIL_NOT_VERIFIED'):
        parse_into_staging(db,spell_ids=(1822,))


def test_unknown_effect_and_cost_disagreement_reject_without_sqlite_edits(tmp_path):
    db=_db(tmp_path)
    with sqlite3.connect(db) as con:
        before=con.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1822').fetchone()[0]
        _synthetic_detail(con,1822,'Rake the target for 999 damage and stuns for 6 seconds.')
    with pytest.raises(SourceRepairBlocked,match='DETAIL_GRAMMAR'):
        parse_into_staging(db,spell_ids=(1822,))
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1822').fetchone()[0]==before
        _synthetic_detail(con,1822,_text(1822),cost='999 Mana')
    with pytest.raises(SourceRepairBlocked,match='DETAIL_COST_DISAGREEMENT'):
        parse_into_staging(db,spell_ids=(1822,))
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1822').fetchone()[0]==before


def test_atomic_multi_rank_rollback_when_second_detail_invalid(tmp_path):
    db=_db(tmp_path)
    with sqlite3.connect(db) as con:
        before=con.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1822').fetchone()[0]
        _synthetic_detail(con,1822,_text(1822,180))
        _synthetic_detail(con,1823,_text(1823),cost='999 Mana',level=34)
    with pytest.raises(SourceRepairBlocked,match='DETAIL_COST_DISAGREEMENT'):
        parse_into_staging(db,spell_ids=(1822,1823))
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1822').fetchone()[0]==before


def test_negative_invalid_mechanics_never_reaches_runtime(tmp_path):
    db=_db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE sourced_direct_periodic_melee_semantics SET crit_multiplier=-2 WHERE spell_id=1822')
    with pytest.raises(ValueError,match='invalid sourced melee'):
        from src.game.data.forever.registry import build_game_ir_slice
        build_game_ir_slice(class_key='druid',level=27,ability_db_path=db)


def test_fetch_runner_parse_staging_then_real_runtime_without_mutating_canonical(tmp_path):
    from types import SimpleNamespace
    from pathlib import Path
    from tools.run_forever_ability_repair import execute
    canonical=_db(tmp_path)
    baseline=canonical.read_bytes()
    called=[]
    def synthetic_runner(command,**kwargs):
        called.append(command)
        staged=Path(command[command.index('--db')+1])
        with sqlite3.connect(staged) as db:
            _synthetic_detail(db,1822,_text(1822,150))
        return SimpleNamespace(returncode=0,stdout='fixture capture',stderr='')
    result=execute(class_key='druid',level=27,canonical=canonical,
         staging=tmp_path/'staging2.sqlite',runner=synthetic_runner,
         spell_ids=(1822,),runtime_scenario=SEARCH_SCENARIO)
    assert result['status']=='STAGING_REAL_POLICY_SEARCH_VALIDATED_NOT_PROMOTED'
    assert not result['promoted'] and called
    assert result['runtime_gate']['arms']['staging']['evaluated_count']==28
    assert result['runtime_gate']['changed_spell_ids']==[1822]
    assert canonical.read_bytes()==baseline


def test_fetch_runner_rejects_wrong_page_and_preserves_canonical(tmp_path):
    from types import SimpleNamespace
    from pathlib import Path
    from tools.run_forever_ability_repair import execute
    canonical=_db(tmp_path); original=canonical.read_bytes()
    def wrong_runner(command,**kwargs):
        staged=Path(command[command.index('--db')+1])
        with sqlite3.connect(staged) as db:
            _synthetic_detail(db,1822,_text(1822,150),wrong_page=True)
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    result=execute(class_key='druid',level=27,canonical=canonical,
         staging=tmp_path/'staging2.sqlite',runner=wrong_runner,
         spell_ids=(1822,),runtime_scenario=SEARCH_SCENARIO)
    assert result['status']=='SOURCE_INCOMPLETE' and not result['promoted']
    assert result['missing_ids']==[1822]
    assert canonical.read_bytes()==original


def test_unhashed_captured_body_cannot_override_signed_html(tmp_path):
    db=_db(tmp_path)
    with sqlite3.connect(db) as con:
        before=con.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1822').fetchone()[0]
        _synthetic_detail(con,1822,_text(1822,123))
        con.execute('UPDATE spell_details SET raw_page_text=REPLACE(raw_page_text,?,?) WHERE spell_id=1822',
                    ('for 123 damage','for 923 damage'))
    with pytest.raises(SourceRepairBlocked,match='HTML_AND_CAPTURED_BODY_DISAGREE'):
        parse_into_staging(db,spell_ids=(1822,))
    with sqlite3.connect(db) as con:
        assert con.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1822').fetchone()[0]==before


def test_real_captured_html_does_not_invent_missing_effect_semantics(tmp_path):
    # A genuinely retained production snapshot exists for this ID, but its
    # executable semantics are not yet typed; no guessed resource/damage facts.
    db=_db(tmp_path)
    from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot
    with sqlite3.connect(db) as conn:
        batch=conn.execute('SELECT batch_id FROM spell_index WHERE spell_id=53').fetchone()[0]
        evidence=read_verified_spell_detail_snapshot(conn,batch_id=batch,spell_id=53)
    assert len(evidence['html']) > 1000 and len(evidence['html_sha256'])==64
    with pytest.raises(SourceRepairBlocked,match='UNKNOWN_OR_UNSUPPORTED_TYPED_EFFECT'):
        parse_into_staging(db,spell_ids=(53,))
