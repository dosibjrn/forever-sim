"""Actual world-kill/native-clock acceptance for the retained Rust↔gsim runner.

Pure receipt corruption controls; the real two-target production engine and
2D world run in native-session-ack-regressions.yml. This is not P4–P6.
"""
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1]
_world = runpy.run_path(
    str(ROOT / "integrations/mythicsim-rust/live_two_world_pulls.py")
)
_elapsed = _world["_verified_world_elapsed"]
_mana = _world["_native_mana_continuity"]


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


def test_actual_native_mana_snapshots_track_each_acked_world_kill_without_inferred_regen():
    # Both native consumption and a later net gain can be observed; neither
    # delta alone proves an out-of-combat recovery action.
    windows = [
        {"index": 0, "actor_mana": 4900.0},
        {"index": 1, "actor_mana": 4300.0},
        {"index": 2, "actor_mana": 4400.0},
    ]
    assert _mana(windows, 3) == {
        "native_actor_mana_after_world_kills": [4900.0, 4300.0, 4400.0],
        "native_actor_mana_delta_between_world_kills": [-600.0, 100.0],
        "minimum_native_actor_mana": 4300.0,
    }
    assert _mana([{"index": 0, "actor_mana": 0}], 1)[
        "minimum_native_actor_mana"] == 0.0  # source-legal manaless classes


@pytest.mark.parametrize("bad", [None, True, False, "10", -0.01,
                                   float("nan"), float("inf"), float("-inf")])
def test_native_world_mana_receipts_fail_closed_on_missing_corrupt_resource(bad):
    with pytest.raises(AssertionError, match="RUST_MULTI_WORLD_NATIVE_MANA_INVALID"):
        _mana([{"index": 0, "actor_mana": 12.0},
               {"index": 1, "actor_mana": bad}], 2)


@pytest.mark.parametrize("windows,count", [
    ([], 2),
    ([{"index": 0, "actor_mana": 8.0}], 2),
    ([{"index": 0, "actor_mana": 8.0}], 0),
    ([{"index": 1, "actor_mana": 8.0}], 1),
    ([{"index": True, "actor_mana": 8.0}], 1),
    ([{"index": 0, "actor_mana": 8.0},
      {"index": 0, "actor_mana": 8.0}], 2),
])
def test_native_world_mana_samples_cannot_skip_or_duplicate_target(windows, count):
    with pytest.raises(AssertionError, match="RUST_MULTI_WORLD_NATIVE_MANA_WINDOWS_INVALID"):
        _mana(windows, count)
