from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Protocol


@dataclass(frozen=True)
class ExecutionPlan:
    kind: str
    command: list[str]
    cooperative_stop: bool = False
    stop_grace_seconds: float = 5.0
    work_unit: str = "process"
    execution_authority: str = "historical_legacy_cli"
    native_generic_job_supported: bool = False


class Executor(Protocol):
    def plan(self, job: dict) -> ExecutionPlan: ...


def requested_resource_units(job: dict) -> int:
    """CPU/process budget charged by the service admission controller.

    Service execution deliberately defaults to one worker even when the raw
    optimizer CLIs would auto-expand to host CPU count.  A caller may request a
    larger bounded budget with ``config.workers``; admission and the launched
    command use the same number, so nested optimizer pools cannot silently
    oversubscribe the daemon.
    """
    cfg = job.get("request", {}).get("config") or {}
    try:
        units = int(cfg.get("workers", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("config.workers must be an integer >= 1") from exc
    if units < 1:
        raise ValueError("config.workers must be >= 1")
    return units


class NativeGenericDecisionExecutor:
    """G50h: exact, provider-declared source Decision, not a route/optimizer job."""

    def plan(self, job: dict) -> ExecutionPlan:
        r = job["request"]
        from src.game.data.forever.queue_capabilities import (
            PINNED_FOREVER_AS_OF, require_native_generic_queue,
        )
        cls = r.get("class_name", "")
        level = int(r.get("start_level", -1))
        require_native_generic_queue(cls, level)
        if (r.get("ruleset") != "forever"
                or int(r.get("end_level", -1)) != level
                or r.get("objective") != "endpoint"
                or r.get("forever_build_as_of") != PINNED_FOREVER_AS_OF
                or r.get("source_snapshot") != "current"
                or r.get("engine_semantic_hash") != "current"
                or r.get("policy_space_version") != "current"
                or r.get("validation_modes")
                or set(r.get("config") or {}) - {"producer_version"}
                or requested_resource_units(job) != 1):
            raise ValueError("native generic_decision requires explicit declared forever class/level endpoint, "
                             "pinned as_of, current sources, no custom config/validation")
        return ExecutionPlan(
            kind="native_generic_decision_level",
            command=[sys.executable, "-m", "src.service.generic_decision_worker",
                     "--class", cls, "--level", str(level), "--as-of", PINNED_FOREVER_AS_OF],
            work_unit="one_native_generic_level_decision",
            execution_authority="native_generic_decision",
            native_generic_job_supported=True,
        )


class V2RunnerExecutor:
    """Bounded v2 runner execution.

    The runner has no durable mid-run checkpoint contract yet, so pause/cancel
    stop the process and a later resume starts a fresh immutable attempt.
    """

    def plan(self, job: dict) -> ExecutionPlan:
        r = job["request"]
        mode = r["endpoint_mode"]
        if mode not in {"smooth", "fast"}:
            raise ValueError(f"v2 runner does not support endpoint_mode {mode!r}")
        cmd = [
            sys.executable, "-m", "src.v2.runner",
            "--ruleset", r["ruleset"],
            "--class", r["class_name"],
            "--start-level", str(r["start_level"]),
            "--end-level", str(r["end_level"]),
            "--view", "smooth",
        ]
        if r.get("ruleset") == "forever":
            cmd.extend(["--forever-as-of", str(r["forever_build_as_of"])])
        cfg = r.get("config") or {}
        workers = requested_resource_units(job)
        cmd.extend(["--workers", str(workers)])
        if cfg.get("buy_water"):
            cmd.append("--buy-water")
        if cfg.get("no_stat_weights"):
            cmd.append("--no-stat-weights")
        if cfg.get("mage_blizzard_aoe"):
            if r.get("ruleset") != "forever" or r.get("class_name") != "mage":
                raise ValueError("config.mage_blizzard_aoe is valid only for forever/mage")
            cmd.append("--mage-blizzard-aoe")
        if cfg.get("gear_overrides"):
            import json
            if r.get("ruleset") != "forever":
                raise ValueError("config.gear_overrides is valid only for forever jobs")
            if not isinstance(cfg.get("gear_overrides"), dict):
                raise ValueError("config.gear_overrides must be an object mapping slot to item id")
            cmd.extend(["--gear-overrides-json", json.dumps(cfg["gear_overrides"], sort_keys=True, separators=(",", ":"))])
        # Search breadth is a user-intent budget compiled by the service. The
        # runner remains the execution backend; these names are not exposed as
        # user-facing modes.
        for key, flag in (("beam_width", "--beam-width"), ("family_keep", "--family-keep"), ("final_k", "--final-k"), ("stat_weight_top_k", "--stat-weight-top-k")):
            if key in cfg:
                cmd.extend([flag, str(int(cfg[key]))])
        return ExecutionPlan(
            kind="v2_runner",
            command=cmd,
            cooperative_stop=False,
            stop_grace_seconds=5.0,
            work_unit="whole_runner",
        )


class MasterOptimizerExecutor:
    """Persistent MC/master-optimizer execution as one checkpoint-safe experiment.

    ``master_optimizer --once`` owns its internal checkpoint semantics. SIGTERM
    is handled cooperatively by that process (STOP event + stop_check hooks), so
    service pause/cancel requests first ask it to stop cleanly before falling
    back to a hard kill.
    """

    _ALLOWED_CONFIG = {
        "water_mode", "school", "workers", "heartbeat_seconds",
        "validation_mobs", "validate_top", "path_race_start_mobs",
        "path_race_max_mobs", "path_race_top", "path_race_alpha",
        "preview_validate_top", "startup_replay_top", "top_k", "producer_version",
    }

    def plan(self, job: dict) -> ExecutionPlan:
        r = job["request"]
        if r["endpoint_mode"] != "mc":
            raise ValueError("master optimizer executor requires endpoint_mode='mc'")
        if r["class_name"] != "mage":
            raise ValueError("MC/master optimizer service execution is currently available only for mage")
        if int(r["start_level"]) != 11 or int(r["end_level"]) != 60:
            raise ValueError("MC/master optimizer currently owns the full L11→60 arc; enqueue mc jobs as L11→60")

        cfg = dict(r.get("config") or {})
        unknown = sorted(set(cfg) - self._ALLOWED_CONFIG)
        if unknown:
            raise ValueError("unsupported MC service config keys: " + ", ".join(unknown))

        cmd = [
            sys.executable, "-m", "src.master_optimizer",
            "--ruleset", r["ruleset"],
            "--class", r["class_name"],
            "--once",
        ]
        if r.get("ruleset") == "forever":
            cmd.extend(["--forever-as-of", str(r["forever_build_as_of"])])
        # Force the service admission budget into the child command even when
        # the caller omitted config.workers; raw CLI auto-sizing is intentionally
        # not inherited by the multi-job service.
        if "workers" not in cfg:
            cmd.extend(["--workers", str(requested_resource_units(job))])
        mapping = {
            "water_mode": "--water-mode",
            "school": "--school",
            "workers": "--workers",
            "heartbeat_seconds": "--heartbeat-seconds",
            "validation_mobs": "--validation-mobs",
            "validate_top": "--validate-top",
            "path_race_start_mobs": "--path-race-start-mobs",
            "path_race_max_mobs": "--path-race-max-mobs",
            "path_race_top": "--path-race-top",
            "path_race_alpha": "--path-race-alpha",
            "preview_validate_top": "--preview-validate-top",
            "startup_replay_top": "--startup-replay-top",
            "top_k": "--top-k",
        }
        for key, flag in mapping.items():
            if key in cfg:
                cmd.extend([flag, str(cfg[key])])

        return ExecutionPlan(
            kind="master_optimizer",
            command=cmd,
            cooperative_stop=True,
            stop_grace_seconds=30.0,
            work_unit="one_master_optimizer_experiment",
        )


def executor_for(job: dict) -> Executor:
    mode = job["request"]["endpoint_mode"]
    if mode == "generic_decision":
        return NativeGenericDecisionExecutor()
    if mode in {"smooth", "fast"}:
        return V2RunnerExecutor()
    if mode == "mc":
        return MasterOptimizerExecutor()
    raise ValueError(f"unsupported service endpoint_mode {mode!r}")
