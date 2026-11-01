"""G50e: real durable queued job -> scheduler -> distinct child import audit.

The queue smooth/fast and mc executors remain historical CLIs.  No native
queued generic evaluator is claimed.  Tests never touch the global queue.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from src.service.models import JobRequest
from src.service.store import QueueStore
from src.service.scheduler import Scheduler
from src.service.executors import executor_for
from tests.test_g50c_cold_service_http_isolation import _guard_environment, ROOT


def _enqueue(tmp_path):
    store = QueueStore(tmp_path / 'queue.sqlite3')
    job, created = store.enqueue(JobRequest(
        ruleset='forever', class_name='mage', start_level=10, end_level=10,
        endpoint_mode='smooth', forever_build_as_of='2026-10-08',
        config={'workers':1, 'no_stat_weights':True,
                'beam_width':1, 'family_keep':1, 'final_k':1},
    ))
    assert created and job['state'] == 'queued'
    return store, job


def _run_cold_daemon_once(db, runs_root, env, *, executable_shim=None):
    args=['--once','--db',str(db),'--runs-root',str(runs_root)]
    if executable_shim is None:
        cmd=[sys.executable,'-B','-m','src.service.daemon',*args]
    else:
        # The exact production Scheduler/Executor code is used. Only the
        # interpreter executable is replaced with a testing shim which loads
        # the guard in the actual spawned worker BEFORE import of src.v2.runner.
        boot=(
            'import runpy,sys;'
            f'sys.executable={str(executable_shim)!r};'
            f'sys.argv={["src.service.daemon",*args]!r};'
            'runpy.run_module("src.service.daemon",run_name="__main__")'
        )
        cmd=[sys.executable,'-B','-c',boot]
    return subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,
                          text=True,timeout=35)


def _interpreter_guard_shim(tmp_path):
    """Child pre-import guard without assuming sitecustomize path precedence."""
    executable=tmp_path/'guarded-python'
    executable.write_text(
        '#!'+sys.executable+'\n'
        'import os, runpy, sys\n'
        'runpy.run_path(os.environ["WOW_G50C_GUARD_SCRIPT"])\n'
        'assert sys.argv[1] == "-m", sys.argv\n'
        'mod=sys.argv[2]\n'
        'sys.argv=sys.argv[2:]\n'
        'runpy.run_module(mod,run_name="__main__")\n',
        encoding='utf-8',
    )
    executable.chmod(0o755)
    return executable


def test_enqueued_historical_worker_is_actually_spawned_and_guarded(tmp_path):
    store, job = _enqueue(tmp_path)
    env, audit = _guard_environment(tmp_path, 'child_imports.log')
    shim=_interpreter_guard_shim(tmp_path)
    # Negative control: verify the exact worker shim blocks scorer imports.
    control = subprocess.run([str(shim),'-m',
        'src.rulesets.forever.classes.druid.engine'],
        cwd=ROOT,env=env,capture_output=True,text=True,timeout=10)
    assert control.returncode != 0 and 'legacy scorer import forbidden' in control.stderr
    audit.write_text('')
    result = _run_cold_daemon_once(store.path, tmp_path/'runs', env, executable_shim=shim)
    assert result.returncode == 0, result.stderr
    attempts=store.list_attempts(job['id'])
    assert len(attempts)==1
    attempt=attempts[0]
    assert attempt['state']=='failed',attempt
    manifest=json.loads((Path(attempt['run_root'])/'attempt_manifest.json').read_text())
    assert manifest['executor']=='v2_runner'
    assert manifest['execution_authority']=='historical_legacy_cli'
    assert manifest['native_generic_job_supported'] is False
    assert manifest['command'][1:3]==['-m','src.v2.runner']
    lines=audit.read_text().splitlines()
    loaded=[line for line in lines if line.startswith('GUARD_LOADED:')]
    blocked=[line for line in lines if line.startswith('BLOCKED:')]
    # The daemon is unguarded in this probe; guard fires inside the real child.
    assert len(set(loaded)) == 1, (loaded, result.stderr)
    assert loaded[0].split(':')[1] != manifest['owner'].rsplit(':',1)[-1]
    assert blocked, 'no historical scorer attempted by real optimizer child'
    assert not store.list_publications()
    assert 'legacy scorer import forbidden' in (Path(attempt['run_root'])/'stderr.log').read_text()


def test_queue_isolation_mode_rejects_historical_job_without_spawning(tmp_path):
    store, job = _enqueue(tmp_path)
    env, audit = _guard_environment(tmp_path, 'isolation_imports.log')
    env['WOW_DISABLE_LEGACY_JOB_EXECUTION']='1'
    result = _run_cold_daemon_once(store.path, tmp_path/'runs', env)
    assert result.returncode==0,result.stderr
    attempts=store.list_attempts(job['id'])
    assert len(attempts)==1 and attempts[0]['state']=='failed'
    root=Path(attempts[0]['run_root'])
    manifest=json.loads((root/'attempt_manifest.json').read_text())
    assert manifest['execution_authority']=='historical_legacy_cli'
    assert manifest['native_generic_job_supported'] is False
    assert not (root/'stdout.log').exists()
    assert not (root/'stderr.log').exists()
    assert 'legacy_job_execution_disabled' in store.get(job['id'])['error']
    assert any(e['kind']=='execution_rejected' for e in store.events_since(job_id=job['id']))
    assert not audit.exists() or 'BLOCKED:' not in audit.read_text()
    assert not store.list_publications()


def test_legacy_executor_authority_is_explicit_for_both_queue_modes():
    fast={'request':{'endpoint_mode':'fast','ruleset':'forever',
                     'class_name':'mage','start_level':10,'end_level':10,
                     'forever_build_as_of':'2026-10-08','config':{}}}
    plan=executor_for(fast).plan(fast)
    assert plan.execution_authority=='historical_legacy_cli'
    assert plan.native_generic_job_supported is False
    mc={'request':{'endpoint_mode':'mc','ruleset':'forever',
                   'class_name':'mage','start_level':11,'end_level':60,
                   'forever_build_as_of':'2026-10-08','config':{}}}
    plan=executor_for(mc).plan(mc)
    assert plan.execution_authority=='historical_legacy_cli'
    assert plan.native_generic_job_supported is False
