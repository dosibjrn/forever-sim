"""Cross-class bulk source recovery: never turn a source hint into a legal spell."""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import hashlib
import shutil
import sqlite3
import subprocess

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_verified_detail_headers import read_current_header
from tools.wf292_batch_verified_source_recovery import inventory,execute
from tools.wf292_ingest_verified_detail_headers_sqlite import ingest


def test_nine_class_bulk_queue_and_source_immunity(tmp_path):
    db=tmp_path/'canonical.sqlite';stage=tmp_path/'stage.sqlite'
    shutil.copy2(DEFAULT_DB,db)
    original=hashlib.sha256(db.read_bytes()).hexdigest()
    planned=inventory(db,chunk_size=100)
    assert planned['indexed']==2255
    assert planned['verified_detail_before']==20
    assert planned['pending']==2235
    assert len(planned['by_class_pending'])==9
    assert len(planned['chunks'])==22
    assert planned['pending_unique_pages']==2174
    assert all(1<=len(c['spell_ids'])<=100 for c in planned['chunks'])
    # The source fetcher cannot be run here. Offline mode still establishes a
    # real staging SQLite and a deterministic resumable exact-ID queue.
    result=execute(canonical=db,stage=stage,offline=True)
    assert result['verified_new']==0
    assert result['attempted_chunks']==0
    assert hashlib.sha256(db.read_bytes()).hexdigest()==original
    assert inventory(stage)['pending']==2235
    resumed=execute(canonical=db,stage=stage,resume=True,offline=True)
    assert resumed['before']['pending']==2235
    with pytest.raises(FileExistsError):
        execute(canonical=db,stage=stage,offline=True)
    with pytest.raises(ValueError,match='CANONICAL'):
        execute(canonical=db,stage=db,offline=True)


def test_failed_batch_preserves_partial_stage_and_cannot_promote(tmp_path):
    db=tmp_path/'canonical.sqlite';stage=tmp_path/'stage.sqlite'
    shutil.copy2(DEFAULT_DB,db)
    calls=[]
    def broken_runner(argv,**kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=2,stdout='browser blocked',stderr='source DNS failed')
    result=execute(canonical=db,stage=stage,chunk_size=125,max_chunks=2,runner=broken_runner)
    assert result['attempted_chunks']==2 and len(calls)==1
    assert result['browser_sessions']==1
    assert all('--details-only' in c and '--detail-plan' in c for c in calls)
    assert result['verified_new']==0 and result['after']['pending']==2235
    assert result['accepted_checkpoints']==result['executable_promotions']==0
    assert all(c['status']=='FETCH_NONZERO' for c in result['chunks'])
    assert execute(canonical=db,stage=stage,resume=True,offline=True)['before']['pending']==2235


def test_batched_browser_plan_covers_all_nine_classes_without_22_launches(tmp_path):
    import json
    db=tmp_path/'canonical.sqlite';stage=tmp_path/'stage.sqlite'
    shutil.copy2(DEFAULT_DB,db)
    before=hashlib.sha256(db.read_bytes()).hexdigest()
    sessions=[]; all_ids=set()
    def inspect_runner(argv,**kwargs):
        assert argv.count('--detail-plan')==1
        from pathlib import Path
        plan=json.loads(Path(argv[argv.index('--detail-plan')+1]).read_text())
        assert plan['schema']=='forever_detail_session_v1'
        assert 1<=len(plan['chunks'])<=4
        sessions.append(plan)
        for chunk in plan['chunks']:
            for sid in chunk['spell_ids']:
                assert (chunk['batch_id'],sid) not in all_ids
                all_ids.add((chunk['batch_id'],sid))
        return SimpleNamespace(returncode=1,stdout='browser unavailable',stderr='')
    result=execute(canonical=db,stage=stage,runner=inspect_runner)
    assert result['attempted_chunks']==22
    assert result['browser_sessions']==6==len(sessions)
    assert len(all_ids)==2174
    assert hashlib.sha256(db.read_bytes()).hexdigest()==before
    assert result['verified_new']==0
    assert not list(tmp_path.glob('.forever_detail_session_*'))


def test_multi_batch_plan_rejects_unindexed_and_duplicate_source_ids(tmp_path):
    import json
    from tools.capture_forever_abilities_sqlite import load_detail_plan
    db=tmp_path/'canonical.sqlite';shutil.copy2(DEFAULT_DB,db)
    plan=tmp_path/'plan.json'
    with sqlite3.connect(db) as conn:
        batch,spell=conn.execute("SELECT batch_id,spell_id FROM spell_index WHERE kind='abilities' LIMIT 1").fetchone()
        def check(chunks):
            plan.write_text(json.dumps({'schema':'forever_detail_session_v1','chunks':chunks}))
            return load_detail_plan(plan,conn)
        assert check([{'batch_id':batch,'spell_ids':[spell]}])
        with pytest.raises(ValueError,match='DUPLICATE'):
            check([{'batch_id':batch,'spell_ids':[spell]},
                   {'batch_id':batch,'spell_ids':[spell]}])
        with pytest.raises(ValueError,match='NOT_COMPLETE_INDEX'):
            check([{'batch_id':batch,'spell_ids':[99999999]}])
        with pytest.raises(ValueError,match='INVALID_DETAIL_SESSION_IDS'):
            check([{'batch_id':batch,'spell_ids':[str(spell)]}])


