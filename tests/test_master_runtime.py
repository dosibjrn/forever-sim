from pathlib import Path
from types import SimpleNamespace
import threading

from src import master_runtime as rt


def _args():
    return SimpleNamespace(workers=3, heartbeat_history=7, heartbeat_seconds=60)


def test_runtime_reporter_update_enriches_and_publishes_all_water_views(monkeypatch):
    calls=[]
    monkeypatch.setattr(rt.sm, 'WATER_MODES', ['buy_water','conjured_water'])
    monkeypatch.setattr(rt.sm, 'current_best_meta', lambda m: {'mode':m})
    monkeypatch.setattr(rt.sm, 'publish_status', lambda s: calls.append(('status',s.copy())))
    monkeypatch.setattr(rt.sm, 'publish_viewer_snapshot', lambda m,s=None: calls.append(('view',m,s.copy())))
    reporter=rt.RuntimeReporter(_args(), stop_event=threading.Event(), active_checkpoint={'path':None})
    snap=reporter.update(state='searching', water_mode='conjured_water', message='x')
    assert snap['best'] == {'mode':'conjured_water'}
    assert snap['best_by_water']['buy_water'] == {'mode':'buy_water'}
    assert [c[1] for c in calls if c[0]=='view'] == ['buy_water','conjured_water']
    assert calls[0][0] == 'status'


def test_runtime_reporter_heartbeat_once_snapshots_checkpoint_and_history(tmp_path, monkeypatch):
    cp=tmp_path/'cp.pkl'; cp.write_bytes(b'checkpoint')
    runtime=tmp_path/'runtime'; runtime.mkdir()
    calls=[]
    monkeypatch.setattr(rt.sm, 'RUNTIME', runtime)
    monkeypatch.setattr(rt.sm, 'WATER_MODES', ['buy_water'])
    monkeypatch.setattr(rt.sm, 'current_best_meta', lambda m: {})
    monkeypatch.setattr(rt.sm, 'atomic_copy', lambda src,dst: Path(dst).write_bytes(Path(src).read_bytes()))
    monkeypatch.setattr(rt.sm, 'publish_status', lambda s: calls.append('status'))
    monkeypatch.setattr(rt.sm, 'publish_viewer_snapshot', lambda m,s=None: calls.append('view'))
    monkeypatch.setattr(rt.sm, 'heartbeat_snapshot', lambda s,keep=0: calls.append(('history',keep)))
    monkeypatch.setattr(rt.sm, 'make_chat_handoff', lambda: calls.append('handoff'))
    reporter=rt.RuntimeReporter(_args(), stop_event=threading.Event(), active_checkpoint={'path':str(cp)})
    reporter.update(water_mode='buy_water')
    calls.clear()
    snap=reporter.heartbeat_once()
    assert (runtime/'optimizer.pkl').read_bytes() == b'checkpoint'
    assert ('history',7) in calls and 'handoff' in calls
    assert snap['water_mode'] == 'buy_water'
