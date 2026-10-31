from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from .store import QueueStore
from .executors import executor_for
from .checkpoints import build_manifest, discover_checkpoint_files, write_sidecar, select_resume_checkpoint, stage_resume_checkpoint, classify_compatibility, Compatibility, file_sha256
from .publication import publish_attempt, PublicationError


@dataclass(frozen=True)
class ClaimedJob:
    job: dict
    attempt: dict


class Scheduler:
    """Bounded-concurrency durable scheduler.

    Queue admission is atomic in SQLite.  Every optimizer writes only below its
    immutable attempt root; the tiny canonical publication commit is serialized
    separately so simultaneous completions cannot lose an overlay generation.
    """

    def __init__(self, store: QueueStore, *, runs_root: str | Path, owner: str | None = None,
                 lease_seconds: float = 30.0, max_active_jobs: int = 1, max_resource_units: int = 1):
        self.store=store
        self.runs_root=Path(runs_root)
        self.owner=owner or f"{socket.gethostname()}:{os.getpid()}"
        self.lease_seconds=float(lease_seconds)
        self.max_active_jobs=max(1,int(max_active_jobs))
        self.max_resource_units=max(1,int(max_resource_units))

    def claim(self) -> ClaimedJob | None:
        claimed=self.store.claim_next(
            owner=self.owner, runs_root=self.runs_root, lease_seconds=self.lease_seconds,
            max_active_jobs=self.max_active_jobs, max_resource_units=self.max_resource_units,
        )
        return None if claimed is None else ClaimedJob(*claimed)

    def _record_checkpoints(self, job: dict, attempt: dict) -> list[dict]:
        recorded=[]
        for path in discover_checkpoint_files(attempt["run_root"]):
            manifest=build_manifest(job=job,attempt=attempt,path=path)
            write_sidecar(manifest)
            recorded.append(self.store.record_checkpoint(manifest.to_dict()))
        return recorded

    def _prepare_saved_state(self, job: dict, attempt: dict) -> tuple[dict | None, dict | None]:
        """Resolve an explicit saved-state choice or the normal strict-resume default.

        Resume copies verified numeric continuation state into the fresh attempt.
        Seed-only never copies numeric state: for MC jobs it exposes only the
        source attempt root to master_optimizer's read-only --import-state-dir
        prior importer.
        """
        if job["request"].get("endpoint_mode") != "mc":
            return None, None
        selected_id=job.get("selected_checkpoint_id")
        selected_mode=job.get("selected_checkpoint_mode")
        if selected_id:
            cp=self.store.get_checkpoint(selected_id)
            if cp is None:
                raise ValueError(f"selected checkpoint {selected_id} no longer exists")
            actual=classify_compatibility(cp["request"], job["request"])
            if selected_mode != actual.value:
                raise ValueError(f"selected saved-state mode {selected_mode} no longer matches compatibility {actual.value}")
        else:
            cp = select_resume_checkpoint(self.store.list_checkpoints(), job["request"], prefer_job_id=job["id"])
            selected_mode = Compatibility.RESUME.value if cp is not None else None
        if cp is None:
            return None, None
        source_attempt = self.store.get_attempt(cp["attempt_id"])
        if source_attempt is None:
            raise ValueError("saved-state source attempt no longer exists")
        if selected_mode == Compatibility.RESUME.value:
            staged = stage_resume_checkpoint(checkpoint=cp, source_attempt=source_attempt, target_attempt=attempt)
            self.store.record_event(job["id"], "checkpoint_staged_for_resume", staged)
            return staged, None
        if selected_mode == Compatibility.SEED_ONLY.value:
            src=Path(cp["path"])
            if not src.exists() or file_sha256(src) != cp["sha256"]:
                raise ValueError("seed-only checkpoint missing or sha256 mismatch")
            seed={
                "checkpoint_id":cp["id"], "source_job_id":cp["job_id"],
                "source_attempt_id":cp["attempt_id"], "source_run_root":source_attempt["run_root"],
                "sha256":cp["sha256"],
            }
            self.store.record_event(job["id"], "checkpoint_selected_as_seed", seed)
            return None, seed
        raise ValueError(f"unsupported saved-state mode {selected_mode}")

    def _stage_resume(self, job: dict, attempt: dict) -> dict | None:
        # Backwards-compatible helper retained for tests/callers.
        return self._prepare_saved_state(job, attempt)[0]


    @staticmethod
    def _runtime_progress_payload(job: dict, attempt: dict) -> dict | None:
        """Normalize optimizer-owned runtime status into a durable service event.

        The child remains the authority for search phase/best metadata; the service
        copies only a bounded summary. Thin clients never parse subprocess logs or
        reach into attempt roots directly.
        """
        roots=sorted(Path(attempt["run_root"]).glob("state/**/runtime/status.json"))
        if not roots:
            return None
        path=max(roots,key=lambda x:x.stat().st_mtime_ns)
        try:
            raw=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError,TypeError):
            return None
        progress={"mode":"indeterminate"}
        raw_progress=raw.get("progress")
        if isinstance(raw_progress,dict) and raw_progress.get("mode") in {"determinate","indeterminate"}:
            progress=dict(raw_progress)
        else:
            total=raw.get("validation_total"); done=raw.get("validation_done")
            try:
                total_i=int(total) if total is not None else 0
                done_i=int(done) if done is not None else 0
                if total_i>0:
                    done_i=max(0,min(total_i,done_i))
                    progress={"mode":"determinate","current":done_i,"total":total_i,"fraction":done_i/total_i,"unit":"rows"}
            except (TypeError,ValueError):
                pass
        best_raw=raw.get("best") if isinstance(raw.get("best"),dict) else {}
        best=None
        if best_raw:
            best={k:best_raw.get(k) for k in ("best_validated_hours","candidate_id","source","water_mode","primary_school","validation_mobs","updated_at") if best_raw.get(k) is not None}
            if not best:
                best=None
        return {
            "attempt_id":attempt["id"],
            "phase":raw.get("phase") or raw.get("state") or "running",
            "stage":raw.get("outer_stage") or raw.get("stage") or raw.get("experiment") or raw.get("state"),
            "level":raw.get("level") if raw.get("level") is not None else raw.get("validation_level"),
            "progress":progress,
            "best_so_far":best,
            "message":raw.get("message"),
        }

    @staticmethod
    def command_for(job: dict) -> list[str]:
        # Backwards-compatible helper; execution policy lives in executors.py.
        return executor_for(job).plan(job).command

    def run_claimed(self, claimed: ClaimedJob, *, project_root: str | Path, poll_seconds: float = 0.25) -> dict:
        job,attempt=claimed.job,claimed.attempt
        run_root=Path(attempt["run_root"]); run_root.mkdir(parents=True,exist_ok=True)
        try:
            resume_info,seed_info=self._prepare_saved_state(job, attempt)
            plan=executor_for(job).plan(job)
            cmd=list(plan.command)
            if seed_info is not None:
                cmd.extend(["--import-state-dir", seed_info["source_run_root"]])
        except Exception as exc:
            self.store.record_event(job["id"],"saved_state_rejected",{"attempt_id":attempt["id"],"error":str(exc)})
            return self.store.finish_attempt(attempt["id"],owner=self.owner,outcome="failed",error=f"saved state rejected: {exc}")
        manifest={"job_id":job["id"],"attempt_id":attempt["id"],"owner":self.owner,"request":job["request"],"executor":plan.kind,"work_unit":plan.work_unit,"execution_authority":plan.execution_authority,"native_generic_job_supported":plan.native_generic_job_supported,"cooperative_stop":plan.cooperative_stop,"command":cmd,"resume":resume_info,"seed_only":seed_info,"created_at":time.time()}
        (run_root/"attempt_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True),encoding="utf-8")
        # G50e: a generic-only deployment must not silently execute historical
        # optimizer CLIs via the queue. There is no native generic queued job
        # executor yet; preserve ordinary legacy jobs unless explicitly opted in.
        if (os.environ.get("WOW_DISABLE_LEGACY_JOB_EXECUTION") == "1"
                and plan.execution_authority == "historical_legacy_cli"):
            error = "legacy_job_execution_disabled: native generic queued executor not implemented"
            self.store.record_event(job["id"], "execution_rejected", {
                "attempt_id": attempt["id"], "reason": "legacy_job_execution_disabled",
                "execution_authority": plan.execution_authority,
                "native_generic_job_supported": plan.native_generic_job_supported,
            })
            return self.store.finish_attempt(attempt["id"], owner=self.owner,
                                             outcome="failed", error=error)
        env=os.environ.copy()
        env["WOW_SIM_STATE_BASE"]=str(run_root/"state")
        stdout=(run_root/"stdout.log").open("wb"); stderr=(run_root/"stderr.log").open("wb")
        try:
            proc=subprocess.Popen(cmd,cwd=project_root,env=env,stdout=stdout,stderr=stderr)
            next_heartbeat=0.0; next_progress=0.0; last_progress=None
            self.store.record_event(job["id"], "runtime_progress", {
                "attempt_id":attempt["id"], "phase":"starting", "stage":plan.kind,
                "progress":{"mode":"indeterminate"}, "best_so_far":None,
                "message":"optimizer process started",
            })
            while True:
                rc=proc.poll(); now=time.monotonic()
                if now >= next_heartbeat:
                    self.store.heartbeat(attempt["id"],owner=self.owner,lease_seconds=self.lease_seconds)
                    next_heartbeat=now+max(0.2,self.lease_seconds/3.0)
                if now >= next_progress:
                    payload=self._runtime_progress_payload(job,attempt)
                    if payload is not None and payload != last_progress:
                        self.store.record_event(job["id"],"runtime_progress",payload)
                        last_progress=payload
                    next_progress=now+1.0
                control=self.store.requested_control(job["id"])
                if control == "checkpoint":
                    recorded=self._record_checkpoints(job, attempt)
                    if recorded:
                        self.store.acknowledge_control(job["id"],"checkpoint",payload={"checkpoint_ids":[x["id"] for x in recorded]})
                        control=None
                if control in {"pause","cancel"}:
                    # MC/master_optimizer owns checkpoint-safe STOP handling.
                    # Bounded v2 jobs have no resume checkpoint yet and are simply
                    # terminated; either way the attempt root remains immutable.
                    proc.terminate()
                    try:
                        proc.wait(timeout=plan.stop_grace_seconds)
                    except subprocess.TimeoutExpired:
                        proc.kill(); proc.wait(timeout=5)
                    self._record_checkpoints(job, attempt)
                    return self.store.finish_attempt(attempt["id"],owner=self.owner,outcome="paused" if control=="pause" else "cancelled")
                if rc is not None:
                    self._record_checkpoints(job, attempt)
                    if rc == 0:
                        try:
                            # Multiple attempts may finish together.  The immutable
                            # state roots are independent; only the overlay parent +
                            # current-pointer swap needs global serialization.
                            with self.store.publication_lock():
                                publication = publish_attempt(project_root, job=job, attempt=attempt)
                            self.store.record_publication(publication)
                            self.store.record_event(job["id"], "publication_committed", {"publication_id": publication["id"], "attempt_id": attempt["id"]})
                        except PublicationError as exc:
                            self.store.record_event(job["id"], "publication_rejected", {"attempt_id": attempt["id"], "error": str(exc)})
                            return self.store.finish_attempt(attempt["id"],owner=self.owner,outcome="failed",error=f"publication rejected: {exc}")
                        return self.store.finish_attempt(attempt["id"],owner=self.owner,outcome="completed")
                    return self.store.finish_attempt(attempt["id"],owner=self.owner,outcome="failed",error=f"optimizer exited {rc}")
                time.sleep(poll_seconds)
        finally:
            stdout.close(); stderr.close()

    def run_once(self, *, project_root: str | Path) -> dict | None:
        claimed=self.claim()
        return None if claimed is None else self.run_claimed(claimed,project_root=project_root)