def test_browser_failure_after_real_verified_snapshot_preserves_progress(tmp_path):
    import json
    db=tmp_path/'canonical.sqlite';stage=tmp_path/'stage.sqlite'
    shutil.copy2(DEFAULT_DB,db)
    execute(canonical=db,stage=stage,offline=True)
    with sqlite3.connect(stage) as conn:
        batch=conn.execute("SELECT batch_id FROM spell_index WHERE class_key='mage' AND spell_id=133").fetchone()[0]
        conn.execute('DELETE FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=133',(batch,))
        conn.execute('DELETE FROM spell_details WHERE batch_id=? AND spell_id=133',(batch,))
    assert inventory(stage)['verified_detail_before']==19
    def crashed_after_first_page(argv,**kwargs):
        plan=json.loads(Path(argv[argv.index('--detail-plan')+1]).read_text())
        assert any(c['batch_id']==batch and 133 in c['spell_ids'] for c in plan['chunks'])
        with sqlite3.connect(db) as src,sqlite3.connect(stage) as dst:
            for table in ('spell_details','spell_detail_snapshots'):
                cols=[r[1] for r in src.execute(f'PRAGMA table_info({table})')]
                row=src.execute(f'SELECT * FROM {table} WHERE batch_id=? AND spell_id=133',(batch,)).fetchone()
                dst.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in cols)})',row)
        return SimpleNamespace(returncode=1,stdout='crashed after durable HTML capture',stderr='')
    result=execute(canonical=db,stage=stage,resume=True,max_chunks=4,runner=crashed_after_first_page)
    assert result['verified_new']==1
    assert result['after']['verified_detail_before']==20
    assert any(133 in c['spell_ids_verified'] for c in result['chunks'])
    assert result['sessions'][0]['status']=='FETCH_NONZERO'


def test_existing_fetcher_persists_real_verified_html_in_multi_batch_mode(tmp_path,monkeypatch):
    """Exercise actual capture_main, not only the subprocess-plan generator."""
    import argparse
    import json
    import sys
    import types
    from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot
    from tools.capture_forever_abilities_sqlite import capture_main
    db=tmp_path/'stage.sqlite';shutil.copy2(DEFAULT_DB,db)
    with sqlite3.connect(db) as conn:
        batch=conn.execute("SELECT batch_id FROM spell_index WHERE class_key='mage' AND spell_id=133").fetchone()[0]
        snap=read_verified_spell_detail_snapshot(conn,batch_id=batch,spell_id=133)
        original=conn.execute('SELECT page_title,raw_page_text FROM spell_details WHERE batch_id=? AND spell_id=133',(batch,)).fetchone()
        conn.execute('DELETE FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=133',(batch,))
        conn.execute('DELETE FROM spell_details WHERE batch_id=? AND spell_id=133',(batch,))
    class FakePage:
        url=snap['source_url']
        def goto(self,url,**kwargs):
            assert url==self.url
            return SimpleNamespace(status=200)
        def wait_for_timeout(self,*args):pass
        def title(self):return original[0]
        def locator(self,selector):
            assert selector=='body'
            return SimpleNamespace(inner_text=lambda **kwargs:original[1])
        def content(self):return snap['html']
    class FakeContext:
        pages=[FakePage()]
        def close(self):pass
    class FakePlaywright:
        chromium=SimpleNamespace(launch_persistent_context=lambda *args,**kwargs:FakeContext())
        def __enter__(self):return self
        def __exit__(self,*args):pass
    fake=types.ModuleType('playwright.sync_api')
    fake.sync_playwright=lambda:FakePlaywright()
    monkeypatch.setitem(sys.modules,'playwright',types.ModuleType('playwright'))
    monkeypatch.setitem(sys.modules,'playwright.sync_api',fake)
    plan=tmp_path/'plan.json'
    plan.write_text(json.dumps({'schema':'forever_detail_session_v1',
                                'chunks':[{'batch_id':batch,'spell_ids':[133]}]}))
    args=argparse.Namespace(db=db,batch_id=None,detail_plan=plan,details_only=True,
        classes=[],kinds=[],resume=True,details=True,spell_ids=None,
        user_data_dir=tmp_path/'profile',channel='chrome',headless=True,
        timeout_ms=1000,settle_ms=0,max_details=None,max_pages=1)
    assert capture_main(args)==0
    with sqlite3.connect(db) as conn:
        assert read_verified_spell_detail_snapshot(conn,batch_id=batch,spell_id=133)['html_sha256']==snap['html_sha256']
    assert inventory(db)['verified_detail_before']==20


