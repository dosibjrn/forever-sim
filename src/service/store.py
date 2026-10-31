from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Iterable

from .models import JobRequest, JobState
from src.version import SOFTWARE_VERSION

_SCHEMA_VERSION = 5
_ACTIVE_STATES = (JobState.QUEUED.value, JobState.RUNNING.value, JobState.PAUSED.value)


class QueueStore:
    """Durable SQLite/WAL control-plane state for optimizer jobs and attempts."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self, *, immediate: bool = False):
        con = sqlite3.connect(self.path, timeout=30.0)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            if immediate:
                con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._conn(immediate=True) as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS service_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    dedup_key TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    position INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    error TEXT,
                    current_attempt_id TEXT,
                    control_requested TEXT,
                    selected_checkpoint_id TEXT,
                    selected_checkpoint_mode TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_queue
                    ON jobs(state, priority DESC, position ASC, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_jobs_dedup
                    ON jobs(dedup_key, state);
                CREATE TABLE IF NOT EXISTS job_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    lease_expires_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    run_root TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    error TEXT,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                    UNIQUE(job_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_attempts_job ON attempts(job_id, ordinal DESC);
                CREATE INDEX IF NOT EXISTS idx_attempts_lease ON attempts(state, lease_expires_at);
                CREATE TABLE IF NOT EXISTS checkpoint_artifacts (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    discovered_at REAL NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                    FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE,
                    UNIQUE(attempt_id, path)
                );
                CREATE INDEX IF NOT EXISTS idx_checkpoint_job ON checkpoint_artifacts(job_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS publications (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    state_root TEXT NOT NULL,
                    parent_id TEXT,
                    request_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                    FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_publications_created ON publications(created_at DESC);
                """
            )
            # Migration from P1 DBs created before the two control columns existed.
            cols = {r["name"] for r in con.execute("PRAGMA table_info(jobs)").fetchall()}
            if "current_attempt_id" not in cols:
                con.execute("ALTER TABLE jobs ADD COLUMN current_attempt_id TEXT")
            if "control_requested" not in cols:
                con.execute("ALTER TABLE jobs ADD COLUMN control_requested TEXT")
            if "selected_checkpoint_id" not in cols:
                con.execute("ALTER TABLE jobs ADD COLUMN selected_checkpoint_id TEXT")
            if "selected_checkpoint_mode" not in cols:
                con.execute("ALTER TABLE jobs ADD COLUMN selected_checkpoint_mode TEXT")
            row = con.execute("SELECT value FROM service_meta WHERE key='schema_version'").fetchone()
            if row is None:
                con.execute("INSERT INTO service_meta(key,value) VALUES('schema_version',?)", (str(_SCHEMA_VERSION),))
            else:
                version = int(row["value"])
                if version > _SCHEMA_VERSION:
                    raise RuntimeError(f"unsupported optimizer service DB schema {version} (expected <= {_SCHEMA_VERSION})")
                if version < _SCHEMA_VERSION:
                    con.execute("UPDATE service_meta SET value=? WHERE key='schema_version'", (str(_SCHEMA_VERSION),))

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        out = dict(row)
        out["request"] = json.loads(out.pop("request_json"))
        return out

    @staticmethod
    def _decode_attempt(row: sqlite3.Row | None) -> dict | None:
        return None if row is None else dict(row)

    def _event(self, con: sqlite3.Connection, job_id: str, kind: str, payload: dict | None = None) -> None:
        con.execute(
            "INSERT INTO job_events(job_id,kind,payload_json,created_at) VALUES(?,?,?,?)",
            (job_id, kind, json.dumps(payload or {}, sort_keys=True), time.time()),
        )

    def enqueue(self, request: JobRequest, *, priority: int = 0, deduplicate: bool = True) -> tuple[dict, bool]:
        now = time.time(); key = request.dedup_key()
        with self._conn(immediate=True) as con:
            if deduplicate:
                row = con.execute(
                    "SELECT * FROM jobs WHERE dedup_key=? AND state IN (?,?,?) ORDER BY created_at DESC LIMIT 1",
                    (key, *_ACTIVE_STATES),
                ).fetchone()
                if row is not None:
                    return self._decode(row), False
            next_pos = con.execute("SELECT COALESCE(MAX(position),0)+1 AS p FROM jobs").fetchone()["p"]
            job_id = uuid.uuid4().hex
            con.execute(
                "INSERT INTO jobs(id,dedup_key,request_json,state,priority,position,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (job_id,key,request.canonical_json(),JobState.QUEUED.value,int(priority),int(next_pos),now,now),
            )
            self._event(con, job_id, "enqueued", {"priority": int(priority)})
            return self._decode(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()), True

    def get(self, job_id: str) -> dict | None:
        with self._conn() as con:
            return self._decode(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def get_attempt(self, attempt_id: str) -> dict | None:
        with self._conn() as con:
            return self._decode_attempt(con.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone())

    def get_checkpoint(self, checkpoint_id: str) -> dict | None:
        with self._conn() as con:
            row=con.execute("SELECT * FROM checkpoint_artifacts WHERE id=?",(checkpoint_id,)).fetchone()
        if row is None:
            return None
        out=dict(row); out["request"]=json.loads(out.pop("request_json")); return out

    def select_saved_state(self, job_id: str, checkpoint_id: str, mode: str) -> dict:
        if mode not in {"resume","seed_only"}:
            raise ValueError("saved state mode must be resume or seed_only")
        with self._conn(immediate=True) as con:
            job=con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
            if job is None: raise KeyError(job_id)
            cp=con.execute("SELECT 1 FROM checkpoint_artifacts WHERE id=?",(checkpoint_id,)).fetchone()
            if cp is None: raise KeyError(checkpoint_id)
            con.execute("UPDATE jobs SET selected_checkpoint_id=?,selected_checkpoint_mode=?,updated_at=? WHERE id=?",(checkpoint_id,mode,time.time(),job_id))
            self._event(con,job_id,"saved_state_selected",{"checkpoint_id":checkpoint_id,"mode":mode})
            return self._decode(con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone())

    def clear_saved_state_selection(self, job_id: str) -> None:
        with self._conn(immediate=True) as con:
            if con.execute("SELECT 1 FROM jobs WHERE id=?",(job_id,)).fetchone() is None: raise KeyError(job_id)
            con.execute("UPDATE jobs SET selected_checkpoint_id=NULL,selected_checkpoint_mode=NULL,updated_at=? WHERE id=?",(time.time(),job_id))

    def list_attempts(self, job_id: str) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM attempts WHERE job_id=? ORDER BY ordinal", (job_id,)).fetchall()
            return [dict(r) for r in rows]

    def list_jobs(self, *, states: Iterable[str] | None = None) -> list[dict]:
        with self._conn() as con:
            if states:
                vals = tuple(str(x) for x in states); q = ",".join("?" for _ in vals)
                rows = con.execute(
                    f"SELECT * FROM jobs WHERE state IN ({q}) ORDER BY CASE state WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END, priority DESC, position ASC, created_at ASC",
                    vals,
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM jobs ORDER BY CASE state WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END, priority DESC, position ASC, created_at ASC"
                ).fetchall()
            return [self._decode(r) for r in rows]

    def set_priority(self, job_id: str, priority: int) -> dict:
        with self._conn(immediate=True) as con:
            row=con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
            if row is None: raise KeyError(job_id)
            if row["state"] != JobState.QUEUED.value: raise ValueError("priority can only change for queued jobs")
            con.execute("UPDATE jobs SET priority=?,updated_at=? WHERE id=?",(int(priority),time.time(),job_id))
            self._event(con,job_id,"priority_changed",{"priority":int(priority)})
            return self._decode(con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone())

    def reorder(self, ordered_job_ids: list[str]) -> list[dict]:
        with self._conn(immediate=True) as con:
            rows = con.execute("SELECT id,state FROM jobs WHERE id IN (%s)" % ",".join("?" * len(ordered_job_ids)), ordered_job_ids).fetchall() if ordered_job_ids else []
            found={r["id"]:r["state"] for r in rows}
            missing=[jid for jid in ordered_job_ids if jid not in found]
            if missing: raise KeyError(",".join(missing))
            bad=[jid for jid in ordered_job_ids if found[jid] != JobState.QUEUED.value]
            if bad: raise ValueError(f"only queued jobs can be reordered: {','.join(bad)}")
            for pos,jid in enumerate(ordered_job_ids,start=1):
                con.execute("UPDATE jobs SET position=?,updated_at=? WHERE id=?",(pos,time.time(),jid)); self._event(con,jid,"reordered",{"position":pos})
        return self.list_jobs(states=[JobState.QUEUED.value])

    def request_control(self, job_id: str, action: str) -> dict:
        if action not in {"pause", "cancel", "checkpoint"}:
            raise ValueError("action must be pause, cancel or checkpoint")
        with self._conn(immediate=True) as con:
            row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None: raise KeyError(job_id)
            state = JobState(row["state"])
            pending=row["control_requested"]
            if pending and pending != action:
                raise ValueError(f"cannot request {action}; {pending} already pending")
            if state is JobState.RUNNING:
                if pending != action:
                    con.execute("UPDATE jobs SET control_requested=?,updated_at=? WHERE id=?", (action,time.time(),job_id))
                    self._event(con, job_id, "control_requested", {"action": action})
            elif state is JobState.QUEUED and action == "pause":
                con.execute("UPDATE jobs SET state=?,updated_at=? WHERE id=?", (JobState.PAUSED.value,time.time(),job_id))
                self._event(con, job_id, "state_changed", {"from":"queued","to":"paused","error":None})
            elif state in {JobState.QUEUED, JobState.PAUSED} and action == "cancel":
                now=time.time(); con.execute("UPDATE jobs SET state=?,updated_at=?,finished_at=? WHERE id=?", (JobState.CANCELLED.value,now,now,job_id))
                self._event(con, job_id, "state_changed", {"from":state.value,"to":"cancelled","error":None})
            else:
                raise ValueError(f"cannot request {action} for {state.value} job")
            return self._decode(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


    def acknowledge_control(self, job_id: str, action: str, *, payload: dict | None = None) -> dict:
        """Clear a durable control request only after the scheduler actually applied it."""
        with self._conn(immediate=True) as con:
            row=con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
            if row is None: raise KeyError(job_id)
            if row["control_requested"] != action:
                raise ValueError(f"control request changed before acknowledgement: expected {action}")
            con.execute("UPDATE jobs SET control_requested=NULL,updated_at=? WHERE id=?",(time.time(),job_id))
            self._event(con,job_id,"control_accepted",{"action":action,**(payload or {})})
            return self._decode(con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone())

    def transition(self, job_id: str, target: JobState, *, error: str | None = None) -> dict:
        allowed = {
            JobState.QUEUED:{JobState.RUNNING,JobState.PAUSED,JobState.CANCELLED},
            JobState.RUNNING:{JobState.PAUSED,JobState.COMPLETED,JobState.FAILED,JobState.CANCELLED},
            JobState.PAUSED:{JobState.QUEUED,JobState.RUNNING,JobState.CANCELLED},
            JobState.COMPLETED:set(), JobState.FAILED:{JobState.QUEUED}, JobState.CANCELLED:{JobState.QUEUED},
        }
        with self._conn(immediate=True) as con:
            row=con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
            if row is None: raise KeyError(job_id)
            current=JobState(row["state"])
            if target not in allowed[current]: raise ValueError(f"invalid transition {current.value}->{target.value}")
            now=time.time(); started=row["started_at"]; finished=row["finished_at"]; attempts=int(row["attempt_count"])
            if target is JobState.RUNNING: started=now; finished=None; attempts+=1
            if target in {JobState.COMPLETED,JobState.FAILED,JobState.CANCELLED}: finished=now
            if target is JobState.QUEUED: finished=None; error=None
            con.execute("UPDATE jobs SET state=?,attempt_count=?,updated_at=?,started_at=?,finished_at=?,error=?,control_requested=NULL WHERE id=?",(target.value,attempts,now,started,finished,error,job_id))
            self._event(con,job_id,"state_changed",{"from":current.value,"to":target.value,"error":error})
            return self._decode(con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone())

    def _recover_expired_attempt_locked(self, con: sqlite3.Connection, attempt: sqlite3.Row, now: float) -> str | None:
        """Recover one expired owner without dropping durable operator intent.

        A daemon crash must not turn a pending pause/cancel/checkpoint into a silent
        fresh run. Cancel and pause can be satisfied immediately once the dead owner
        is fenced. Checkpoint remains pending and is carried into the replacement
        attempt so the next live worker acknowledges it at a safe boundary.
        """
        jid=attempt["job_id"]; aid=attempt["id"]
        con.execute("UPDATE attempts SET state='expired',finished_at=?,error=? WHERE id=?",(now,"lease expired",aid))
        job=con.execute("SELECT * FROM jobs WHERE id=?",(jid,)).fetchone()
        if job is None or job["state"] != JobState.RUNNING.value or job["current_attempt_id"] != aid:
            return None
        control=job["control_requested"]
        if control == "cancel":
            con.execute("UPDATE jobs SET state=?,current_attempt_id=NULL,control_requested=NULL,updated_at=?,finished_at=?,error=? WHERE id=?",(JobState.CANCELLED.value,now,now,"previous attempt lease expired after cancel request",jid))
            self._event(con,jid,"lease_expired",{"attempt_id":aid,"recovery":"cancelled"})
            self._event(con,jid,"control_accepted",{"action":"cancel","reason":"owner lease expired"})
            return jid
        if control == "pause":
            con.execute("UPDATE jobs SET state=?,current_attempt_id=NULL,control_requested=NULL,updated_at=?,error=? WHERE id=?",(JobState.PAUSED.value,now,"previous attempt lease expired after pause request",jid))
            self._event(con,jid,"lease_expired",{"attempt_id":aid,"recovery":"paused"})
            self._event(con,jid,"control_accepted",{"action":"pause","reason":"owner lease expired"})
            return jid
        # No control -> normal retry. A pending checkpoint deliberately survives
        # and is applied by the replacement attempt at its next safe boundary.
        con.execute("UPDATE jobs SET state=?,current_attempt_id=NULL,updated_at=?,error=? WHERE id=?",(JobState.QUEUED.value,now,"previous attempt lease expired",jid))
        self._event(con,jid,"lease_expired",{"attempt_id":aid,"recovery":"requeued","pending_control":control})
        return jid

    def recover_expired(self, *, now: float | None = None) -> list[str]:
        now = time.time() if now is None else float(now)
        recovered=[]
        with self._conn(immediate=True) as con:
            rows=con.execute("SELECT * FROM attempts WHERE state='running' AND lease_expires_at<? ORDER BY started_at",(now,)).fetchall()
            for attempt in rows:
                jid=self._recover_expired_attempt_locked(con,attempt,now)
                if jid is not None:
                    recovered.append(jid)
        return recovered

    @staticmethod
    def _resource_units_from_request_json(request_json: str) -> int:
        try:
            request = json.loads(request_json)
            units = int((request.get("config") or {}).get("workers", 1))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("job config.workers must be an integer >= 1") from exc
        if units < 1:
            raise ValueError("job config.workers must be >= 1")
        return units

    def claim_next(self, *, owner: str, runs_root: str | Path, lease_seconds: float = 30.0,
                   max_active_jobs: int = 1, max_resource_units: int = 1,
                   now: float | None = None) -> tuple[dict, dict] | None:
        now=time.time() if now is None else float(now)
        runs_root=Path(runs_root)
        max_active_jobs=max(1,int(max_active_jobs)); max_resource_units=max(1,int(max_resource_units))
        with self._conn(immediate=True) as con:
            # Inline expired-lease recovery makes admission atomic with ownership.
            expired=con.execute("SELECT * FROM attempts WHERE state='running' AND lease_expires_at<?",(now,)).fetchall()
            for a in expired:
                self._recover_expired_attempt_locked(con,a,now)

            running=con.execute("SELECT request_json FROM jobs WHERE state='running'").fetchall()
            if len(running) >= max_active_jobs:
                return None
            used_units=sum(self._resource_units_from_request_json(r["request_json"]) for r in running)
            remaining=max_resource_units-used_units
            if remaining < 1:
                return None

            # Priority remains authoritative, but a temporarily-too-large job may
            # be skipped so smaller work can use otherwise idle admitted capacity.
            job=None; job_units=None
            for candidate in con.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY priority DESC,position ASC,created_at ASC").fetchall():
                units=self._resource_units_from_request_json(candidate["request_json"])
                if units <= remaining:
                    job=candidate; job_units=units; break
            if job is None: return None
            ordinal=int(job["attempt_count"])+1; aid=uuid.uuid4().hex
            run_root=runs_root/job["id"]/aid
            run_root.mkdir(parents=True,exist_ok=False)
            con.execute("INSERT INTO attempts(id,job_id,ordinal,state,owner,lease_expires_at,heartbeat_at,run_root,created_at,started_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(aid,job["id"],ordinal,"running",owner,now+lease_seconds,now,str(run_root),now,now))
            # Preserve a recovered pending checkpoint request. Other controls are
            # resolved during lease recovery and therefore cannot reach this claim.
            con.execute("UPDATE jobs SET state='running',attempt_count=?,current_attempt_id=?,started_at=?,finished_at=NULL,error=NULL,updated_at=? WHERE id=?",(ordinal,aid,now,now,job["id"]))
            self._event(con,job["id"],"attempt_started",{"attempt_id":aid,"owner":owner,"run_root":str(run_root),"lease_seconds":lease_seconds,"resource_units":job_units})
            j2=self._decode(con.execute("SELECT * FROM jobs WHERE id=?",(job["id"],)).fetchone())
            a2=self._decode_attempt(con.execute("SELECT * FROM attempts WHERE id=?",(aid,)).fetchone())
            return j2,a2

    @contextmanager
    def publication_lock(self):
        """Serialize filesystem publication commits across daemon processes.

        The DB write transaction is intentionally held only around the tiny
        manifest/current-pointer commit; optimizer execution and validation never
        run under this lock.
        """
        with self._conn(immediate=True):
            yield

    def heartbeat(self, attempt_id: str, *, owner: str, lease_seconds: float = 30.0, now: float | None = None) -> dict:
        now=time.time() if now is None else float(now)
        with self._conn(immediate=True) as con:
            a=con.execute("SELECT * FROM attempts WHERE id=?",(attempt_id,)).fetchone()
            if a is None: raise KeyError(attempt_id)
            if a["state"] != "running": raise ValueError("attempt is not running")
            if a["owner"] != owner: raise ValueError("attempt lease owner mismatch")
            con.execute("UPDATE attempts SET heartbeat_at=?,lease_expires_at=? WHERE id=?",(now,now+lease_seconds,attempt_id))
            return self._decode_attempt(con.execute("SELECT * FROM attempts WHERE id=?",(attempt_id,)).fetchone())

    def finish_attempt(self, attempt_id: str, *, owner: str, outcome: str, error: str | None = None) -> dict:
        mapping={"completed":JobState.COMPLETED,"failed":JobState.FAILED,"paused":JobState.PAUSED,"cancelled":JobState.CANCELLED}
        if outcome not in mapping: raise ValueError("invalid attempt outcome")
        with self._conn(immediate=True) as con:
            a=con.execute("SELECT * FROM attempts WHERE id=?",(attempt_id,)).fetchone()
            if a is None: raise KeyError(attempt_id)
            if a["owner"] != owner: raise ValueError("attempt lease owner mismatch")
            if a["state"] != "running": raise ValueError("attempt is not running")
            j=con.execute("SELECT * FROM jobs WHERE id=?",(a["job_id"],)).fetchone()
            if j is None or j["current_attempt_id"] != attempt_id: raise ValueError("attempt no longer owns job")
            now=time.time(); target=mapping[outcome]
            con.execute("UPDATE attempts SET state=?,finished_at=?,error=? WHERE id=?",(outcome,now,error,attempt_id))
            con.execute("UPDATE jobs SET state=?,current_attempt_id=NULL,control_requested=NULL,updated_at=?,finished_at=?,error=? WHERE id=?",(target.value,now,now if target in {JobState.COMPLETED,JobState.FAILED,JobState.CANCELLED} else None,error,a["job_id"]))
            self._event(con,a["job_id"],"attempt_finished",{"attempt_id":attempt_id,"outcome":outcome,"error":error})
            return self._decode(con.execute("SELECT * FROM jobs WHERE id=?",(a["job_id"],)).fetchone())


    def record_checkpoint(self, manifest: dict) -> dict:
        now=time.time(); cid=uuid.uuid4().hex
        with self._conn(immediate=True) as con:
            existing=con.execute("SELECT * FROM checkpoint_artifacts WHERE attempt_id=? AND path=?",(manifest["attempt_id"],manifest["path"])).fetchone()
            if existing is None:
                con.execute("INSERT INTO checkpoint_artifacts(id,job_id,attempt_id,path,kind,sha256,size_bytes,request_json,created_at,discovered_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(cid,manifest["job_id"],manifest["attempt_id"],manifest["path"],manifest["kind"],manifest["sha256"],int(manifest["size_bytes"]),json.dumps(manifest["request"],sort_keys=True),float(manifest["created_at"]),now))
                self._event(con,manifest["job_id"],"checkpoint_recorded",{"attempt_id":manifest["attempt_id"],"path":manifest["path"],"sha256":manifest["sha256"]})
                existing=con.execute("SELECT * FROM checkpoint_artifacts WHERE id=?",(cid,)).fetchone()
            out=dict(existing); out["request"]=json.loads(out.pop("request_json")); return out

    def list_checkpoints(self, job_id: str | None = None) -> list[dict]:
        with self._conn() as con:
            if job_id is None:
                rows=con.execute("SELECT * FROM checkpoint_artifacts ORDER BY created_at DESC, discovered_at DESC").fetchall()
            else:
                rows=con.execute("SELECT * FROM checkpoint_artifacts WHERE job_id=? ORDER BY created_at DESC, discovered_at DESC",(job_id,)).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d["request"]=json.loads(d.pop("request_json")); out.append(d)
        return out


    def record_publication(self, publication: dict) -> dict:
        with self._conn(immediate=True) as con:
            con.execute(
                "INSERT OR REPLACE INTO publications(id,job_id,attempt_id,state_root,parent_id,request_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (publication["id"], publication["job_id"], publication["attempt_id"], publication["state_root"], publication.get("parent_id"), json.dumps(publication.get("request") or {}, sort_keys=True), float(publication["created_at"])),
            )
            row=con.execute("SELECT * FROM publications WHERE id=?",(publication["id"],)).fetchone()
        out=dict(row); out["request"]=json.loads(out.pop("request_json")); return out

    def list_publications(self, *, job_id: str | None = None, class_name: str | None = None, limit: int | None = None) -> list[dict]:
        clauses=[]; args=[]
        if job_id is not None:
            clauses.append("job_id=?"); args.append(job_id)
        sql="SELECT * FROM publications"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"; args.append(max(1,min(500,int(limit))))
        with self._conn() as con:
            rows=con.execute(sql, tuple(args)).fetchall()
        out=[]
        for row in rows:
            d=dict(row); d["request"]=json.loads(d.pop("request_json"))
            if class_name is None or d["request"].get("class_name")==class_name:
                out.append(d)
        return out

    def job_lineage(self, job_id: str) -> dict:
        job=self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        attempts=self.list_attempts(job_id)
        checkpoints=self.list_checkpoints(job_id)
        publications=self.list_publications(job_id=job_id)
        cps_by_attempt={}
        for cp in checkpoints:
            cps_by_attempt.setdefault(cp["attempt_id"],[]).append(cp)
        pubs_by_attempt={}
        for pub in publications:
            pubs_by_attempt.setdefault(pub["attempt_id"],[]).append(pub)
        rows=[]
        for attempt in attempts:
            row=dict(attempt)
            row["checkpoints"]=cps_by_attempt.get(attempt["id"],[])
            row["publications"]=pubs_by_attempt.get(attempt["id"],[])
            rows.append(row)
        return {
            "job":job,
            "attempts":rows,
            "publication_count":len(publications),
            "latest_publication":publications[0] if publications else None,
        }

    def status_snapshot(self, *, job_limit: int = 100, publication_limit: int = 20) -> dict:
        """Bounded control-plane read model for thin clients.

        One SQLite snapshot supplies queue rows plus each job's latest durable
        event/checkpoint/attempt and recent publications.  Browser polling should
        consume this instead of issuing N+1 detail requests.
        """
        job_limit=max(1,min(500,int(job_limit))); publication_limit=max(1,min(100,int(publication_limit)))
        with self._conn() as con:
            meta={r["key"]:r["value"] for r in con.execute("SELECT key,value FROM service_meta").fetchall()}
            jobs=con.execute(
                "SELECT * FROM jobs ORDER BY CASE state WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END, priority DESC, position ASC, created_at ASC LIMIT ?",
                (job_limit,),
            ).fetchall()
            events=con.execute(
                "SELECT e.seq,e.job_id,e.kind,e.payload_json,e.created_at FROM job_events e "
                "JOIN (SELECT job_id,MAX(seq) AS seq FROM job_events GROUP BY job_id) x "
                "ON e.job_id=x.job_id AND e.seq=x.seq"
            ).fetchall()
            progress_events=con.execute(
                "SELECT e.seq,e.job_id,e.kind,e.payload_json,e.created_at FROM job_events e "
                "JOIN (SELECT job_id,MAX(seq) AS seq FROM job_events WHERE kind='runtime_progress' GROUP BY job_id) x "
                "ON e.job_id=x.job_id AND e.seq=x.seq"
            ).fetchall()
            checkpoints=con.execute(
                "SELECT * FROM checkpoint_artifacts ORDER BY created_at DESC,discovered_at DESC"
            ).fetchall()
            attempts=con.execute(
                "SELECT * FROM attempts ORDER BY job_id,ordinal DESC"
            ).fetchall()
            pubs=con.execute(
                "SELECT * FROM publications ORDER BY created_at DESC LIMIT ?",
                (publication_limit,),
            ).fetchall()

        latest_events={}
        for r in events:
            d=dict(r); d["payload"]=json.loads(d.pop("payload_json")); latest_events[d["job_id"]]=d
        latest_progress={}
        for r in progress_events:
            d=dict(r); d["payload"]=json.loads(d.pop("payload_json")); latest_progress[d["job_id"]]=d
        latest_checkpoints={}
        for r in checkpoints:
            jid=r["job_id"]
            if jid in latest_checkpoints: continue
            d=dict(r); d["request"]=json.loads(d.pop("request_json")); latest_checkpoints[jid]=d
        latest_attempts={}
        for r in attempts:
            latest_attempts.setdefault(r["job_id"],dict(r))

        decoded_jobs=[]
        now=time.time()
        for row in jobs:
            d=self._decode(row)
            jid=d["id"]
            d["latest_event"]=latest_events.get(jid)
            d["latest_progress_event"]=latest_progress.get(jid)
            d["latest_checkpoint"]=latest_checkpoints.get(jid)
            d["latest_attempt"]=latest_attempts.get(jid)
            progress_payload=(latest_progress.get(jid) or {}).get("payload") or {}
            attempt=latest_attempts.get(jid) or {}
            heartbeat_at=attempt.get("heartbeat_at")
            lease_expires_at=attempt.get("lease_expires_at")
            heartbeat_age=None if heartbeat_at is None else max(0.0,now-float(heartbeat_at))
            lease_window=None
            if heartbeat_at is not None and lease_expires_at is not None:
                lease_window=max(0.0,float(lease_expires_at)-float(heartbeat_at))
            stalled=bool(
                d.get("state")==JobState.RUNNING.value and heartbeat_age is not None and
                heartbeat_age > max(5.0,0.75*(lease_window or 0.0))
            )
            if d.get("state")==JobState.COMPLETED.value:
                default_progress={"mode":"determinate","current":1,"total":1,"fraction":1.0,"unit":"job"}
            else:
                default_progress={"mode":"indeterminate"}
            d["phase"]=progress_payload.get("phase") or d.get("state")
            d["stage"]=progress_payload.get("stage")
            d["progress"]=progress_payload.get("progress") or default_progress
            d["best_so_far"]=progress_payload.get("best_so_far")
            d["runtime_message"]=progress_payload.get("message")
            d["runtime_level"]=progress_payload.get("level")
            d["heartbeat"]={
                "age_seconds": heartbeat_age,
                "lease_remaining_seconds": None if lease_expires_at is None else float(lease_expires_at)-now,
                "stalled": stalled,
            }
            decoded_jobs.append(d)
        decoded_pubs=[]
        for row in pubs:
            d=dict(row); d["request"]=json.loads(d.pop("request_json")); decoded_pubs.append(d)
        active=[j for j in decoded_jobs if j.get("state") in _ACTIVE_STATES]
        return {
            "schema_version": int(meta.get("schema_version", _SCHEMA_VERSION)),
            "service_version": SOFTWARE_VERSION,
            "jobs": decoded_jobs,
            "active_count": len(active),
            "publications": decoded_pubs,
        }

    def record_event(self, job_id: str, kind: str, payload: dict | None = None) -> None:
        with self._conn(immediate=True) as con:
            if con.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone() is None:
                raise KeyError(job_id)
            self._event(con, job_id, kind, payload)

    def requested_control(self, job_id: str) -> str | None:
        with self._conn() as con:
            r=con.execute("SELECT control_requested FROM jobs WHERE id=?",(job_id,)).fetchone()
            if r is None: raise KeyError(job_id)
            return r["control_requested"]

    def events_since(self, *, after_seq: int = 0, job_id: str | None = None, limit: int = 200) -> list[dict]:
        limit=max(1,min(1000,int(limit)))
        with self._conn() as con:
            if job_id is None:
                rows=con.execute(
                    "SELECT seq,job_id,kind,payload_json,created_at FROM job_events WHERE seq>? ORDER BY seq LIMIT ?",
                    (int(after_seq),limit),
                ).fetchall()
            else:
                rows=con.execute(
                    "SELECT seq,job_id,kind,payload_json,created_at FROM job_events WHERE job_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (job_id,int(after_seq),limit),
                ).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d["payload"]=json.loads(d.pop("payload_json")); out.append(d)
        return out

    def events(self, job_id: str) -> list[dict]:
        out=[]; cursor=0
        while True:
            rows=self.events_since(after_seq=cursor,job_id=job_id,limit=1000)
            out.extend(rows)
            if len(rows)<1000:
                return out
            cursor=int(rows[-1]["seq"])
