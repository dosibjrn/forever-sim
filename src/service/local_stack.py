from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
import uuid
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = ROOT / '.runtime'
STATE_FILE = RUNTIME_DIR / 'local_stack.json'
COMMAND_FILE = RUNTIME_DIR / 'local_stack.command.json'


def _write_json(path: Path, obj: dict[str, Any], *, best_effort: bool = False) -> bool:
    """Write small runtime JSON safely across Windows file-lock races.

    Windows can reject ``os.replace`` while another process, an indexer, or AV has
    the destination open without delete sharing.  State publication is heartbeat
    metadata and must never take the supervised stack down because of that race.

    Prefer an atomic replace from a writer-unique temp file.  On transient sharing
    violations retry briefly, then fall back to an in-place write (which Windows
    commonly permits even when rename/delete is denied).  Readers already tolerate
    malformed/partial JSON and the supervisor republishes once per second.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, sort_keys=True)
    tmp = path.with_name(f'{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        tmp.write_text(payload, encoding='utf-8')
        for delay in (0.0, 0.01, 0.025, 0.05, 0.10, 0.20):
            if delay:
                time.sleep(delay)
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:
                continue

        # ``replace`` can remain forbidden on Windows solely because the existing
        # destination lacks FILE_SHARE_DELETE.  Updating that file in place is a
        # useful fallback and keeps service-start.sh alive.
        for delay in (0.0, 0.025, 0.05, 0.10, 0.20):
            if delay:
                time.sleep(delay)
            try:
                path.write_text(payload, encoding='utf-8')
                return True
            except PermissionError:
                continue
        if best_effort:
            return False
        raise PermissionError(f'could not update runtime state file: {path}')
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except PermissionError:
            pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _terminate(proc: subprocess.Popen[Any] | None, *, timeout: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _spawn(name: str, argv: list[str], *, env: dict[str, str], log_dir: Path) -> tuple[subprocess.Popen[Any], Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / f'{name}.log', 'a', encoding='utf-8', buffering=1)
    creationflags = 0
    if os.name == 'nt':
        creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    proc = subprocess.Popen(
        argv,
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    return proc, log


def request_stop(command: str = 'stop-all') -> int:
    state = _read_json(STATE_FILE)
    token = str(state.get('token') or '')
    if not token:
        print('[local-stack] no running local stack state found', file=sys.stderr)
        return 1
    _write_json(COMMAND_FILE, {'token': token, 'command': command, 'created_at': time.time()})
    print(f'[local-stack] requested {command}')
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Launch and supervise local optimizer API + daemon + listener')
    p.add_argument('--service-port', type=int, default=8765)
    p.add_argument('--listener-port', type=int, default=8766)
    p.add_argument('--class', dest='class_name', default='paladin', choices=('mage', 'paladin', 'druid', 'hunter'))
    p.add_argument('--ruleset', default='forever')
    p.add_argument('--max-jobs', type=int, default=2)
    p.add_argument('--db', default=str(ROOT / 'state' / 'optimizer_service.sqlite3'))
    p.add_argument('--runs-root', default=str(ROOT / 'state' / 'runs'))
    p.add_argument('--max-resource-units', type=int, default=2)
    p.add_argument('--no-browser', action='store_true')
    p.add_argument('--stop', action='store_true')
    p.add_argument('--stop-workers', action='store_true')
    args = p.parse_args(argv)

    if args.stop:
        return request_stop('stop-all')
    if args.stop_workers:
        return request_stop('stop-daemon')

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        COMMAND_FILE.unlink()
    except FileNotFoundError:
        pass

    token = secrets.token_urlsafe(24)
    base_env = os.environ.copy()
    base_env['PYTHONUTF8'] = '1'
    base_env['PYTHONIOENCODING'] = 'utf-8'
    base_env['WOW_OPTIMIZER_SERVICE_URL'] = f'http://127.0.0.1:{args.service_port}'
    base_env['WOW_LOCAL_STACK_STATE'] = str(STATE_FILE)
    base_env['WOW_LOCAL_STACK_COMMAND'] = str(COMMAND_FILE)
    base_env['WOW_LOCAL_STACK_TOKEN'] = token

    children: dict[str, subprocess.Popen[Any] | None] = {'api': None, 'daemon': None, 'listener': None}
    logs: list[Any] = []
    stopping = False

    def publish_state() -> None:
        _write_json(STATE_FILE, {
            'supervisor_pid': os.getpid(),
            'token': token,
            'service_url': f'http://127.0.0.1:{args.service_port}',
            'listener_url': f'http://127.0.0.1:{args.listener_port}/decisions',
            'children': {
                name: {'pid': proc.pid if proc and proc.poll() is None else None,
                       'running': bool(proc and proc.poll() is None)}
                for name, proc in children.items()
            },
            'updated_at': time.time(),
        }, best_effort=True)

    def stop_all(*_unused: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    try:
        proc, log = _spawn('api', [sys.executable, '-m', 'src.service.http_api', '--host', '127.0.0.1', '--port', str(args.service_port), '--db', str(args.db)], env=base_env, log_dir=RUNTIME_DIR)
        children['api'] = proc; logs.append(log)
        proc, log = _spawn('daemon', [sys.executable, '-m', 'src.service.daemon', '--db', str(args.db), '--runs-root', str(args.runs_root), '--max-jobs', str(args.max_jobs), '--max-resource-units', str(args.max_resource_units)], env=base_env, log_dir=RUNTIME_DIR)
        children['daemon'] = proc; logs.append(log)
        listener_cmd = [sys.executable, '-m', 'src.listener', '--host', '127.0.0.1', '--port', str(args.listener_port), '--open-path', '/decisions', '--ruleset', args.ruleset, '--class', args.class_name]
        if args.no_browser:
            listener_cmd.append('--no-browser')
        proc, log = _spawn('listener', listener_cmd, env=base_env, log_dir=RUNTIME_DIR)
        children['listener'] = proc; logs.append(log)
        publish_state()
        print(f'[local-stack] listener  http://127.0.0.1:{args.listener_port}/decisions')
        print(f'[local-stack] service   http://127.0.0.1:{args.service_port}')
        print(f'[local-stack] workers   max_jobs={args.max_jobs} resource_units={args.max_resource_units}')
        print('[local-stack] logs      .runtime/*.log')
        print('[local-stack] Ctrl-C or ./service-stop.sh stops the whole stack')

        last_publish = 0.0
        while not stopping:
            now = time.time()
            if now - last_publish >= 1.0:
                publish_state(); last_publish = now
            cmd = _read_json(COMMAND_FILE)
            if cmd and str(cmd.get('token') or '') == token:
                command = str(cmd.get('command') or '')
                try:
                    COMMAND_FILE.unlink()
                except FileNotFoundError:
                    pass
                if command == 'stop-daemon':
                    _terminate(children.get('daemon'))
                    children['daemon'] = None
                    publish_state()
                elif command == 'stop-all':
                    stopping = True
                    break
            # Fail closed if the UI/listener dies: keep service/daemon alive, but report it.
            time.sleep(0.20)
    finally:
        for name in ('listener', 'daemon', 'api'):
            _terminate(children.get(name))
            children[name] = None
        publish_state()
        for log in logs:
            try: log.close()
            except Exception: pass
        try:
            COMMAND_FILE.unlink()
        except FileNotFoundError:
            pass
        print('[local-stack] stopped')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
