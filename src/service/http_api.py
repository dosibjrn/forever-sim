from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import time
from urllib.parse import parse_qs, urlparse

from .models import JobRequest, JobState
from .intents import compile_intent, public_intent_from_job
from .item_operations import add_item
from .item_refresh import start_refresh, get_refresh, latest_refresh
from .abilities_refresh import (
    start_refresh as start_abilities_refresh,
    get_refresh as get_abilities_refresh,
    latest_refresh as latest_abilities_refresh,
    catalogue_status as abilities_catalogue_status,
)
from .store import QueueStore
from .publication import read_current_queued_generic_decision, QueuedGenericDecisionUnavailable
from .checkpoints import decorate_saved_states, classify_compatibility, Compatibility, select_resume_checkpoint, file_sha256
from src.v2.decision_dashboard import build_decision_payload, LegacyDecisionsDisabled

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "state" / "service" / "queue.sqlite3"
API_PREFIX = "/api/v1"


def _json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _request_from_body(body: dict) -> JobRequest:
    required = ("ruleset", "class_name", "start_level", "end_level")
    missing = [k for k in required if k not in body]
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))
    return JobRequest(
        ruleset=str(body["ruleset"]),
        class_name=str(body["class_name"]),
        start_level=int(body["start_level"]),
        end_level=int(body["end_level"]),
        objective=str(body.get("objective", "cumulative")),
        endpoint_mode=str(body.get("endpoint_mode", "smooth")),
        source_snapshot=str(body.get("source_snapshot", "current")),
        engine_semantic_hash=str(body.get("engine_semantic_hash", "current")),
        policy_space_version=str(body.get("policy_space_version", "current")),
        forever_build_as_of=body.get("forever_build_as_of"),
        config=dict(body.get("config") or {}),
        validation_modes=tuple(body.get("validation_modes") or ()),
    )


