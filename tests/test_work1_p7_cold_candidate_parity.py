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


@pytest.mark.parametrize("number", (2, 3, 4))
def test_all_three_cold_gate_entrypoints_reject_duration_drift(
        monkeypatch, tmp_path, number):
    """Each real gate entrypoint must call the shared causal source control."""
    import copy
    import importlib
    gate = importlib.import_module(f"tools.wf_gate_p7_{number}_live")
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("mock: not pinned native Rust")
    base = {"raid": {"parties": [{"players": [{
        "distanceFromTarget": 15,
        "equipment": {"items": [{"id": 10}]},
        "talentsString": "reference",
        "rotation": {"priorityList": [1, 2, 3]},
    }]}]}}
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *args: (base, {"reference_dps": 728.19}, binary))
    calls = []

    def native(engine, request, iterations):
        calls.append("native")
        return {"iterations": iterations, "native_dps": 730.0,
                "first_duration_s": 120.0}

    def world(engine, request, *, distance, iterations):
        calls.append("world")
        return {"iterations_done": iterations,
                "per_iteration": [{"duration_s": 119.0}] * iterations,
                "sampled_duration_s": 119.0,
                "native_dps": 730.0, "world_mean_dps": 730.0,
                "native_damage_events": 10, "native_world_ticks": 20}

    production = SimpleNamespace(native_source_control=native, run=world)
    if number == 2:
        source = SimpleNamespace(
            mutate_apl=lambda _, actions, rng, cold: list(reversed(actions)))
    elif number == 3:
        source = SimpleNamespace(
            random_build=lambda rng: [[1, 2], [0], [0]],
            validate=lambda allocation: True,
            encode=lambda allocation: "independent-source-talents")
    else:
        for relative in ("data/items.jsonl", "data/enchants.jsonl"):
            p = tmp_path / "upstream" / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("")
        catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
        catalogue.parent.mkdir(parents=True)
        catalogue.write_text("")

        class Validator:
            def __init__(self, *args): pass
            def validate(self, ids): assert ids == [11]
            def close(self): pass

        def swap(reference, ids):
            candidate = copy.deepcopy(reference)
            candidate["raid"]["parties"][0]["players"][0]["equipment"] = {
                "items": [{"id": i} for i in ids]}
            return candidate

        source = SimpleNamespace(
            GearValidator=Validator,
            candidate_pool=lambda validator, limit: ({0: [11]}, {}),
            RejectedGear=ValueError,
            _swap=swap)

    monkeypatch.setattr(
        gate, "_source_module",
        lambda path, name: production if "live_world_probe.py" in str(path)
        else source)
    result = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert result["status"] == "FAIL"
    assert calls == ["native", "world"] * (4 if number == 2 else 3)
    failures = (result.get("cold_candidate_failures", [])
                + result.get("source_candidate_failures", []))
    assert failures and all("FIRST_DURATION_DIVERGED" in f for f in failures)
    assert "winner_live_dps" not in result
