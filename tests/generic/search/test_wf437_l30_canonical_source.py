"""L30 P4 cold source initialization: reach the real search without a staged DB.

The expensive 30s search and 100-mob acceptance remain Merge-only. This test
runs the real source build and cold-stage setup, stopping exactly at the
existing production search boundary.
"""
from pathlib import Path
import runpy
import sys

import pytest

from src.game.data.forever import registry
from src.game.data.forever.source_db_scope import DEFAULT_DB
from src.v2 import source_bounded_joint_frontier


class _ColdSearchReached(Exception):
    """Sentinel: the genuine cold-search entrypoint was reached."""


def test_druid_l30_unrestricted_uses_canonical_source_and_reaches_search(
    monkeypatch, tmp_path,
):
    original_build = registry.build_game_ir_slice
    observed = {}

    def capture_real_source_build(**kwargs):
        observed["ability_db_path"] = Path(kwargs["ability_db_path"]).resolve()
        ir = original_build(**kwargs)
        observed["source_ir"] = ir
        return ir

    def stop_before_paid_search(**kwargs):
        observed["search_kwargs"] = kwargs
        raise _ColdSearchReached

    monkeypatch.setattr(registry, "build_game_ir_slice", capture_real_source_build)
    monkeypatch.setattr(
        source_bounded_joint_frontier,
        "search_bounded_joint_frontier",
        stop_before_paid_search,
    )
    monkeypatch.setattr(sys, "argv", [
        "wf437_direct_budgeted_run",
        "--budget", "30",
        "--checkpoint-class", "druid",
        "--checkpoint-level", "30",
        "--checkpoint-spec", "unrestricted",
        "--output", str(tmp_path / "not-written.json"),
    ])

    with pytest.raises(_ColdSearchReached):
        runpy.run_module("tools.wf437_direct_budgeted_run", run_name="__main__")

    assert Path(DEFAULT_DB).is_file()
    assert observed["ability_db_path"] == Path(DEFAULT_DB).resolve()
    assert observed["source_ir"] is not None
    params = observed["search_kwargs"]
    assert (params["class_key"], params["level"]) == ("druid", 30)
    assert params["source_ir"] is observed["source_ir"]
    assert params["seed_stage"] is not None
    assert params["max_cpu_s"] == 30.0
    assert params["screen_evaluator_backend"] == "direct"
    assert params["finalist_mobs"] == 100
    assert not (tmp_path / "not-written.json").exists()
