import json
from src.v2 import runtime_state as rs


def test_atomic_write_publish_and_read_roundtrip(tmp_path, monkeypatch):
    snap=tmp_path/'viewer.json'
    monkeypatch.setattr(rs,'SNAPSHOT',snap)
    out=rs.publish({'phase':'x','views':{}})
    assert out['phase']=='x'
    assert isinstance(out['updated_at'],float)
    assert json.loads(snap.read_text())['phase']=='x'
    got=rs.read_snapshot()
    assert got['phase']=='x'


def test_read_snapshot_missing_returns_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(rs,'SNAPSHOT',tmp_path/'missing.json')
    got=rs.read_snapshot()
    assert got['running'] is False
    assert got['phase']=='idle'
    assert got['views']=={}


def test_atomic_write_cleans_temp_when_replace_fails(tmp_path, monkeypatch):
    target=tmp_path/'x.json'
    made=[]
    real_tmp=rs._tmp
    def fixed_tmp(path):
        p=tmp_path/'fixed.tmp'; made.append(p); return p
    monkeypatch.setattr(rs,'_tmp',fixed_tmp)
    def boom(src,dst):
        raise OSError('replace failed')
    monkeypatch.setattr(rs.os,'replace',boom)
    try:
        rs.atomic_write_json(target,{'x':1})
    except OSError as e:
        assert 'replace failed' in str(e)
    else:
        raise AssertionError('expected OSError')
    assert made and not made[0].exists()
    monkeypatch.setattr(rs,'_tmp',real_tmp)


def test_atomic_write_retries_transient_permission_error(tmp_path, monkeypatch):
    target=tmp_path/'viewer.json'
    real_replace=rs.os.replace
    calls={'n':0}
    sleeps=[]
    def flaky_replace(src,dst):
        calls['n']+=1
        if calls['n'] < 3:
            raise PermissionError(13,'busy')
        return real_replace(src,dst)
    monkeypatch.setattr(rs.os,'replace',flaky_replace)
    monkeypatch.setattr(rs.time,'sleep',lambda delay:sleeps.append(delay))
    rs.atomic_write_json(target,{'ok':True})
    assert calls['n']==3
    assert json.loads(target.read_text())=={'ok':True}
    assert sleeps==[0.005,0.010]


def test_atomic_write_falls_back_to_direct_write_when_replace_stays_locked(tmp_path, monkeypatch):
    target=tmp_path/'viewer.json'
    target.write_text('{"old": true}',encoding='utf-8')
    monkeypatch.setattr(rs.os,'replace',lambda *a,**k:(_ for _ in ()).throw(PermissionError(13,'rename locked')))
    monkeypatch.setattr(rs.time,'sleep',lambda delay:None)
    rs.atomic_write_json(target,{'new':True})
    assert json.loads(target.read_text())=={'new':True}
    assert not list(tmp_path.glob('*.tmp'))


def test_publish_does_not_kill_optimizer_when_snapshot_is_exclusively_locked(tmp_path, monkeypatch):
    monkeypatch.setattr(rs,'SNAPSHOT',tmp_path/'viewer.json')
    monkeypatch.setattr(rs,'atomic_write_json',lambda *a,**k:(_ for _ in ()).throw(PermissionError(13,'locked')))
    monkeypatch.setattr(rs.time,'monotonic',lambda:10.0)
    monkeypatch.setattr(rs,'_LAST_PUBLISH_WARNING_AT',0.0)
    out=rs.publish({'phase':'searching'})
    assert out['phase']=='searching'
    assert isinstance(out['updated_at'],float)
