"""G50d: real cold service→listener HTTP + empty worker startup import isolation.

Uses G50c's deny-guard *before* each process imports the production module.
A live socket and process-specific audit are required; no mocked ServiceClient.
"""
from __future__ import annotations

import json

from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from tests.test_g50c_cold_service_http_isolation import _guard_environment, _http_json, _unused_local_port, ROOT


def _spawn_guarded(module: str, args: list[str], env: dict):
    bootstrap = (
        'import os,runpy,sys;'
        'runpy.run_path(os.environ["WOW_G50C_GUARD_SCRIPT"]);'
        f'sys.argv=[{module!r}]+{args!r};'
        f'runpy.run_module({module!r},run_name="__main__")'
    )
    return subprocess.Popen(
        [sys.executable, '-B', '-c', bootstrap], cwd=ROOT, env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, text=True,
    )


def _ready(proc, url, audit, *, timeout=25):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f'cold process exited {proc.returncode}: {proc.stderr.read()}')
        try:
            with urlopen(url, timeout=0.7) as response:
                assert response.status == 200
            assert f'GUARD_LOADED:{proc.pid}' in audit.read_text()
            return
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.12)
    raise AssertionError(f'cold process never became ready: {url}')


def _stop(proc):
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate(timeout=5)
    assert proc.poll() is not None


def test_cold_listener_to_service_generic_fail_closed_under_legacy_import_deny(tmp_path):
    service_env, service_audit = _guard_environment(tmp_path, 'service_g50d_imports.log')
    listener_env, listener_audit = _guard_environment(tmp_path, 'listener_g50d_imports.log')
    service_port, listener_port = _unused_local_port(), _unused_local_port()
    assert service_port != listener_port
    service_base=f'http://127.0.0.1:{service_port}'
    listener_base=f'http://127.0.0.1:{listener_port}'
    listener_env['WOW_OPTIMIZER_SERVICE_URL'] = service_base
    listener_env['WOW_LISTENER_OFFLINE_DECISIONS'] = '0'
    service=_spawn_guarded('src.service.http_api', [
        '--host','127.0.0.1','--port',str(service_port),
        '--db',str(tmp_path/'queue.sqlite3'),'--project-root',str(ROOT),
    ], service_env)
    listener=None
    try:
        _ready(service,service_base+'/health',service_audit)
        listener=_spawn_guarded('src.listener', [
            '--host','127.0.0.1','--port',str(listener_port),
            '--no-browser','--class','druid', '--ruleset','forever',
        ], listener_env)
        _ready(listener,listener_base+'/decisions',listener_audit,timeout=30)

        # True cold listener→service proxy, not a direct service call or stub.
        code, response = _http_json(listener_base+'/api/decisions?backend=generic&class=druid&level=10',timeout=60)
        assert code==200, (code,response)
        assert response['active_backend']=='generic'
        assert response['backend_selection']['legacy_fallback'] is False
        assert len(response['decisions'])==7
        assert len(response['native_route_decisions'])==26

        # Same payload/authority as a service request; no local artifact fallback.
        service_code, service_response = _http_json(service_base+'/api/v1/decisions?backend=generic&class=druid&level=10',timeout=60)
        assert service_code==200
        assert response==service_response

        # Disabled oracle and default must fail closed at *both* boundaries.
        for query in ('backend=legacy&class=druid&level=10',
                      'backend=compare&class=druid&level=10',
                      'class=druid&level=10'):
            status, body=_http_json(listener_base+'/api/decisions?'+query,timeout=12)
            assert status==503,(query,status,body)
            assert body['offline_fallback'] is False
            assert 'decisions' not in body

        assert f'GUARD_LOADED:{service.pid}' in service_audit.read_text()
        assert f'GUARD_LOADED:{listener.pid}' in listener_audit.read_text()
        assert 'BLOCKED:' not in service_audit.read_text(),service_audit.read_text()
        assert 'BLOCKED:' not in listener_audit.read_text(),listener_audit.read_text()

        # A stopped service must not cause the still-live listener to compute
        # a fake success via its historical in-process optimizer path.
        _stop(service)
        dead_status, dead_body = _http_json(listener_base+'/api/decisions?backend=generic&class=druid&level=10',timeout=12)
        assert dead_status==503,(dead_status,dead_body)
        assert dead_body['offline_fallback'] is False
        assert 'decisions' not in dead_body
    finally:
        if listener is not None:_stop(listener)
        _stop(service)


def test_cold_queue_daemon_empty_run_starts_without_legacy_scorer_imports(tmp_path):
    """Worker startup only; NOT proof of an actual optimized job execution."""
    env,audit=_guard_environment(tmp_path,'daemon_imports.log')
    db=str(tmp_path/'empty_queue.sqlite3')
    # Inventory the real daemon/Scheduler import graph after its empty-queue
    # startup. This is deliberately not a claim about a queued job child.
    audit_modules=tmp_path/'daemon_startup_modules.json'
    boot=(
        'import json,os,runpy,sys\n'
        'runpy.run_path(os.environ["WOW_G50C_GUARD_SCRIPT"])\n'
        'sys.argv=["src.service.daemon","--once","--db",'+repr(db)+',"--runs-root",'+repr(str(tmp_path/'runs'))+']\n'
        'try:\n'
        '    runpy.run_module("src.service.daemon",run_name="__main__")\n'
        'except SystemExit as exc:\n'
        '    exit_code=exc.code\n'
        'else:\n'
        '    exit_code=0\n'
        'mods=sorted(m for m in sys.modules if m.startswith("src."))\n'
        'with open('+repr(str(audit_modules))+',"w") as fp: json.dump(mods,fp,indent=2)\n'
        'sys.exit(exit_code)\n'
    )
    result=subprocess.run([sys.executable,'-B','-c',boot],cwd=ROOT,env=env,capture_output=True,text=True,timeout=25)
    assert result.returncode==0, result.stderr
    assert 'GUARD_LOADED:' in audit.read_text()
    assert 'BLOCKED:' not in audit.read_text(),audit.read_text()
    assert Path(db).exists()
    loaded=json.loads(audit_modules.read_text())
    assert 'src.service.scheduler' in loaded
    assert 'src.service.executors' in loaded
    assert 'src.service.store' in loaded
    assert not any(m.endswith(('.engine', '.mechanics'))
                   and m.startswith('src.rulesets.forever.classes.') for m in loaded)
