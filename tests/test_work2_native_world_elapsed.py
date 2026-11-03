"""Actual world-kill/native-clock acceptance for the retained Rust↔gsim runner.

Pure receipt corruption controls; the real two-target production engine and
2D world run in native-session-ack-regressions.yml. This is not P4–P6.
"""
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1]
_elapsed = runpy.run_path(
    str(ROOT / "integrations/mythicsim-rust/live_two_world_pulls.py")
)["_verified_world_elapsed"]


def _rows(native_clocks=(5_000_000_000, 11_500_000_000),
          world_clocks=(5_000_000_000, 11_500_000_000)):
    native = [{"index": index, "native_kill_ns": ns}
              for index, ns in enumerate(native_clocks)]
    world = [{"target_id": f"m{index}", "world_kill_clock_ns": ns}
             for index, ns in enumerate(world_clocks)]
    return native, world


def test_paid_world_clock_is_actual_native_and_ack_elapsed_not_fight_duration():
    receipt = _elapsed(*_rows())
    assert receipt == {
        "world_elapsed_seconds": 11.5,
        "world_seconds_per_target_without_paid_recovery": 5.75,
        "world_per_target_elapsed_seconds_without_paid_recovery": [5.0, 6.5],
    }
    assert "paid_recovery" not in receipt


@pytest.mark.parametrize("native_clocks,world_clocks", [
    ((5_000_000_000, 11_000_000_000), (5_000_000_000, 11_500_000_000)),
    ((5_000_000_000, 5_000_000_000), (5_000_000_000, 5_000_000_000)),
    ((5_000_000_000, 4_000_000_000), (5_000_000_000, 4_000_000_000)),
    ((0, 11_500_000_000), (0, 11_500_000_000)),
    ((5_000_000_000, True), (5_000_000_000, True)),
    ((5_000_000_000, 11.5), (5_000_000_000, 11.5)),
    ((5_000_000_000, None), (5_000_000_000, None)),
])
def test_forged_noncausal_or_nonmonotonic_native_world_kill_clocks_fail(
    native_clocks, world_clocks
):
    with pytest.raises(AssertionError, match="RUST_WORLD_KILL_CLOCK_NOT_CAUSAL"):
        _elapsed(*_rows(native_clocks, world_clocks))


def test_missing_window_or_mismatched_target_count_cannot_produce_paid_metric():
    native, world = _rows()
    for x, y in (([], []), (native[:1], world), (native, world[:1])):
        with pytest.raises(AssertionError, match="RUST_WORLD_ELAPSED_TARGET_COUNT_MISMATCH"):
            _elapsed(x, y)


def test_native_window_index_must_match_real_world_kill_order():
    native, world = _rows()
    native[1]["index"] = 3
    with pytest.raises(AssertionError, match="RUST_WORLD_KILL_CLOCK_NOT_CAUSAL"):
        _elapsed(native, world)


def test_missing_or_boolean_timestamps_are_not_integer_source_clock():
    native, world = _rows()
    native[1].pop("native_kill_ns")
    with pytest.raises(AssertionError, match="RUST_WORLD_KILL_CLOCK_NOT_CAUSAL"):
        _elapsed(native, world)
    native, world = _rows()
    world[1]["world_kill_clock_ns"] = False
    with pytest.raises(AssertionError, match="RUST_WORLD_KILL_CLOCK_NOT_CAUSAL"):
        _elapsed(native, world)
