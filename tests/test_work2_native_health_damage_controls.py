"""The selected Rust health-damage receipt must prove both attacking and quiet controls.

These tests exercise production receipt validation, not simulated player damage
or P4–P6 acceptance. The real selected-engine + gsim execution is in Actions.
"""
from pathlib import Path
import json
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[1]
_native_world = runpy.run_path(
    str(ROOT / "integrations/mythicsim-rust/live_two_world_pulls.py")
)
_summary = _native_world["_native_health_damage_summary"]
_run_native_world = _native_world["run"]


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


def test_native_incoming_damage_request_reaches_rust_without_python_enemy_shape_veto(
    tmp_path, monkeypatch
):
    """A prepared Warlock target is enough to attempt native execution.

    The native receipt (not a Python enemy-key guess) determines whether
    incoming player damage actually occurred. No game damage is mocked.
    """
    prepared = tmp_path / "warlock-prepared.json"
    prepared.write_text(json.dumps({
        "request_sha256": "f" * 64,
        "target": {"auto_swing_melee": True},
    }))
    launched = []

    def native_launch(cmd, **kwargs):
        launched.append(cmd)
        raise RuntimeError("reached selected native executable")

    monkeypatch.setattr(_run_native_world.__globals__["subprocess"],
                        "Popen", native_launch)
    with pytest.raises(RuntimeError, match="reached selected native executable"):
        _run_native_world(
            Path("/mock-native-engine"), prepared,
            classic_mob_level=20, target_count=2,
            require_native_health_damage=True,
        )
    assert launched and "native-world-pulls" in launched[0]
    assert "--targets" in launched[0]
