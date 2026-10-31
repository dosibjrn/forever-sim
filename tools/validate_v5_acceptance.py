from __future__ import annotations
import os, signal, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STAGES=[
    ('V0','run-validation-fast.sh',25),
    ('V1','run-validation-v1.sh',20),
    ('V2','run-validation-v2.sh',20),
    ('V3','run-validation-v3.sh',15),
    ('V4','run-validation-v4.sh',20),
]
LOGDIR=ROOT/'.runtime'/'validation-v5'
LOGDIR.mkdir(parents=True, exist_ok=True)

def run_stage(name, script, timeout_s):
    log=LOGDIR/f'{name.lower()}.log'
    start=time.perf_counter()
    with log.open('wb') as fh:
        proc=subprocess.Popen(
            ['bash', str(ROOT/script)], cwd=ROOT,
            stdout=fh, stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},
        )
        try:
            rc=proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try: os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                proc.wait(timeout=2)
            rc=124
        finally:
            # Acceptance stages may spawn browser/listener/daemon descendants. Even
            # when pytest exits cleanly, tear down the whole stage process group so
            # the aggregate gate itself has no orphaned background processes.
            try: os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError: pass
    elapsed=time.perf_counter()-start
    tail=log.read_text(encoding='utf-8', errors='replace')[-5000:]
    print(f'===== {name} =====')
    print(tail.rstrip())
    if rc != 0:
        print(f'[validate-v5] FAIL stage={name} rc={rc} elapsed={elapsed:.2f}s log={log}', file=sys.stderr)
        return False
    print(f'[validate-v5] {name}=PASS elapsed={elapsed:.2f}s log={log}')
    return True

def main():
    all_start=time.perf_counter()
    for args in STAGES:
        if not run_stage(*args):
            return 1
    total=time.perf_counter()-all_start
    print(f'[validate-v5] PASS V0-V4 total={total:.2f}s')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
