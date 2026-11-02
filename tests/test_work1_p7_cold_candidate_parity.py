"""P7 cold candidates must have real native-vs-world parity before scoring.

Fast control-flow negative regressions only. Genuine Rust/gsim source runs
remain on demand; neither these stubs nor their test results award P7 PASS.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.wf_gate_p7_2_live import _run_source_coupled_candidate


def _outputs():
    native = {"iterations": 3, "native_dps": 731.25,
              "first_duration_s": 120.0}
    world = {"iterations_done": 3, "native_dps": 731.25,
             "world_mean_dps": 731.25, "sampled_duration_s": 120.0,
             "native_damage_events": 10, "native_world_ticks": 20,
             "per_iteration": [{"duration_s": 120.0}] * 3}
    return native, world


def _producer(native, world, calls):
    def native_control(binary, request, iterations):
        calls.append(("native", binary, request, iterations))
        return native

    def live_run(binary, request, *, distance, iterations):
        calls.append(("live", binary, request, distance, iterations))
        return world

    return SimpleNamespace(native_source_control=native_control,
                           run=live_run)


def test_p7_cold_candidate_requires_both_independent_source_executions():
    native, world = _outputs()
    calls = []
    result = _run_source_coupled_candidate(
        _producer(native, world, calls), Path("forever-engine"),
        Path("candidate.json"), distance=15.0, iterations=3)
    assert result is world
    assert calls == [
        ("native", Path("forever-engine"), Path("candidate.json"), 3),
        ("live", Path("forever-engine"), Path("candidate.json"), 15.0, 3),
    ]


@pytest.mark.parametrize(("mutation", "reason"), [
    ({"sampled_duration_s": 119.0}, "FIRST_DURATION_DIVERGED"),
    ({"world_mean_dps": 734.0}, "SAVED_DPS_PARITY_FAILED"),
    ({"native_world_ticks": 0}, "EXECUTION_INCOMPLETE"),
    ({"native_damage_events": 0}, "EXECUTION_INCOMPLETE"),
    ({"iterations_done": 2}, "EXECUTION_INCOMPLETE"),
])
def test_cold_candidate_rejects_world_drift_even_with_positive_dps(
        mutation, reason):
    native, world = _outputs()
    world.update(mutation)
    with pytest.raises(ValueError, match="SOURCE_NATIVE_WORLD_PARITY:.*" + reason):
        _run_source_coupled_candidate(
            _producer(native, world, []), Path("forever-engine"),
            Path("candidate.json"), distance=15.0, iterations=3)
