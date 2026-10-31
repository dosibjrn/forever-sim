"""Actual saved Forever source HTML replayed through concurrent capture writer.

No fake spell values, no network, no L2 promotion. Transport latency is
synthetic; the persisted source bytes are independently verified originals.
"""
from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
import sqlite3
import time

import pytest

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2.source_sqlite_detail_snapshots import read_verified_spell_detail_snapshot, MissingVerifiedSpellDetail
from tools.capture_forever_abilities_sqlite import load_detail_plan
from tools.wf313_parallel_verified_capture import (
    capture_parallel, pending_plan, persist_verified_capture, InvalidCapture,
)


def _prepare(tmp_path, limit=12):
    canonical = Path(DEFAULT_DB)
    before_sha = sha256(canonical.read_bytes()).hexdigest()
    stage = tmp_path/'capture_stage.sqlite'
    with sqlite3.connect(canonical) as source, sqlite3.connect(stage) as db:
        source.backup(db)
        rows = db.execute('SELECT batch_id,spell_id FROM spell_detail_snapshots ORDER BY spell_id LIMIT ?',
                          (limit,)).fetchall()
        assert len(rows)==limit
        fixture={}
        for batch_id,sid in rows:
            original=read_verified_spell_detail_snapshot(db,batch_id=batch_id,spell_id=sid)
            title,body,status=db.execute('''SELECT d.page_title,d.raw_page_text,s.http_status
                FROM spell_details d JOIN spell_detail_snapshots s
                ON s.batch_id=d.batch_id AND s.spell_id=d.spell_id
                WHERE d.batch_id=? AND d.spell_id=?''',(batch_id,sid)).fetchone()
            fixture[sid]={'html':original['html'],'title':title,'body':body,
                          'status':status,'final_url':original['final_url'],
                          'sha':original['html_sha256']}
            db.execute('DELETE FROM spell_detail_snapshots WHERE batch_id=? AND spell_id=?',(batch_id,sid))
            db.execute('DELETE FROM spell_details WHERE batch_id=? AND spell_id=?',(batch_id,sid))
        db.commit()
    plan=[{'batch_id':rows[0][0],'spell_ids':[sid for _,sid in rows]}]
    return canonical,before_sha,stage,fixture,plan


def test_concurrent_source_replay_and_idempotent_resume(tmp_path):
    canonical,sha,stage,fixture,plan=_prepare(tmp_path)
    with sqlite3.connect(stage) as db:
        assert len(pending_plan(db,plan)[0])==len(fixture)
        async def fetch(index,sid,url):
            await asyncio.sleep(.01)
            return {k:v for k,v in fixture[sid].items() if k!='sha'}
        t=time.monotonic()
        report=asyncio.run(capture_parallel(db,plan=plan,fetch=fetch,workers=6))
        elapsed=time.monotonic()-t
        assert report['newly_verified']==len(fixture)
        assert report['failed_unverified']==0
        assert report['fetch_attempts_including_failures']==len(fixture)
        for batch_id,sid in [(plan[0]['batch_id'],sid) for sid in plan[0]['spell_ids']]:
            assert read_verified_spell_detail_snapshot(db,batch_id=batch_id,spell_id=sid)['html_sha256']==fixture[sid]['sha']
        resumed=asyncio.run(capture_parallel(db,plan=plan,fetch=fetch,workers=6))
        assert resumed['newly_verified']==0 and resumed['previously_verified']==len(fixture)
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert sha256(canonical.read_bytes()).hexdigest()==sha
    assert elapsed<2.0


