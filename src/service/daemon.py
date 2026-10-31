from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from .cli import DEFAULT_DB, ROOT
from .scheduler import Scheduler
from .store import QueueStore

DEFAULT_RUNS = ROOT / "state" / "runs"

def main(argv=None)->int:
    p=argparse.ArgumentParser(description="Long-lived bounded-concurrency optimizer service daemon")
    p.add_argument("--db",default=str(DEFAULT_DB)); p.add_argument("--runs-root",default=str(DEFAULT_RUNS))
    p.add_argument("--lease-seconds",type=float,default=30.0); p.add_argument("--poll-seconds",type=float,default=1.0)
    p.add_argument("--max-jobs",type=int,default=1,help="maximum simultaneous optimizer jobs")
    p.add_argument("--max-resource-units",type=int,default=1,help="maximum summed config.workers across running jobs")
    p.add_argument("--once",action="store_true",help="run at most one queued job and exit")
    args=p.parse_args(argv)
    scheduler=Scheduler(
        QueueStore(args.db), runs_root=args.runs_root, lease_seconds=args.lease_seconds,
        max_active_jobs=args.max_jobs, max_resource_units=args.max_resource_units,
    )
    if args.once:
        scheduler.run_once(project_root=ROOT)
        return 0

    # Optimizers are subprocesses; threads only supervise process lifetime and
    # heartbeats. Admission in SQLite remains the source of truth.
    with ThreadPoolExecutor(max_workers=max(1,args.max_jobs), thread_name_prefix="optimizer-job") as pool:
        active=set()
        while True:
            done={f for f in active if f.done()}
            for f in done:
                active.remove(f)
                # Surface unexpected supervisor failures instead of silently
                # shrinking daemon capacity. Normal job failures are durable state.
                f.result()

            admitted=False
            while len(active) < max(1,args.max_jobs):
                claimed=scheduler.claim()
                if claimed is None:
                    break
                active.add(pool.submit(scheduler.run_claimed,claimed,project_root=ROOT))
                admitted=True

            if not admitted and not done:
                time.sleep(args.poll_seconds)

if __name__ == "__main__": raise SystemExit(main())
