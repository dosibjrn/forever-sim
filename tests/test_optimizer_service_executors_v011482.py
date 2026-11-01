from pathlib import Path

import pytest

from src.service.executors import MasterOptimizerExecutor, V2RunnerExecutor, executor_for
from src.service.models import JobRequest
from src.service.scheduler import Scheduler
from src.service.store import QueueStore


def job_for(tmp_path: Path, *, mode="smooth", cls="mage", start=11, end=60, config=None):
    store = QueueStore(tmp_path / "q.sqlite3")
    job, _ = store.enqueue(JobRequest(
        ruleset="forever", class_name=cls, start_level=start, end_level=end,
        endpoint_mode=mode, config=config or {},
    ))
    return job


def test_executor_dispatch_and_v2_command(tmp_path: Path):
    job = job_for(tmp_path, mode="smooth", start=11, end=20)
    ex = executor_for(job)
    assert isinstance(ex, V2RunnerExecutor)
    plan = ex.plan(job)
    assert plan.kind == "v2_runner"
    assert plan.cooperative_stop is False
    assert plan.work_unit == "whole_runner"
    assert "src.v2.runner" in plan.command
    assert plan.command[plan.command.index("--view")+1] == "smooth"
    assert plan.command[plan.command.index("--workers")+1] == "1"


def test_mc_plan_is_one_checkpoint_safe_master_experiment(tmp_path: Path):
    job = job_for(tmp_path, mode="mc", config={"school":"frost", "water_mode":"buy_water", "workers":3})
    plan = MasterOptimizerExecutor().plan(job)
    assert plan.kind == "master_optimizer"
    assert plan.cooperative_stop is True
    assert plan.stop_grace_seconds >= 30
    assert plan.work_unit == "one_master_optimizer_experiment"
    assert "src.master_optimizer" in plan.command
    assert "--once" in plan.command
    assert plan.command[plan.command.index("--school")+1] == "frost"
    assert plan.command[plan.command.index("--workers")+1] == "3"


def test_mc_rejects_partial_arc_non_mage_and_unknown_config(tmp_path: Path):
    with pytest.raises(ValueError, match="full L11"):
        MasterOptimizerExecutor().plan(job_for(tmp_path / "a", mode="mc", start=20, end=40))
    with pytest.raises(ValueError, match="only for mage"):
        MasterOptimizerExecutor().plan(job_for(tmp_path / "b", mode="mc", cls="paladin"))
    with pytest.raises(ValueError, match="unsupported MC service config"):
        MasterOptimizerExecutor().plan(job_for(tmp_path / "c", mode="mc", config={"magic":1}))


def test_scheduler_command_helper_uses_executor_contract(tmp_path: Path):
    job = job_for(tmp_path, mode="mc")
    cmd = Scheduler.command_for(job)
    assert "src.master_optimizer" in cmd
    assert "--once" in cmd
