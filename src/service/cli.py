from __future__ import annotations

import argparse
import json
from pathlib import Path

from .checkpoints import classify_compatibility
from .client import DEFAULT_SERVICE_URL, ServiceClient, ServiceClientError
from .models import JobRequest, JobState
from .store import QueueStore

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "state" / "service" / "queue.sqlite3"


def _print_job(job: dict) -> None:
    req = job["request"]
    print(
        f"{job['id']}  {job['state']:<9} p={job['priority']:<3} "
        f"{req['ruleset']}/{req['class_name']} L{req['start_level']}→{req['end_level']} "
        f"{req['objective']} {req['endpoint_mode']}"
    )


def _request_body(args) -> dict:
    return {
        "ruleset": args.ruleset,
        "class_name": args.class_name,
        "start_level": args.start_level,
        "end_level": args.end_level,
        "objective": args.objective,
        "endpoint_mode": args.endpoint_mode,
        "forever_build_as_of": args.forever_build_as_of,
        "priority": args.priority,
        "config": json.loads(args.config_json),
        "deduplicate": not args.no_dedup,
    }


def _run_http(args) -> int:
    c = ServiceClient(args.service_url, timeout=args.timeout)
    if args.cmd == "enqueue":
        job, created = c.enqueue(_request_body(args)); print("enqueued" if created else "duplicate-active"); _print_job(job); return 0
    if args.cmd == "queue":
        for job in c.list_jobs(): _print_job(job)
        return 0
    if args.cmd == "get": print(json.dumps(c.get_job(args.job_id), indent=2, sort_keys=True)); return 0
    if args.cmd == "priority": _print_job(c.set_priority(args.job_id, args.value)); return 0
    if args.cmd == "reorder":
        for job in c.reorder(args.job_ids): _print_job(job)
        return 0
    if args.cmd in {"pause", "resume", "cancel"}: _print_job(c.control(args.job_id, args.cmd)); return 0
    if args.cmd == "attempts": print(json.dumps(c.attempts(args.job_id), indent=2, sort_keys=True)); return 0
    if args.cmd == "checkpoints": print(json.dumps(c.checkpoints(args.job_id), indent=2, sort_keys=True)); return 0
    if args.cmd == "publications": print(json.dumps(c.publications(), indent=2, sort_keys=True)); return 0
    if args.cmd == "events": print(json.dumps(c.events(after=args.after, job_id=args.job_id, limit=args.limit), indent=2, sort_keys=True)); return 0
    if args.cmd == "health": print(json.dumps(c.health(), indent=2, sort_keys=True)); return 0
    if args.cmd == "checkpoint-compat":
        # Compatibility classification intentionally remains maintenance-only: it
        # compares raw persisted manifests and therefore requires explicit direct mode.
        raise SystemExit("checkpoint-compat requires --direct")
    return 2


def _run_direct(args) -> int:
    store = QueueStore(args.db)
    if args.cmd == "enqueue":
        body = _request_body(args)
        request = JobRequest(
            ruleset=body["ruleset"], class_name=body["class_name"], start_level=body["start_level"], end_level=body["end_level"],
            objective=body["objective"], endpoint_mode=body["endpoint_mode"], forever_build_as_of=body.get("forever_build_as_of"), config=body["config"],
        )
        job, created = store.enqueue(request, priority=args.priority, deduplicate=not args.no_dedup)
        print("enqueued" if created else "duplicate-active"); _print_job(job); return 0
    if args.cmd == "queue":
        for job in store.list_jobs(): _print_job(job)
        return 0
    if args.cmd == "get":
        job = store.get(args.job_id)
        if job is None: raise SystemExit(f"unknown job {args.job_id}")
        print(json.dumps(job, indent=2, sort_keys=True)); return 0
    if args.cmd == "priority": _print_job(store.set_priority(args.job_id, args.value)); return 0
    if args.cmd == "reorder":
        for job in store.reorder(args.job_ids): _print_job(job)
        return 0
    if args.cmd == "pause": _print_job(store.request_control(args.job_id, "pause")); return 0
    if args.cmd == "resume": _print_job(store.transition(args.job_id, JobState.QUEUED)); return 0
    if args.cmd == "cancel": _print_job(store.request_control(args.job_id, "cancel")); return 0
    if args.cmd == "attempts": print(json.dumps(store.list_attempts(args.job_id), indent=2, sort_keys=True)); return 0
    if args.cmd == "checkpoints": print(json.dumps(store.list_checkpoints(args.job_id), indent=2, sort_keys=True)); return 0
    if args.cmd == "checkpoint-compat":
        job=store.get(args.job_id)
        if job is None: raise SystemExit(f"unknown job {args.job_id}")
        rows=[]
        for cp in store.list_checkpoints(): rows.append({"checkpoint_id":cp["id"],"path":cp["path"],"compatibility":classify_compatibility(cp["request"],job["request"]).value})
        print(json.dumps(rows, indent=2, sort_keys=True)); return 0
    if args.cmd == "publications": print(json.dumps(store.list_publications(), indent=2, sort_keys=True)); return 0
    if args.cmd == "events": print(json.dumps(store.events_since(after_seq=args.after, job_id=args.job_id, limit=args.limit), indent=2, sort_keys=True)); return 0
    if args.cmd == "health": print(json.dumps({"ok": True, "mode": "direct", "db": str(args.db)}, indent=2, sort_keys=True)); return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Optimizer service control client")
    p.add_argument("--service-url", default=DEFAULT_SERVICE_URL, help="optimizer service base URL (default: %(default)s)")
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--direct", action="store_true", help="explicit recovery/test mode: access QueueStore directly")
    p.add_argument("--db", default=str(DEFAULT_DB), help="QueueStore path used only with --direct")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enqueue")
    e.add_argument("--ruleset", required=True); e.add_argument("--class", dest="class_name", required=True)
    e.add_argument("--start-level", type=int, required=True); e.add_argument("--end-level", type=int, required=True)
    e.add_argument("--objective", default="cumulative"); e.add_argument("--endpoint-mode", choices=["smooth","fast","mc","generic_decision"], default="smooth")
    e.add_argument("--priority", type=int, default=0); e.add_argument("--forever-as-of", dest="forever_build_as_of", default=None, help="Forever beta build date YYYY-MM-DD"); e.add_argument("--config-json", default="{}"); e.add_argument("--no-dedup", action="store_true")

    sub.add_parser("queue"); sub.add_parser("health")
    g = sub.add_parser("get"); g.add_argument("job_id")
    pr = sub.add_parser("priority"); pr.add_argument("job_id"); pr.add_argument("value", type=int)
    ro = sub.add_parser("reorder"); ro.add_argument("job_ids", nargs="+")
    for name in ("pause", "resume", "cancel"):
        sp = sub.add_parser(name); sp.add_argument("job_id")
    at = sub.add_parser("attempts"); at.add_argument("job_id")
    cp = sub.add_parser("checkpoints"); cp.add_argument("job_id")
    cc = sub.add_parser("checkpoint-compat"); cc.add_argument("job_id")
    sub.add_parser("publications")
    ev = sub.add_parser("events"); ev.add_argument("--job-id"); ev.add_argument("--after", type=int, default=0); ev.add_argument("--limit", type=int, default=200)

    args = p.parse_args(argv)
    try:
        return _run_direct(args) if args.direct else _run_http(args)
    except ServiceClientError as exc:
        raise SystemExit(f"{exc}\nStart src.service.http_api or use --direct for explicit local recovery/test access.") from exc


if __name__ == "__main__":
    raise SystemExit(main())