def test_verified_detail_headers_recover_cost_but_never_claim_effects(tmp_path):
    db=tmp_path/'source.sqlite';shutil.copy2(DEFAULT_DB,db)
    report=ingest(db)
    assert report['indexed_source_verified_headers']==20
    assert report['costs_recovered_where_index_missing']==9
    assert report['executable_promotions']==0
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM verified_spell_detail_header_facts').fetchone()[0]==20
        assert read_current_header(conn,class_key='priest',spell_id=17)['cost_amount']==45
        # Even a hash-matched row cannot make up resource values.
        conn.execute("UPDATE verified_spell_detail_header_facts SET cost_amount=900 WHERE spell_id=17")
        with pytest.raises(ValueError,match='TAMPERED'):
            read_current_header(conn,class_key='priest',spell_id=17)
    with pytest.raises(ValueError,match='TAMPERED'):
        from src.game.data.forever.source_indexed_action_coverage import indexed_ability_coverage
        from src.game.data.forever.registry import build_game_ir_slice
        # Registry must be asked to use the altered source database; the
        # verified header ledger is never trusted without checking source.
        ir=build_game_ir_slice(class_key='priest',level=20,ability_db_path=db)


def test_detail_index_conflict_rolls_back_batch(tmp_path):
    db=tmp_path/'source.sqlite';shutil.copy2(DEFAULT_DB,db)
    ingest(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE spell_index SET level_hint=19 WHERE class_key='mage' AND spell_id=116")
    with pytest.raises(ValueError,match='LEVEL_DRIFT'):
        ingest(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM verified_spell_detail_header_facts').fetchone()[0]==20


def test_source_detail_headers_are_not_legal_world_actions():
    for cls in ('druid','hunter','mage','paladin','priest','rogue','shaman','warlock','warrior'):
        ir=build_game_ir_slice(class_key=cls,level=20)
        assert ir is not None
        coverage=next(f for f in ir.source_facts if f.get('fact_kind')=='canonical_indexed_ability_coverage')
        assert coverage['summary']['source_verified_header_is_not_executable']
        assert ir.provenance['complete_source_action_coverage'] is False


def test_source_batch_typed_ingest_all_nine_classes(tmp_path):
    from tools.wf292_batch_verified_source_recovery import typed_ingest_stage
    fetch=tmp_path/'fetch.sqlite';typed=tmp_path/'typed.sqlite'
    shutil.copy2(DEFAULT_DB,fetch)
    original=hashlib.sha256(fetch.read_bytes()).hexdigest()
    result=typed_ingest_stage(source_stage=fetch,typed_stage=typed)
    assert result['ingested']['verified_headers']['indexed_source_verified_headers']==20
    assert result['ingested']['verified_headers']['costs_recovered_where_index_missing']==9
    assert result['ingested']['acquisition']['indexed_abilities']==2255
    assert result['ingested']['entities']['source_entity_links']==405
    assert result['ingested']['effect_candidates']['typed_candidates']==326
    assert result['executable_promotions']==result['accepted_checkpoints']==0
    assert hashlib.sha256(fetch.read_bytes()).hexdigest()==original
    with sqlite3.connect(typed) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT COUNT(*) FROM verified_spell_detail_header_facts').fetchone()[0]==20
    with pytest.raises(FileExistsError):
        typed_ingest_stage(source_stage=fetch,typed_stage=typed)


def test_generic_verified_detail_cost_fallback_and_no_invention(tmp_path):
    from src.game.data.forever.source_ability_semantics import _source_cost_match
    db=tmp_path/'source.sqlite';shutil.copy2(DEFAULT_DB,db)
    missing_index,proof=_source_cost_match('',db_path=db,class_key='priest',spell_id=17)
    assert missing_index.groups()==('45.0','mana') and len(proof)==64
    # A present but invalid source index must NOT be silently replaced.
    malformed,proof=_source_cost_match('not a resource cost',db_path=db,class_key='priest',spell_id=17)
    assert malformed is None and proof is None
    absent,proof=_source_cost_match('',db_path=db,class_key='paladin',spell_id=999999)
    assert absent is None and proof is None
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE verified_spell_detail_header_facts SET cost_amount=999 WHERE spell_id=17")
    with pytest.raises(ValueError,match='TAMPERED'):
        _source_cost_match('',db_path=db,class_key='priest',spell_id=17)