def test_invalid_wrong_id_block_and_failure_are_not_persisted(tmp_path):
    canonical,sha,stage,fixture,plan=_prepare(tmp_path,limit=8)
    ids=plan[0]['spell_ids'];wrong=ids[0];blocked=ids[1];failed=ids[2]
    async def fetch(index,sid,url):
        if sid==wrong:
            out=dict(fixture[sid]);out['final_url']=f'https://www.wowhead.com/forever/spell={ids[3]}'
            return out
        if sid==blocked:
            out=dict(fixture[sid]);out['body']='Just a moment... captcha';return out
        if sid==failed:raise TimeoutError('simulated source timeout')
        return dict(fixture[sid])
    with sqlite3.connect(stage) as db:
        report=asyncio.run(capture_parallel(db,plan=plan,fetch=fetch,workers=4,retries=1))
        assert report['newly_verified']==5 and report['failed_unverified']==3
        assert report['fetch_attempts_including_failures']==9
        for sid in (wrong,blocked,failed):
            with pytest.raises(MissingVerifiedSpellDetail):
                read_verified_spell_detail_snapshot(db,batch_id=plan[0]['batch_id'],spell_id=sid)
        async def repaired(index,sid,url):return dict(fixture[sid])
        report=asyncio.run(capture_parallel(db,plan=plan,fetch=repaired,workers=3))
        assert report['previously_verified']==5 and report['newly_verified']==3
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert sha256(canonical.read_bytes()).hexdigest()==sha


def test_data_only_changed_source_is_reverified_not_silently_accepted(tmp_path):
    _,_,stage,fixture,plan=_prepare(tmp_path,limit=1)
    sid=plan[0]['spell_ids'][0]
    with sqlite3.connect(stage) as db:
        candidate=dict(fixture[sid]);candidate['html']=candidate['html'].replace('Value:','Value: 999 ',1)
        # An HTML-only change is still a valid *new* source snapshot if page
        # identity is valid; the independent SHA changes and typed stages must
        # be re-ingested. This is NOT permission to promote executable facts.
        new_hash=persist_verified_capture(db,batch_id=plan[0]['batch_id'],spell_id=sid,response=candidate)
        assert new_hash!=fixture[sid]['sha']
        assert read_verified_spell_detail_snapshot(db,batch_id=plan[0]['batch_id'],spell_id=sid)['html_sha256']==new_hash
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_plan_rejects_unindexed_ids_and_worker_limits(tmp_path):
    _,_,stage,fixture,plan=_prepare(tmp_path,limit=1)
    with sqlite3.connect(stage) as db:
        import json
        p=tmp_path/'plan.json'
        p.write_text(json.dumps({'schema':'forever_detail_session_v1','chunks':[{'batch_id':plan[0]['batch_id'],'spell_ids':[999999999]}]}))
        with pytest.raises(ValueError,match='DETAIL_SESSION_IDS_NOT_COMPLETE_INDEX'):
            load_detail_plan(p,db)
        async def fetch(index,sid,url):return dict(fixture[sid])
        with pytest.raises(ValueError,match='INVALID_SOURCE_CAPTURE_BUDGET'):
            asyncio.run(capture_parallel(db,plan=plan,fetch=fetch,workers=9))


def test_systemic_invalid_pages_stop_bulk_capture_before_burning_2174(tmp_path):
    _,_,stage,fixture,plan=_prepare(tmp_path,limit=12)
    async def bad(index,sid,url):
        out=dict(fixture[sid]);out['status']=403;return out
    with sqlite3.connect(stage) as db:
        report=asyncio.run(capture_parallel(db,plan=plan,fetch=bad,workers=2))
        assert report['stopped_on_repeated_invalid_source']
        assert report['unattempted_pending']>0
        assert report['newly_verified']==0
        assert db.execute('SELECT COUNT(*) FROM spell_detail_snapshots').fetchone()[0]==8


def test_wf310_invokes_same_fetcher_with_bounded_parallel_workers(tmp_path):
    from tools.wf292_batch_verified_source_recovery import execute
    _,_,stage,fixture,plan=_prepare(tmp_path,limit=2)
    # Use a real complete canonical DB as the parent, not the stripped stage.
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    class FakeProcess:
        returncode=1
        stdout='browser offline'
        stderr='network unavailable'
    called=[]
    def runner(argv,**kw):
        called.append(argv)
        return FakeProcess()
    capture_stage=tmp_path/'new_stage.sqlite'
    result=execute(canonical=Path(DEFAULT_DB),stage=capture_stage,
                   max_chunks=1,session_chunks=1,detail_workers=6,runner=runner)
    assert len(called)==1
    assert '--detail-workers' in called[0]
    assert called[0][called[0].index('--detail-workers')+1]=='6'
    assert result['detail_workers']==6
    assert result['verified_new']==0
    assert result['source_db_unchanged_sha256']==sha256(Path(DEFAULT_DB).read_bytes()).hexdigest()
