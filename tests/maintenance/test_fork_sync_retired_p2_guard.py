"""Fork publishing must not be gated by retired P1/P2 proof.

These tests cover Forever's own workflow contract, not MythicSim gameplay.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_fork_bootstrap_retains_active_native_transport_checks_only():
    bootstrap = (ROOT / "scripts/bootstrap_mythicsim_rust_fork.sh").read_text(
        encoding="utf-8"
    )
    assert "native_improved_roots_rank_intake" not in bootstrap
    for required in (
        "cargo test --locked --lib persistent_next_target",
        "cargo test --locked --lib world_lethal_terminal",
        "cargo test --locked --lib druid_talent_layout_api_tests",
        "check_engine_source",
    ):
        assert required in bootstrap, required


def test_fork_ci_has_no_retired_p2_rank_publication_gate():
    workflow = (ROOT / ".github/workflows/rust-upstream-fork.yml").read_text(
        encoding="utf-8"
    )
    assert "--lib native_improved_roots_rank_intake" not in workflow
    # Native world ACK and Roots effects are still tested in the actual
    # integration pipeline; only the separate retired P2 acceptance was cut.
    for required in (
        "--lib persistent_next_target",
        "--lib world_lethal_terminal",
        "--lib druid_talent_layout_api_tests",
        "forever_roots_native_periodic_ticks_change_with_rank",
        "tests/maintenance/test_fork_sync_retired_p2_guard.py",
    ):
        assert required in workflow, required
