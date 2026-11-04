"""Unrestricted P7.5: source/native routing, not a simulated gate PASS."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p7_2_live as preflight
from tools import wf_gate_p7_5_live as p75
from tools.wf_gate_coverage import measured_p7_dps_proximity


def _player(request):
    return request["raid"]["parties"][0]["players"][0]


def _base():
    return {"raid": {"parties": [{"players": [{
        "class": "ClassDruid",
        "distanceFromTarget": 15,
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "saved-balance",
        "rotation": {"priorityList": [1, 2, 3]},
    }]}]},
        "encounter": {"targets": [{"level": 63}]}}


def test_unrestricted_preflight_uses_authentic_balance_reference_without_world(
        tmp_path, monkeypatch):
    request = tmp_path / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
    witness = tmp_path / "docs/evidence/wf633/WF633_VALIDATION.json"
    request.parent.mkdir(parents=True)
    witness.parent.mkdir(parents=True)
    request.write_text(json.dumps(_base()))
    witness.write_text(json.dumps({
        "engine_revision": preflight.PINNED_RUST, "reference_dps": 728.19}))
    monkeypatch.setattr(preflight, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    monkeypatch.setattr(preflight, "_selected_rust_submodule",
                        lambda *args: "selected-rust-revision")
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("injected native executable")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    # No world_bridge.rs: the approved P7.5 is stationary and native.
    resolved = preflight._pinned_source_runtime(
        tmp_path, "druid", 60, "unrestricted", "P7.5",
        require_world=False)
    assert not isinstance(resolved, dict)
    assert resolved[1]["selected_reference_profile"] == "balance"
    assert resolved[1]["selected_engine_revision"] == "selected-rust-revision"
    assert preflight._pinned_source_runtime(
        tmp_path, "warrior", 60, "unrestricted", "P7.5",
        require_world=False)["status"] == "BLOCKED"


def _setup_paid_unrestricted(monkeypatch, tmp_path, *, prior=None, holdout=730.0):
    base = _base()
    unchanged = copy.deepcopy(base)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("native transport mocked, not run")
    upstream = binary.parents[2]
    (upstream / "data").mkdir(exist_ok=True)
    for name in ("items.jsonl", "enchants.jsonl"):
        (upstream / "data" / name).write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True, exist_ok=True)
    catalogue.write_text("injected catalogue")
    preflights = []
    def prepared(*args, **kwargs):
        preflights.append(kwargs)
        return base, {"reference_dps": 728.19,
                      "selected_engine_revision": "selected-native-pin"}, binary
    monkeypatch.setattr(p75, "_pinned_source_runtime", prepared)
    monkeypatch.setattr(p75, "strongest_accepted_prior", lambda *a, **kw: prior)

    class Validator:
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue
        def __init__(self, *args):
            assert args[-1] is base
        def close(self):
            pass

    def make_candidate(original, pools, rng, **kwargs):
        candidate = copy.deepcopy(original)
        player = _player(candidate)
        player["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        player["talentsString"] = "independently-discovered-talents"
        player["rotation"]["priorityList"] = [3, 2, 1]
        return candidate

    source = SimpleNamespace(
        GearValidator=Validator,
        candidate_pool=lambda v, limit, **kw: ({0: [11], 1: [21]}, {}),
        source_enchant_pools=lambda v, pools: {0: [None], 1: [None]},
        player=_player, make_candidate=make_candidate,
        RejectedGear=ValueError)
    calls = []
    def native(binary, path, iterations, *, rng_mode):
        calls.append((iterations, rng_mode, json.loads(path.read_text())))
        return {"native_dps": holdout if iterations == 1000 else 731.0,
                "iterations": iterations}
    def world(*args, **kwargs):
        raise AssertionError("Unrestricted P7.5 must never invoke gsim 2D world")
    producer = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(
        p75, "_source_module",
        lambda path, name: source if "joint_search" in str(path) else producer)
    return calls, preflights, unchanged, base


def _clock(monkeypatch, times):
    it = iter(times)
    monkeypatch.setattr(p75.time, "monotonic", lambda: next(it, times[-1]))


def test_unrestricted_full_cold_search_and_holdout_are_native_only(
        monkeypatch, tmp_path):
    calls, preflights, unchanged, base = _setup_paid_unrestricted(
        monkeypatch, tmp_path)
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    _clock(monkeypatch, [0.0, 0.0, 300.0, 300.0])
    report = p75.run_live(tmp_path, "druid", 60, spec="unrestricted")
    assert preflights == [{"require_world": False}]
    assert [(n, mode) for n, mode, _ in calls] == [
        (3, "balanced"), (1000, "stochastic")]
    assert report["status"] == "PASS"  # injected routing only, NOT an M1 result
    assert report["runtime_proof"]["executed"] is True
    assert report["production_engine"] == "pinned_mythicsim_rust_native"
    assert report["frozen_stochastic_native_dps"] == 730.0
    assert report["final_required_dps"] == 0.93 * 728.19
    assert report["source_legal_joint_candidates_paid"] == 1
    assert report["independent_300s_search_completed"] is True
    assert "frozen_stochastic_world_dps" not in report
    assert "world_damage_events" not in report
    assert _player(calls[0][2])["talentsString"] == "independently-discovered-talents"
    assert calls[0][2] == calls[1][2]
    assert base == unchanged
    proximity = measured_p7_dps_proximity("P7.5", report)
    assert proximity["dps_objective_actual"] == 730.0
    assert proximity["dps_objective_required"] == round(0.93 * 728.19, 4)


def test_stronger_accepted_stochastic_prior_raises_native_floor(
        monkeypatch, tmp_path):
    prior = {"dps": 800.0, "compatible_gates": ["P7.1"],
             "run_urls": ["https://github.com/example/actions/runs/1"]}
    calls, _, _, _ = _setup_paid_unrestricted(
        monkeypatch, tmp_path, prior=prior)
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    _clock(monkeypatch, [0.0, 0.0, 300.0, 300.0])
    report = p75.run_live(tmp_path, "druid", 60, spec="unrestricted")
    assert [(n, mode) for n, mode, _ in calls] == [
        (3, "balanced"), (1000, "stochastic")]
    assert report["status"] == "FAIL"
    assert report["final_required_dps"] == 744.0
    assert "P7_5_FROZEN_STOCHASTIC_DPS_BELOW_ACCEPTED_PRIOR_FLOOR" in report["reasons"]
    assert "runtime_proof" not in report


def test_bounded_unrestricted_native_probe_cannot_claim_pass(
        monkeypatch, tmp_path):
    calls, _, _, _ = _setup_paid_unrestricted(monkeypatch, tmp_path)
    monkeypatch.delenv("FOREVER_P7_FULL_SOURCE_SEARCH", raising=False)
    _clock(monkeypatch, [0.0, 1.0])
    report = p75.run_live(tmp_path, "druid", 60, spec="unrestricted")
    assert report["status"] == "BLOCKED"
    assert "P7_5_FULL_300S_COLD_SEARCH_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED" in report["reasons"]
    assert len(calls) == 1 and calls[0][0:2] == (3, "balanced")
    assert measured_p7_dps_proximity("P7.5", report) is None
