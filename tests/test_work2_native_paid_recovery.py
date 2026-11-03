"""Validation for explicit paid recovery receipts from the selected Rust actor."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


SCRIPT = (Path(__file__).resolve().parents[1]
          / "integrations/mythicsim-rust/live_two_world_pulls.py")
spec = spec_from_file_location("work2_paid_recovery", SCRIPT)
module = module_from_spec(spec)
spec.loader.exec_module(module)
_summary = module._native_paid_recovery_summary
_command = module._native_world_pulls_command

GAP_NS = 5_000_000_000


def _window(start_ns, *, mana_before=4000.0, mana_after=4200.0,
            health_before=800.0, health_after=800.0,
            mana_ticks=2, health_ticks=0, item_ticks=0, hot_ticks=0):
    return {
        "mode": "native_scheduled_regeneration_only",
        "start_ns": start_ns,
        "end_ns": start_ns + GAP_NS,
        "charged_ns": GAP_NS,
        "mana_before": mana_before,
        "mana_after": mana_after,
        "mana_delta": mana_after - mana_before,
        "health_before": health_before,
        "health_after": health_after,
        "health_delta": health_after - health_before,
        "mana_tick_events": mana_ticks,
        "item_mana_tick_events": item_ticks,
        "health_regen_tick_events": health_ticks,
        "self_heal_dot_tick_events": hot_ticks,
    }


def test_two_paid_gaps_are_measured_from_native_clock_and_resource_events():
    windows = [
        _window(8_000_000_000, mana_before=4000.0, mana_after=4200.0,
                mana_ticks=2, health_ticks=0),
        _window(21_000_000_000, mana_before=4100.0, mana_after=4300.0,
                mana_ticks=2, item_ticks=1, health_ticks=1, hot_ticks=1),
    ]
    result = _summary(windows, 3, GAP_NS)
    assert result["paid_recovery"] is True
    assert result["paid_recovery_ns_per_gap"] == GAP_NS
    assert result["paid_recovery_ns_total"] == 2 * GAP_NS
    assert result["paid_recovery_seconds"] == 10.0
    assert result["native_paid_recovery_events"] == {
        "mana_tick_events": 4,
        "item_mana_tick_events": 1,
        "health_regen_tick_events": 1,
        "self_heal_dot_tick_events": 1,
    }


def test_legacy_native_result_is_compatible_when_recovery_is_zero():
    assert module._native_recovery_contract_matches({"paid_recovery": False}, 2, 0)
    assert module._native_recovery_contract_matches({"world_targets_killed": 2}, 2, 0)


def test_zero_recovery_rejects_forged_paid_recovery_receipts():
    assert not module._native_recovery_contract_matches({
        "paid_recovery": True,
        "paid_recovery_ns_per_gap": 0,
        "paid_recovery_ns_total": 0,
    }, 2, 0)
    assert not module._native_recovery_contract_matches({
        "paid_recovery": False,
        "paid_recovery_ns_per_gap": 1,
        "paid_recovery_ns_total": 0,
    }, 2, 0)


def test_positive_recovery_requires_exact_native_duration_and_mode():
    result = {
        "paid_recovery": True,
        "paid_recovery_ns_per_gap": GAP_NS,
        "paid_recovery_ns_total": 2 * GAP_NS,
        "recovery_mode": "native_scheduled_regeneration_only",
    }
    assert module._native_recovery_contract_matches(result, 3, GAP_NS)
    assert not module._native_recovery_contract_matches(
        {**result, "recovery_mode": "synthetic"}, 3, GAP_NS
    )


def test_zero_interval_is_not_mislabeled_as_paid_recovery():
    result = _summary([], 3, 0)
    assert result["paid_recovery"] is False
    assert result["paid_recovery_ns_total"] == 0
    assert result["native_paid_recovery"] == []


@pytest.mark.parametrize("recovery_ns", [True, False, -1, 1.0, "5", 300_000_000_001])
def test_recovery_duration_rejects_boolean_noninteger_or_out_of_range(recovery_ns):
    with pytest.raises(AssertionError, match="RUST_NATIVE_PAID_RECOVERY_INPUT_INVALID"):
        _summary([], 3, recovery_ns)


@pytest.mark.parametrize("target_count", [True, False, 1, 101, 2.0])
def test_target_count_rejects_boolean_or_out_of_range(target_count):
    with pytest.raises(AssertionError, match="RUST_NATIVE_PAID_RECOVERY_INPUT_INVALID"):
        _summary([], target_count, GAP_NS)


@pytest.mark.parametrize("windows", [
    None,
    [],
    [_window(8_000_000_000)],
    [_window(8_000_000_000), _window(9_000_000_000)],
    [{**_window(8_000_000_000), "mode": "synthetic"} , _window(21_000_000_000)],
    [{**_window(8_000_000_000), "end_ns": 1}, _window(21_000_000_000)],
    [{**_window(8_000_000_000), "mana_after": float("nan")}, _window(21_000_000_000)],
    [{**_window(8_000_000_000), "health_delta": 1.0}, _window(21_000_000_000)],
    [{**_window(8_000_000_000), "mana_tick_events": True}, _window(21_000_000_000)],
    [{**_window(8_000_000_000), "health_regen_tick_events": -1}, _window(21_000_000_000)],
])
def test_partial_or_corrupt_native_recovery_receipts_fail_closed(windows):
    with pytest.raises(AssertionError):
        _summary(windows, 3, GAP_NS)


def test_zero_recovery_rejects_unexpected_native_recovery_windows():
    with pytest.raises(AssertionError, match="RUST_NATIVE_PAID_RECOVERY_WINDOWS_INVALID"):
        _summary([_window(8_000_000_000)], 2, 0)

def test_zero_recovery_omits_recovery_flag_and_passes_explicit_balanced_mode():
    command = _command(
        Path("/tmp/forever-engine"), Path("/tmp/prepared.json"), 2, 0,
        rng_mode="balanced",
    )
    assert command == [
        "/tmp/forever-engine", "native-world-pulls", "--infile",
        "/tmp/prepared.json", "--targets", "2", "--rng-mode", "balanced",
    ]


def test_native_world_cli_requires_explicit_valid_rng_mode():
    with pytest.raises(TypeError):
        _command(Path("/tmp/forever-engine"), Path("/tmp/prepared.json"), 2, 0)
    with pytest.raises(ValueError, match="RUST_NATIVE_WORLD_PULLS_RNG_MODE_INVALID"):
        _command(
            Path("/tmp/forever-engine"), Path("/tmp/prepared.json"), 2, 0,
            rng_mode="automatic",
        )


def test_stochastic_mode_is_available_only_when_explicitly_requested():
    command = _command(
        Path("/tmp/forever-engine"), Path("/tmp/prepared.json"), 2, 0,
        rng_mode="stochastic",
    )
    assert command[-2:] == ["--rng-mode", "stochastic"]


def test_paid_recovery_passes_explicit_nanoseconds_to_native_cli():
    command = _command(
        Path("/tmp/forever-engine"), Path("/tmp/prepared.json"), 3, GAP_NS,
        rng_mode="balanced",
    )
    assert command[-2:] == ["--recovery-ns", str(GAP_NS)]
    assert command[command.index("--rng-mode") + 1] == "balanced"


def test_run_requires_explicit_rng_mode_before_starting_native_process():
    with pytest.raises(TypeError):
        module.run(Path("/tmp/forever-engine"), Path("/tmp/prepared.json"))
