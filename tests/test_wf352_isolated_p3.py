"""Focused failure isolation; no rogue processes or fake successes."""
from types import SimpleNamespace
import time
from src.game.data.forever.source_checkpoint_p3_isolated import isolated_process_probe


def _sleeper(q,*args):
    time.sleep(30.)


def _success(q,*args):
    q.put({'status':'COMPLETE','s_per_mob':11.2,'events':42})


def _crash(q,*args):
    raise RuntimeError('crash')


def test_os_timeout_terminates_before_hung_executor_finishes():
    started=time.monotonic()
    result=isolated_process_probe(None,'armor',100,timeout_s=.25,worker=_sleeper)
    assert result['status']=='OS_TIMEOUT'
    assert time.monotonic()-started<3.


def test_os_worker_completes_and_reports_runtime():
    result=isolated_process_probe(None,'armor',100,timeout_s=2,worker=_success)
    assert result['status']=='COMPLETE'
    assert result['s_per_mob']==11.2 and result['events']==42


def test_os_worker_dies_fail_closed():
    result=isolated_process_probe(None,'armor',100,timeout_s=2,worker=_crash)
    assert result['status']=='WORKER_EXIT_WITHOUT_RESULT'


def test_resume_reuses_exact_context_and_rejects_stale(tmp_path, monkeypatch):
    import json
    from src.game.data.forever import source_checkpoint_p3_isolated as iso
    import types
    fake_item=types.SimpleNamespace()
    candidate=SimpleNamespace(source_stage={'gear_policy_result':{'winner':{'gear':{'slots':{'weapon':{'weapon_dps':10}}}}},
                                            'source_context_sha256':'context-A'},
                              ir=SimpleNamespace(actor=SimpleNamespace(base_stats={'strength':22})))
    path=tmp_path/'items.sqlite';path.write_bytes(b'catalogue')
    monkeypatch.setattr(iso,'_identity',lambda stage:'build-A')
    monkeypatch.setattr(iso,'catalogue_path',lambda:path)
    monkeypatch.setattr(iso,'available_items',lambda *a,**k:[fake_item])
    monkeypatch.setattr(iso,'_features',lambda row:{'armor':50.})
    monkeypatch.setattr(iso,'executable_gear_stats',lambda ir:('armor',))
    monkeypatch.setattr(iso,'context_weapon_speed_semantics',lambda ir:'FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY')
    result=iso.measured_axis_suite(candidate=candidate,class_key='druid',level=30,
       base_score_s_per_mob=11.3,out_dir=tmp_path/'cache',axes=['armor'],worker=_success)
    assert result['weights']['armor']['status']=='MEASURED_100MOB_OS_ISOLATED'
    assert (tmp_path/'cache'/'armor.json').is_file()
    repeated=iso.measured_axis_suite(candidate=candidate,class_key='druid',level=30,
       base_score_s_per_mob=11.3,out_dir=tmp_path/'cache',axes=['armor'],worker=_sleeper)
    assert repeated['worker_events'][0]['action']=='CACHED'
    try:
        iso.measured_axis_suite(candidate=candidate,class_key='druid',level=30,
           base_score_s_per_mob=11.4,out_dir=tmp_path/'cache',axes=['armor'],worker=_success)
    except ValueError as exc:assert 'P3_STALE_PROBE_CACHE' in str(exc)
    else:assert False,'stale cache must not be reused'


def test_default_axes_skip_absent_item_stats(tmp_path,monkeypatch):
    from src.game.data.forever import source_checkpoint_p3_isolated as iso
    fake_item=SimpleNamespace()
    candidate=SimpleNamespace(source_stage={'gear_policy_result':{'winner':{'gear':{'slots':{'weapon':{'weapon_dps':10}}}}},
                                            'source_context_sha256':'context'},
                              ir=SimpleNamespace(actor=SimpleNamespace(base_stats={})))
    path=tmp_path/'items.sqlite';path.write_bytes(b'catalogue')
    monkeypatch.setattr(iso,'_identity',lambda stage:'build-X')
    monkeypatch.setattr(iso,'catalogue_path',lambda:path)
    monkeypatch.setattr(iso,'available_items',lambda *a,**k:[fake_item])
    monkeypatch.setattr(iso,'_features',lambda row:{'armor':50.})
    monkeypatch.setattr(iso,'executable_gear_stats',lambda ir:('armor',))
    monkeypatch.setattr(iso,'context_weapon_speed_semantics',lambda ir:'FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY')
    out=iso.measured_axis_suite(candidate=candidate,class_key='druid',level=30,
          base_score_s_per_mob=11.3,out_dir=tmp_path/'cache',worker=_success)
    assert [x['axis'] for x in out['worker_events']]==['armor']
