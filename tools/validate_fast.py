#!/usr/bin/env python3
"""Fast development validation for the Forever optimizer.

This is the default validation loop. It intentionally excludes historical M47
adversarial/report scripts: those are evidence, not a required per-change ritual.
The contract is simple: exercise the current production path and core mechanics
inside a strict wall-clock budget.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGET_SECONDS = 15.0

TESTS = [
    "tests/test_forever_release_gate_v0114621.py",
    "tests/test_forever_shared_recovery.py",
    "tests/test_forever_same_level_and_mage_chain_v0114616.py",
    "tests/test_per_level_best_respec_v0114617.py",
    "tests/test_m47_mage_hp_wand_finisher_v011479.py",
    "tests/test_m47_mage_l40_l60_wand_v0114710.py",
    "tests/test_mage_periodic_crit_v0114713.py",
    "tests/test_druid_natural_reaction_v0114714.py",
    "tests/test_druid_thick_hide_v0114715.py",
    "tests/test_druid_defense_avoidance_v0114812.py",
    "tests/test_druid_cat_swipe_v0114716.py",
    "tests/test_druid_lacerate_v0114718.py",
    "tests/test_druid_blood_frenzy_v0114719.py",
    "tests/test_druid_king_of_the_jungle_v0114720.py",
    "tests/test_druid_berserk_v0114721.py",
    "tests/test_v2_mc_bridge_errors.py::test_publish_paths_ignores_named_auxiliary_routes",
    "tests/test_m47_paladin_mechanic_reconciliation_v011477.py",
    "tests/test_listener_canonical_path_wiring_v0114724.py",
    "tests/test_optimizer_service_queue_v011480.py",
    "tests/test_optimizer_service_scheduler_v011481.py",
    "tests/test_optimizer_service_concurrency_v0114811.py",
    "tests/test_optimizer_service_executors_v011482.py",
    "tests/test_optimizer_service_checkpoints_v011483.py",
    "tests/test_optimizer_service_resume_v011484.py",
    "tests/test_optimizer_service_publication_v011485.py",
    "tests/test_optimizer_service_http_v011486.py",
    "tests/test_optimizer_service_client_v011487.py",
    "tests/test_listener_service_controls_v011488.py",
    "tests/test_optimizer_service_progress_v0114814.py",
    "tests/test_listener_progress_contract_v0114814.py",
    "tests/test_optimizer_service_operator_controls_v0114815.py",
    "tests/test_optimizer_service_saved_state_ux_v0114816.py",
    "tests/test_optimizer_service_workbench_v0114817.py",
    "tests/test_v3_checkpoint_failure_semantics_v0114821.py",
    "tests/test_local_stack_launcher_v0114822.py",
    "tests/test_item_catalogue_i1_v0114826.py",
    "tests/test_item_catalogue_i2_v0114827.py",
    "tests/test_item_catalogue_i3_v0114828.py",
    "tests/test_item_catalogue_i4_v0114829.py",
    "tests/test_wowhead_capture_i5prep_v0114830.py",
    "tests/test_master_optimizer_external_state_v011484.py",
    "tests/test_architecture_boundaries.py",
    "tests/test_listener_semantics.py",
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def main() -> int:
    started = time.perf_counter()

    compile_result = _run([sys.executable, "-m", "compileall", "-q", "src", "tests", "tools"])
    if compile_result.stdout:
        print(compile_result.stdout, end="")
    if compile_result.returncode != 0:
        print("[validate-fast] FAIL: compileall/import preflight failed", file=sys.stderr)
        return compile_result.returncode

    import_result = _run([
        sys.executable,
        "-c",
        "import src.listener, src.master_optimizer, src.service.store, "
        "src.service.scheduler, src.service.http_api, src.service.client, src.service.local_stack",
    ])
    if import_result.stdout:
        print(import_result.stdout, end="")
    if import_result.returncode != 0:
        print("[validate-fast] FAIL: core import sanity failed", file=sys.stderr)
        return import_result.returncode

    cmd = [sys.executable, "-m", "pytest", "-q", "-r", "s", *TESTS]
    result = _run(cmd)
    if result.stdout:
        print(result.stdout, end="")
    elapsed = time.perf_counter() - started

    print(f"[validate-fast] elapsed={elapsed:.2f}s budget={BUDGET_SECONDS:.0f}s")
    if result.returncode != 0:
        return result.returncode
    if " skipped" in result.stdout or " skipped," in result.stdout:
        print("[validate-fast] FAIL: mandatory test was skipped", file=sys.stderr)
        return 3
    if elapsed > BUDGET_SECONDS:
        print(
            f"[validate-fast] FAIL: validation exceeded {BUDGET_SECONDS:.0f}s budget",
            file=sys.stderr,
        )
        return 2
    print("[validate-fast] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