class OptimizerAPIHandler(BaseHTTPRequestHandler):
    server_version = "ForeverOptimizerService/1"
    protocol_version = "HTTP/1.1"

    @property
    def store(self) -> QueueStore:
        return self.server.store  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        # Quiet by default; the daemon/service caller owns process logging.
        if getattr(self.server, "verbose", False):  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    def _send_json(self, status: int, value) -> None:
        data = _json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        raw_len = self.headers.get("Content-Length", "0")
        try:
            size = int(raw_len)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if size < 0 or size > 1_048_576:
            raise ValueError("request body too large")
        raw = self.rfile.read(size) if size else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    @staticmethod
    def _parts(path: str) -> list[str]:
        return [p for p in path.split("/") if p]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/health":
                self._send_json(HTTPStatus.OK, {"ok": True, "service": "optimizer", "api_version": 1})
                return
            if path == f"{API_PREFIX}/items/refresh":
                task_id=(query.get("task_id") or [None])[0]
                value=get_refresh(task_id) if task_id else latest_refresh()
                self._send_json(HTTPStatus.OK, {"refresh": value})
                return
            if path == f"{API_PREFIX}/abilities/refresh":
                task_id=(query.get("task_id") or [None])[0]
                value=get_abilities_refresh(task_id) if task_id else latest_abilities_refresh()
                self._send_json(HTTPStatus.OK, {"refresh": value,
                                                "catalogue": abilities_catalogue_status()})
                return
            if path == f"{API_PREFIX}/status":
                snapshot=self.store.status_snapshot()
                snapshot.update({"ok": True, "service": "optimizer", "api_version": 1})
                self._send_json(HTTPStatus.OK, snapshot)
                return
            if path == f"{API_PREFIX}/decisions/queued":
                try:
                    cls=(query.get("class") or [""])[0]
                    backend=(query.get("backend") or [""])[0]
                    level_raw=(query.get("level") or [""])[0]
                    level=int(level_raw)
                    payload=read_current_queued_generic_decision(
                        self.server.project_root, class_name=cls, level=level, backend=backend)
                except (ValueError, TypeError) as exc:
                    self._error(HTTPStatus.BAD_REQUEST, str(exc)); return
                except QueuedGenericDecisionUnavailable as exc:
                    self._error(HTTPStatus.CONFLICT, str(exc)); return
                self._send_json(HTTPStatus.OK, payload); return
            if path == f"{API_PREFIX}/decisions":
                try:
                    level=int((query.get("level") or [""])[0]) if query.get("level") else None
                except (TypeError, ValueError):
                    raise ValueError("level must be an integer")
                backend=(query.get("backend") or [None])[0]
                cls=(query.get("class") or [None])[0]
                payload=build_decision_payload(
                    project_root=self.server.project_root, selected_level=level,
                    backend_id=backend, class_name=cls,
                )
                self._send_json(HTTPStatus.OK, payload)
                return
            if path == f"{API_PREFIX}/jobs":
                states = []
                for raw in query.get("state", []):
                    states.extend(x for x in raw.split(",") if x)
                self._send_json(HTTPStatus.OK, {"jobs": self.store.list_jobs(states=states or None)})
                return
            if path == f"{API_PREFIX}/publications":
                job_id=(query.get("job_id") or [None])[0]
                class_name=(query.get("class_name") or [None])[0]
                limit=int((query.get("limit") or ["100"])[0])
                self._send_json(HTTPStatus.OK, {"publications": self.store.list_publications(job_id=job_id,class_name=class_name,limit=limit)})
                return
            if path == f"{API_PREFIX}/events":
                after = int(query.get("after", ["0"])[0])
                limit = min(1000, max(1, int(query.get("limit", ["200"])[0])))
                self._send_json(HTTPStatus.OK, {"events": self.store.events_since(after_seq=after, limit=limit)})
                return
            if path == f"{API_PREFIX}/events/stream":
                self._stream_events(query)
                return

            parts = self._parts(path)
            # /api/v1/jobs/<id>[/resource]
            if len(parts) >= 4 and parts[:3] == ["api", "v1", "jobs"]:
                job_id = parts[3]
                job = self.store.get(job_id)
                if job is None:
                    self._error(HTTPStatus.NOT_FOUND, f"unknown job {job_id}")
                    return
                if len(parts) == 4:
                    self._send_json(HTTPStatus.OK, job)
                    return
                if len(parts) == 5 and parts[4] == "attempts":
                    self._send_json(HTTPStatus.OK, {"attempts": self.store.list_attempts(job_id)})
                    return
                if len(parts) == 5 and parts[4] == "checkpoints":
                    self._send_json(HTTPStatus.OK, {"checkpoints": self.store.list_checkpoints(job_id)})
                    return
                if len(parts) == 5 and parts[4] == "saved-states":
                    states=decorate_saved_states(self.store.list_checkpoints(), job["request"], limit=24)
                    seed_supported=(job["request"].get("endpoint_mode")=="mc" and job["request"].get("class_name")=="mage")
                    for item in states:
                        item["actions"]={
                            "resume": item["compatibility"]==Compatibility.RESUME.value,
                            "seed_only": item["compatibility"]==Compatibility.SEED_ONLY.value and seed_supported,
                        }
                        if item["compatibility"]==Compatibility.SEED_ONLY.value and not seed_supported:
                            item["seed_unavailable_reason"]="seed-only import is currently supported by the Mage MC executor only"
                    self._send_json(HTTPStatus.OK, {"job_id":job_id,"saved_states":states})
                    return
                if len(parts) == 5 and parts[4] == "lineage":
                    self._send_json(HTTPStatus.OK, self.store.job_lineage(job_id))
                    return
                if len(parts) == 5 and parts[4] == "events":
                    after = int(query.get("after", ["0"])[0])
                    limit = min(1000, max(1, int(query.get("limit", ["200"])[0])))
                    self._send_json(HTTPStatus.OK, {"events": self.store.events_since(after_seq=after, job_id=job_id, limit=limit)})
                    return
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except LegacyDecisionsDisabled:
            # G50a isolation is an explicit unavailable state, not a fallback.
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "legacy_decisions_disabled",
                "offline_fallback": False,
                "legacy_fallback": False,
            })
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"internal error: {type(exc).__name__}")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json()
            if path == f"{API_PREFIX}/items/refresh":
                classes=body.get("classes")
                if classes is not None and not isinstance(classes, list):
                    raise ValueError("classes must be an array")
                result=start_refresh(classes)
                self._send_json(HTTPStatus.ACCEPTED, {"refresh": result})
                return
            if path == f"{API_PREFIX}/abilities/refresh":
                if set(body) - {'mode','max_details'}:
                    raise ValueError('unknown ability capture options')
                try:
                    result=start_abilities_refresh(mode=body.get('mode','index'),
                                                    max_details=body.get('max_details'))
                except RuntimeError as exc:
                    self._error(HTTPStatus.CONFLICT, str(exc))
                    return
                self._send_json(HTTPStatus.ACCEPTED, {"refresh": result})
                return
            if path == f"{API_PREFIX}/items/add":
                value = body.get("item", body.get("item_id", body.get("url")))
                result = add_item(value, class_name=body.get("class_name", body.get("class")))
                self._send_json(HTTPStatus.OK, result.as_dict())
                return
            if path == f"{API_PREFIX}/intents":
                compiled = compile_intent(body)
                job, created = self.store.enqueue(
                    compiled.request, priority=compiled.priority, deduplicate=compiled.deduplicate,
                )
                self.store.record_event(job["id"], "intent_submitted", {
                    "intent": public_intent_from_job(job), "summary": compiled.user_summary,
                })
                self._send_json(HTTPStatus.CREATED if created else HTTPStatus.OK, {
                    "created": created, "job": job, "intent": public_intent_from_job(job),
                    "summary": compiled.user_summary,
                })
                return
            if path == f"{API_PREFIX}/jobs":
                request = _request_from_body(body)
                if request.endpoint_mode not in {"smooth", "fast", "mc", "generic_decision"}:
                    raise ValueError("endpoint_mode must be smooth, fast, mc or generic_decision")
                if request.endpoint_mode == "generic_decision":
                    # Reject unsupported native scope at admission as well as
                    # executor time; never silently redirect to smooth/MC.
                    from .executors import executor_for
                    executor_for({"request": request.canonical_dict()}).plan({"request": request.canonical_dict()})
                job, created = self.store.enqueue(
                    request,
                    priority=int(body.get("priority", 0)),
                    deduplicate=bool(body.get("deduplicate", True)),
                )
                self._send_json(HTTPStatus.CREATED if created else HTTPStatus.OK, {"created": created, "job": job})
                return
            if path == f"{API_PREFIX}/queue/reorder":
                ids = body.get("job_ids")
                if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
                    raise ValueError("job_ids must be an array of strings")
                self._send_json(HTTPStatus.OK, {"jobs": self.store.reorder(ids)})
                return

            parts = self._parts(path)
            if len(parts) == 5 and parts[:3] == ["api", "v1", "jobs"]:
                job_id, action = parts[3], parts[4]
                if self.store.get(job_id) is None:
                    self._error(HTTPStatus.NOT_FOUND, f"unknown job {job_id}")
                    return
                if action in {"pause", "cancel", "checkpoint"}:
                    self._send_json(HTTPStatus.ACCEPTED if action == "checkpoint" else HTTPStatus.OK, self.store.request_control(job_id, action))
                    return
                if action == "resume":
                    source=self.store.get(job_id)
                    if source is None:
                        raise KeyError(job_id)
                    if source["state"] != JobState.PAUSED.value:
                        raise ValueError(f"cannot resume {source['state']} job")
                    # A queued job can be paused before its first attempt exists.
                    # That state needs no checkpoint: resume simply puts it back in
                    # the durable queue. Jobs paused after execution still require a
                    # strict compatible checkpoint so we never silently restart fresh.
                    if int(source.get("attempt_count") or 0) == 0:
                        self._send_json(HTTPStatus.OK, self.store.transition(job_id, JobState.QUEUED))
                        return
                    cp=select_resume_checkpoint(self.store.list_checkpoints(), source["request"], prefer_job_id=job_id)
                    if cp is None:
                        raise ValueError("no resumable checkpoint; choose a saved state or clone/rerun fresh")
                    self.store.select_saved_state(job_id,cp["id"],Compatibility.RESUME.value)
                    self._send_json(HTTPStatus.OK, self.store.transition(job_id, JobState.QUEUED))
                    return
                if action == "saved-state":
                    source=self.store.get(job_id)
                    if source["state"] == JobState.RUNNING.value:
                        raise ValueError("cannot change saved state while job is running")
                    if source["state"] == JobState.COMPLETED.value:
                        raise ValueError("completed job is immutable; clone/rerun before selecting saved state")
                    checkpoint_id=str(body.get("checkpoint_id") or "")
                    mode=str(body.get("mode") or "")
                    cp=self.store.get_checkpoint(checkpoint_id)
                    if cp is None:
                        raise KeyError(checkpoint_id)
                    actual=classify_compatibility(cp["request"],source["request"])
                    if mode != actual.value:
                        raise ValueError(f"saved state is {actual.value}, not {mode}")
                    if mode == Compatibility.INCOMPATIBLE.value:
                        raise ValueError("incompatible saved state cannot be selected")
                    if mode == Compatibility.SEED_ONLY.value and not (source["request"].get("endpoint_mode")=="mc" and source["request"].get("class_name")=="mage"):
                        raise ValueError("seed-only import is currently supported by the Mage MC executor only")
                    path=Path(cp["path"])
                    if not path.exists() or file_sha256(path) != cp["sha256"]:
                        raise ValueError("saved-state checkpoint missing or sha256 mismatch")
                    job=self.store.select_saved_state(job_id,checkpoint_id,mode)
                    if job["state"] in {JobState.PAUSED.value,JobState.FAILED.value,JobState.CANCELLED.value}:
                        job=self.store.transition(job_id,JobState.QUEUED)
                    self._send_json(HTTPStatus.OK,{"job":job,"checkpoint_id":checkpoint_id,"mode":mode})
                    return
                if action == "clone":
                    source=self.store.get(job_id)
                    overrides=body.get("overrides") or {}
                    if not isinstance(overrides,dict):
                        raise ValueError("overrides must be an object")
                    allowed={"ruleset","class_name","start_level","end_level","objective","endpoint_mode","source_snapshot","engine_semantic_hash","policy_space_version","forever_build_as_of","config","validation_modes"}
                    bad=sorted(set(overrides)-allowed)
                    if bad:
                        raise ValueError("unsupported clone override(s): "+", ".join(bad))
                    merged=dict(source["request"]); merged.update(overrides)
                    request=_request_from_body(merged)
                    job,created=self.store.enqueue(request,priority=int(body.get("priority",source.get("priority",0))),deduplicate=bool(body.get("deduplicate",False)))
                    self.store.record_event(job["id"],"cloned_from",{"source_job_id":job_id,"overrides":overrides})
                    self._send_json(HTTPStatus.CREATED if created else HTTPStatus.OK,{"created":created,"job":job,"source_job_id":job_id})
                    return
                if action == "priority":
                    if "priority" not in body:
                        raise ValueError("priority is required")
                    self._send_json(HTTPStatus.OK, self.store.set_priority(job_id, int(body["priority"])))
                    return
            self._error(HTTPStatus.NOT_FOUND, "not found")
        except KeyError as exc:
            self._error(HTTPStatus.NOT_FOUND, f"unknown job {exc.args[0]}")
        except ValueError as exc:
            self._error(HTTPStatus.CONFLICT if "cannot request" in str(exc) or "invalid transition" in str(exc) else HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"internal error: {type(exc).__name__}")

    def _stream_events(self, query: dict[str, list[str]]) -> None:
        header_cursor = self.headers.get("Last-Event-ID")
        cursor = int(query.get("after", [header_cursor or "0"])[0])
        follow = query.get("follow", ["1"])[0].lower() not in {"0", "false", "no"}
        heartbeat = min(30.0, max(0.25, float(query.get("heartbeat", ["5"])[0])))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive" if follow else "close")
        self.end_headers()
        last_write = time.monotonic()
        try:
            while True:
                rows = self.store.events_since(after_seq=cursor, limit=200)
                for event in rows:
                    cursor = max(cursor, int(event["seq"]))
                    payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
                    self.wfile.write(f"id: {event['seq']}\nevent: {event['kind']}\ndata: {payload}\n\n".encode("utf-8"))
                    last_write = time.monotonic()
                if rows:
                    self.wfile.flush()
                if not follow:
                    break
                if time.monotonic() - last_write >= heartbeat:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    last_write = time.monotonic()
                time.sleep(0.20)
        except (BrokenPipeError, ConnectionResetError):
            return


class OptimizerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, store: QueueStore, *, project_root: str | Path = ROOT, verbose: bool = False):
        self.store = store
        self.project_root = Path(project_root).resolve()
        self.verbose = verbose
        super().__init__(server_address, OptimizerAPIHandler)


def serve(*, host: str = "127.0.0.1", port: int = 8765, db: str | Path = DEFAULT_DB, project_root: str | Path = ROOT, verbose: bool = False) -> None:
    server = OptimizerHTTPServer((host, int(port)), QueueStore(db), project_root=project_root, verbose=verbose)
    print(f"[optimizer-api] http://{host}:{server.server_address[1]} db={db}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Forever optimizer service HTTP API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--project-root", default=str(ROOT))
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    serve(host=args.host, port=args.port, db=args.db, project_root=args.project_root, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
