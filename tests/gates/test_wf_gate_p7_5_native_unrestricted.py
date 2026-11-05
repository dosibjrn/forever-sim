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


def test_feral_p75_preflight_uses_authentic_feral_request_without_balance_witness(
        tmp_path, monkeypatch):
    request = tmp_path / "docs/evidence/druid-l60-feral/p7.1/saved_811_request.json"
    request.parent.mkdir(parents=True)
    base = _base()
    _player(base)["feralCatDruid"] = {}
    request.write_text(json.dumps(base))
    monkeypatch.setattr(preflight, "SAVED_FERAL_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    monkeypatch.setattr(preflight, "_selected_rust_submodule",
                        lambda *args: "selected-feral-native-pin")
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("native transport mocked")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    resolved = preflight._pinned_source_runtime(
        tmp_path, "druid", 60, "feral", "P7.5", require_world=False)
    assert not isinstance(resolved, dict)
    assert resolved[1]["selected_reference_profile"] == "feral"
    assert resolved[1]["reference_dps"] == preflight.FERAL_REFERENCE_DPS
    assert resolved[1]["source_request_raw_sha256"] == preflight.SAVED_FERAL_RAW_SHA


def test_feral_p75_native_paid_search_uses_go_rules_and_rust_gear_options(
        monkeypatch, tmp_path):
    calls, preflights, unchanged, base = _setup_paid_unrestricted(
        monkeypatch, tmp_path, holdout=730.0)
    # The authentic saved Feral request omits the 2D world distance field.
    _player(base).pop("distanceFromTarget")
    unchanged = copy.deepcopy(base)
    original_loader = p75._source_module
    rust_pool_calls = []
    native_go_rules = []

    def load(path, name):
        if "p74_gear_search" in str(path):
            def options(items, enchants):
                rust_pool_calls.append((items.name, enchants.name))
                return ({0: [11], 1: [21]}, {0: [None], 1: [None]}, {})
            return SimpleNamespace(pinned_rust_candidate_pool=options)
        module = original_loader(path, name)
        if "live_world_probe" in str(path):
            def native(binary, request, iterations, *, rng_mode, go_rules=False):
                native_go_rules.append(go_rules)
                return module.native_source_control(
                    binary, request, iterations, rng_mode=rng_mode)
            return SimpleNamespace(native_source_control=native, run=module.run)
        return module

    monkeypatch.setattr(p75, "_source_module", load)
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    _clock(monkeypatch, [0.0, 0.0, 300.0, 300.0])
    report = p75.run_live(tmp_path, "druid", 60, spec="feral")
    assert preflights == [{"require_world": False}]
    assert rust_pool_calls == [("items.jsonl", "enchants.jsonl")]
    assert native_go_rules == [True, True]
    assert [(n, mode) for n, mode, _ in calls] == [
        (3, "balanced"), (1000, "stochastic")]
    assert report["status"] == "PASS"  # injected transport, not gate evidence
    assert report["native_rules"] == "go_reference"
    assert report["reference_profile"] is None  # mocked preflight has no profile
    assert report["source_request_raw_sha256"] == p75.SAVED_FERAL_RAW_SHA
    assert base == unchanged


def test_feral_joint_generator_uses_native_proposals_not_balance_talent_rules(
        monkeypatch):
    import importlib
    import random
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "integrations/mythicsim-rust"))
    joint = importlib.import_module("p75_joint_search")
    base = _base()
    player = _player(base)
    player["equipment"]["items"] = [{"id": 100 + i} for i in range(16)]
    pools = {i: [100 + i, 200 + i] for i in range(16)}
    monkeypatch.setattr(joint, "random_build", lambda rng: (_ for _ in ()).throw(
        AssertionError("Balance-only talent generator called")))
    monkeypatch.setattr(joint, "parse", lambda *args: (_ for _ in ()).throw(
        AssertionError("Balance-only talent parser called")))
    monkeypatch.setattr(joint, "encode", lambda *args: (_ for _ in ()).throw(
        AssertionError("Balance-only talent encoder called")))
    observed = []
    def mutate(actions, grammar, rng, **kwargs):
        observed.append(kwargs)
        return [3, 2, 1]
    monkeypatch.setattr(joint, "mutate_apl", mutate)
    proposals = SimpleNamespace(
        cold_talent_string=lambda template, rng: "cold-native-proposal",
        mutate_talent_string=lambda parent, rng: "paid-native-proposal")
    cold = joint.make_candidate(
        base, pools, __import__("random").Random(1),
        talent_proposals=proposals, preserve_source_conditions=True)
    assert _player(cold)["talentsString"] == "cold-native-proposal"
    assert observed[-1]["preserve_source_conditions"] is True
    paid = joint.make_candidate(
        base, pools, random.Random(2), elite=cold,
        repair_axes=("talents", "rotation"),
        talent_proposals=proposals, preserve_source_conditions=True)
    assert _player(paid)["talentsString"] == "paid-native-proposal"
    assert observed[-1]["preserve_source_conditions"] is True
    assert _player(base)["talentsString"] == "saved-balance"


def test_feral_cold_rank_explorer_uses_independent_sparse_then_broad_draws():
    import random
    from src.engine_client.native_talent_proposals import (
        ColdRankLadderExplorer, cold_talent_string)

    template = "050022-55000032021032212051-053"
    original_budget = sum(int(c) for c in template if c.isdigit())
    explorer = ColdRankLadderExplorer()
    samples = [explorer.cold_talent_string(template, random.Random(100 + i))
               for i in range(5)]
    for sample, ceiling in zip(samples, (1, 2, 3, 5, 9)):
        assert [len(tree) for tree in sample.split("-")] == [6, 20, 3]
        digits = [int(c) for c in sample if c.isdigit()]
        assert max(digits) <= ceiling
        assert sum(digits) == min(original_budget, 29 * ceiling)
        assert sample != template or ceiling > 1  # never seed from source
    assert max(int(c) for c in samples[0] if c.isdigit()) == 1
    assert explorer.cold_draws == 5
    import pytest
    with pytest.raises(ValueError, match="RANK_CEILING_INVALID"):
        cold_talent_string(template, random.Random(7), rank_ceiling=0)
