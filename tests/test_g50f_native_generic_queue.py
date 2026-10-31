"""G50f: real native generic child, fail-closed queue, atomic publication."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from src.service.models import JobRequest
from src.service.store import QueueStore
from src.service.scheduler import Scheduler
from src.service.executors import executor_for
from src.service.publication import PublicationError, _validate_attempt_state, current_publication
from tests.test_g50e_worker_child_legacy_boundary import _interpreter_guard_shim
from tests.test_g50c_cold_service_http_isolation import _guard_environment, ROOT


def _request(**kw):
    args = dict(ruleset='forever', class_name='druid', start_level=10, end_level=10,
                objective='endpoint', endpoint_mode='generic_decision',
                forever_build_as_of='2026-10-08')
    args.update(kw)
    return JobRequest(**args)


def _queued(tmp_path, **kw):
    store=QueueStore(tmp_path/'queue.sqlite3')
    job, created=store.enqueue(_request(**kw))
    assert created
    return store, job


def test_native_generic_queue_real_child_guarded_and_atomically_published(tmp_path, monkeypatch):
    store, job=_queued(tmp_path)
    env, audit=_guard_environment(tmp_path, 'native_child_imports.log')
    shim=_interpreter_guard_shim(tmp_path)
    monkeypatch.setattr(sys, 'executable', str(shim))
    monkeypatch.setenv('PYTHONPATH', env['PYTHONPATH'])
    monkeypatch.setenv('WOW_G50C_GUARD_SCRIPT', env['WOW_G50C_GUARD_SCRIPT'])
    monkeypatch.setenv('WOW_G50C_IMPORT_AUDIT', env['WOW_G50C_IMPORT_AUDIT'])
    monkeypatch.setenv('WOW_DISABLE_LEGACY_JOB_EXECUTION', '1')
    monkeypatch.setenv('WOW_DISABLE_LEGACY_DECISIONS', '1')
    # Publication root is isolated; code is imported through PYTHONPATH.
    scheduler=Scheduler(store,runs_root=tmp_path/'runs')
    outcome=scheduler.run_once(project_root=tmp_path)
    assert outcome['state']=='completed', outcome
    attempt=store.list_attempts(job['id'])[0]
    manifest=json.loads((Path(attempt['run_root'])/'attempt_manifest.json').read_text())
    assert manifest['execution_authority']=='native_generic_decision'
    assert manifest['native_generic_job_supported'] is True
    assert manifest['executor']=='native_generic_decision_level'
    assert manifest['command'][1:3]==['-m','src.service.generic_decision_worker']
    assert audit.exists() and 'GUARD_LOADED:' in audit.read_text()
    assert 'BLOCKED:' not in audit.read_text(), audit.read_text()
    assert len(store.list_publications())==1
    pub=current_publication(tmp_path)
    assert pub['attempt_id']==attempt['id']
    artifact=Path(pub['state_root'])/'generic/decisions/forever-druid-L10.json'
    payload=json.loads(artifact.read_text())
    assert payload['execution_authority']=='native_generic_decision'
    assert payload['legacy_fallback'] is False
    assert payload['producer_version']==__import__('src.version',fromlist=['SOFTWARE_VERSION']).SOFTWARE_VERSION
    record=payload['decision']
    assert record['backend']['id']=='generic'
    assert record['provenance']['source']=='generic_backend_native'
    assert record['identity']['level']==10
    assert record['publication_availability']['timing']=='available'
    assert any(e['kind']=='publication_committed' for e in store.events_since(job_id=job['id']))


@pytest.mark.parametrize('overrides', [
    {'class_name':'mage','start_level':12,'end_level':12}, {'start_level':12,'end_level':12},
    {'end_level':11}, {'objective':'cumulative'},
    {'forever_build_as_of':'2026-10-02'}, {'config':{'beam_width':2}},
    {'source_snapshot':'other'}, {'validation_modes':('compare',)},
])
def test_unsupported_native_queue_scope_rejected_without_spawn(tmp_path, overrides):
    store, job=_queued(tmp_path, **overrides)
    scheduler=Scheduler(store,runs_root=tmp_path/'runs')
    result=scheduler.run_once(project_root=tmp_path)
    assert result['state']=='failed'
    assert 'saved state rejected' in store.get(job['id'])['error']
    attempt=store.list_attempts(job['id'])[0]
    root=Path(attempt['run_root'])
    assert not (root/'stdout.log').exists()
    assert not store.list_publications()


def test_historical_smooth_is_not_routed_to_native():
    job={'request':{'endpoint_mode':'smooth','ruleset':'forever','class_name':'druid',
                    'start_level':10,'end_level':10,'forever_build_as_of':'2026-10-08','config':{}}}
    plan=executor_for(job).plan(job)
    assert plan.execution_authority=='historical_legacy_cli'
    assert plan.native_generic_job_supported is False


def test_native_publication_rejects_forged_provenance(tmp_path):
    root=tmp_path/'run'; state=root/'state/generic/decisions';state.mkdir(parents=True)
    request=_request().canonical_dict()
    job={'id':'test','request':request}
    attempt={'id':'attempt','run_root':str(root)}
    file=state/'forever-druid-L10.json'
    # Non-object JSON must produce PublicationError, never crash the scheduler.
    file.write_text('[]')
    with pytest.raises(PublicationError): _validate_attempt_state(job,attempt)
    file.write_text(json.dumps({'schema_version':1,'complete':True,
                                'execution_authority':'historical_legacy_cli',
                                'legacy_fallback':False}))
    with pytest.raises(PublicationError): _validate_attempt_state(job,attempt)


def test_http_admission_accepts_only_explicit_supported_generic_scope(tmp_path):
    from threading import Thread
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from src.service.http_api import OptimizerHTTPServer

    store=QueueStore(tmp_path/'queue.sqlite3')
    server=OptimizerHTTPServer(('127.0.0.1',0),store,project_root=tmp_path)
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    def post(overrides):
        payload=_request(**overrides).canonical_dict()
        data=json.dumps(payload).encode()
        req=Request(f'http://127.0.0.1:{server.server_address[1]}/api/v1/jobs',
                    data=data,headers={'Content-Type':'application/json'},method='POST')
        try:
            with urlopen(req,timeout=5) as response:
                return response.status,json.load(response)
        except HTTPError as exc:
            return exc.code,json.load(exc)
    try:
        status,payload=post({})
        assert status==201 and payload['job']['request']['endpoint_mode']=='generic_decision'
        status,payload=post({'class_name':'mage','start_level':12,'end_level':12})
        assert status==400 and 'scope not declared' in payload['error']
        assert len(store.list_jobs())==1
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
