"""The selected Rust health-damage receipt must prove both attacking and quiet controls.

These tests exercise production receipt validation, not simulated player damage
or P4–P6 acceptance. The real selected-engine + gsim execution is in Actions.
"""
from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[1]
_summary = runpy.run_path(
    str(ROOT / "integrations/mythicsim-rust/live_two_world_pulls.py")
)["_native_health_damage_summary"]


def _window(index: int, amount: float, events: int) -> dict:
    return {
        "index": index,
        "native_health_damage_taken": amount,
        "native_health_damage_events": events,
    }


def test_selected_native_quiet_control_requires_observed_zero_events():
    windows = [_window(0, 0.0, 0), _window(1, 0.0, 0)]
    receipt = _summary(windows, require_positive=False, require_zero=True)
    assert receipt == {"observed": True, "damage_taken": 0.0, "damage_events": 0}


def test_selected_native_attack_control_requires_actual_health_damage():
    windows = [_window(0, 125.0, 1), _window(1, 250.0, 2)]
    receipt = _summary(windows, require_positive=True)
    assert receipt == {
        "observed": True, "damage_taken": 375.0, "damage_events": 3,
    }
    with pytest.raises(AssertionError, match="RUST_WORLD_UNEXPECTED_NATIVE_HEALTH_DAMAGE"):
        _summary(windows, require_positive=False, require_zero=True)


@pytest.mark.parametrize("windows", [
    [{"index": 0}, {"index": 1}],
    [_window(0, 0, 0), {"index": 1}],
])
def test_native_health_controls_do_not_pass_missing_or_partial_selected_port(windows):
    with pytest.raises(AssertionError, match="RUST_WORLD_NATIVE_HEALTH_DAMAGE_"):
        _summary(windows, require_positive=False, require_zero=True)


def test_native_health_controls_reject_false_zero_and_invalid_event_totals():
    with pytest.raises(AssertionError, match="RUST_WORLD_UNEXPECTED_NATIVE_HEALTH_DAMAGE"):
        _summary([_window(0, 0, 1)], require_positive=False, require_zero=True)
    with pytest.raises(AssertionError, match="RUST_WORLD_NATIVE_HEALTH_DAMAGE_RECEIPT_INVALID"):
        _summary([_window(0, -1, 0)], require_positive=False, require_zero=True)
    with pytest.raises(AssertionError, match="RUST_WORLD_NATIVE_ATTACK_NOT_OBSERVED"):
        _summary([_window(0, 0, 0)], require_positive=True)
