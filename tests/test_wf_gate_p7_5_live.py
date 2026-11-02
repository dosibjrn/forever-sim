"""P7.5 source-legal cold joint fixed-value mutation, not a fake PASS."""
import copy
import random
from types import SimpleNamespace

from tools import wf_gate_p7_5_live as gate


def _base():
    return {"raid": {"parties": [{"players": [{
        "equipment": {"items": [{"id": 10}, {"id": 20}]},
        "talentsString": "reference",
        "rotation": {"priorityList": [1, 2, 3]},
    }]}]}}


def test_cold_joint_changes_all_three_dimensions_and_does_not_seed_winner():
    original = _base()
    prior = copy.deepcopy(original)
    def player(obj):
        return obj["raid"]["parties"][0]["players"][0]
    def create(reference, pools, rng, item_names=None):
        q = copy.deepcopy(reference)
        p = player(q)
        p["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        p["talentsString"] = "new-legal-source"
        p["rotation"]["priorityList"] = [3, 2, 1]
        return q
    v = SimpleNamespace(engine={11: {"name": "One"}, 21: {"name": "Two"}},
                        validate=lambda ids, enchants: True)
    source = SimpleNamespace(make_candidate=create, player=player,
                             RejectedGear=ValueError)
    candidate = gate._cold_joint(original, source, v, {}, random.Random(1))
    assert player(candidate)["talentsString"] != player(original)["talentsString"]
    assert player(candidate)["rotation"] != player(original)["rotation"]
    assert player(candidate)["equipment"] != player(original)["equipment"]
    assert original == prior


def test_unrelated_checkpoint_does_not_use_balance_ref(tmp_path):
    report = gate.run_live(tmp_path, "warrior", 40, spec="arms")
    assert report["status"] == "BLOCKED"
    assert "P7_5_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT" in report["reasons"]


def test_real_p75_provider_rejects_equal_dps_with_wrong_world_duration(monkeypatch, tmp_path):
    """Negative control: a plausible DPS score cannot bypass causal parity."""
    from pathlib import Path
    import json
    from tools import wf_gate_p7_5_live as p75

    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("focused test uses injected production interface")
    for relative in ("data/items.jsonl", "data/enchants.jsonl"):
        path = tmp_path / "upstream" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("")
    original = _base()
    original["raid"]["parties"][0]["players"][0]["distanceFromTarget"] = 15
    monkeypatch.setattr(p75, "_pinned_source_runtime",
                        lambda *args: (original, {"reference_dps": 728.19}, binary))

    class Validator:
        engine = {11: {"name": "one"}, 21: {"name": "two"}}
        # This parity-negative-control fixture supplies a source validator
        # seam; the real LFS/SQLite check is independently tested above.
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue
        def __init__(self, *args): pass
        def validate(self, ids, enchants): assert ids == [11, 21]
        def close(self): pass

    def player(q):
        return q["raid"]["parties"][0]["players"][0]

    def cold(reference, pools, rng, item_names=None):
        candidate = copy.deepcopy(reference)
        p = player(candidate)
        p["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        p["talentsString"] = "source-legal-cold"
        p["rotation"]["priorityList"] = [3, 2, 1]
        return candidate

    source = SimpleNamespace(
        GearValidator=Validator,
        candidate_pool=lambda validator, limit: ({0: [11], 1: [21]}, {}),
        make_candidate=cold, player=player, RejectedGear=ValueError)
    production = SimpleNamespace(
        native_source_control=lambda binary, path, n, *, rng_mode: {
            "iterations": n, "first_duration_s": 120.0, "native_dps": 730.0},
        run=lambda binary, path, distance, iterations, *, rng_mode: {
            "iterations_done": iterations,
            "per_iteration": [
                {"iteration_index": i, "duration_s": 119.0,
                 "world_dps": 730.0, "world_applied_damage": 730.0 * 119.0}
                for i in range(iterations)],
            "sampled_duration_s": 119.0,
            "native_dps": 730.0, "world_mean_dps": 730.0,
            "native_damage_events": 10, "native_world_ticks": 20})
    monkeypatch.setattr(p75, "_source_module",
                        lambda path, name: source if "joint_search" in str(path)
                        else production)
    report = p75.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "FAIL"
    assert report["reasons"] == [
        "P7_5_NO_SOURCE_LEGAL_JOINT_CANDIDATE_REACHED_NATIVE_WORLD"]
    assert any("P7_5_P7_1_NATIVE_WORLD_FIRST_DURATION_DIVERGED" in reason
               for reason in report["cold_candidate_failures"])
    assert "joint_cold_world_dps" not in report


def test_shared_source_preflight_uses_exact_p7_gate_reason(tmp_path):
    from tools.wf_gate_p7_2_live import _pinned_source_runtime
    for gate_name in ("P7.2", "P7.3", "P7.4", "P7.5"):
        report = _pinned_source_runtime(
            tmp_path, "priest", 60, "holy", gate_name)
        assert report["status"] == "BLOCKED"
        assert report["reasons"] == [
            gate_name.replace(".", "_") +
            "_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]


def test_full_p75_freezes_executed_joint_winner_and_keeps_prior_fail_closed(
        monkeypatch, tmp_path):
    """Injected producer routing; this is NOT a real 300s or P7.5 PASS."""
    import hashlib
    import json
    from pathlib import Path

    original = _base()
    original["raid"]["parties"][0]["players"][0]["distanceFromTarget"] = 15
    unchanged = copy.deepcopy(original)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_text("producer stub, never invoked")
    upstream = binary.parents[2]
    (upstream / "data").mkdir()
    (upstream / "data/items.jsonl").write_text("")
    (upstream / "data/enchants.jsonl").write_text("")
    catalogue = tmp_path / "data/forever/catalogue/items_2026-09-29.sqlite"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text("validator injected")
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    clock = iter([0.0, 0.0, 300.0, 300.0])
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock, 300.0))
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: (original, {"reference_dps": 728.19}, binary))
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *a, **kw: None)

    class Validator:
        engine = {11: {"name": "one"}, 21: {"name": "two"}}
        @staticmethod
        def require_sqlite_catalogue(path):
            assert path == catalogue
        def __init__(self, *args):
            assert args[-1] is original
        def validate(self, ids, enchants):
            assert ids == [11, 21]
        def close(self): pass

    pool_calls = []
    def pool(v, limit):
        pool_calls.append(limit)
        return ({0: [11], 1: [21]}, {})

    def player(q):
        return q["raid"]["parties"][0]["players"][0]

    def make_candidate(base, pools, rng, item_names=None):
        q = copy.deepcopy(base)
        p = player(q)
        p["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        p["talentsString"] = "new-source-legal"
        p["rotation"]["priorityList"] = [3, 2, 1]
        return q

    source = SimpleNamespace(
        GearValidator=Validator, candidate_pool=pool, make_candidate=make_candidate,
        player=player, RejectedGear=ValueError)
    calls = []
    def native(binary, path, n, *, rng_mode):
        calls.append(("native", n, rng_mode, path.read_text()))
        return {"native_dps": 730.0}
    def world(binary, path, distance, iterations, *, rng_mode):
        assert distance == 15
        calls.append(("world", iterations, rng_mode, path.read_text()))
        return {"world_mean_dps": 729.0, "iterations_done": iterations,
                "native_damage_events": 20, "native_world_ticks": 30}
    producer = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(
        gate, "_source_module",
        lambda path, name: source if "joint_search" in str(path) else producer)

    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert pool_calls == [80]
    assert [(a, b, c) for a, b, c, _ in calls] == [
        ("native", 3, "balanced"), ("world", 3, "balanced"),
        ("native", 1000, "stochastic"), ("world", 1000, "stochastic")]
    assert json.loads(calls[0][3]) == json.loads(calls[-1][3])
    assert report["frozen_request_raw_sha256"] == hashlib.sha256(
        calls[-1][3].encode()).hexdigest()
    assert report["independent_300s_search_completed"] is True
    assert report["cold_unique_source_requests"] == 1
    assert report["source_legal_joint_candidates_paid"] == 1
    assert report["frozen_stochastic_iterations"] == 1000
    assert report["frozen_stochastic_external_only_floor_met"] is True
    assert report["final_required_dps"] is None
    assert report["status"] == "FAIL"
    assert "P7_5_ACCEPTED_COMPATIBLE_PRIOR_REQUIRED_FOR_FINAL_DPS_FLOOR" in report["reasons"]
    assert original == unchanged


def test_p75_rejects_invalid_full_search_mode_before_source_work(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "anything")
    monkeypatch.setattr(gate, "_pinned_source_runtime",
                        lambda *a: ({}, {"reference_dps": 728.19}, tmp_path / "binary"))
    assert gate.run_live(tmp_path, "druid", 60, spec="balance") == {
        "status": "BLOCKED", "reasons": ["P7_5_INVALID_FULL_SOURCE_SEARCH_MODE"]}


def test_joint_cold_admits_independently_rediscovered_reference_axes():
    """RED on old provider: matching even one reference axis was discarded.

    These are source-generated cold builds; equality is not a saved-build seed.
    The real catalogue/native legality remains a separate paid production check.
    """
    original = _base()
    player = lambda q: q["raid"]["parties"][0]["players"][0]
    tried = []
    for unchanged_axis in ("gear", "talents", "rotation", "all"):
        candidate = copy.deepcopy(original)
        p = player(candidate)
        if unchanged_axis != "gear" and unchanged_axis != "all":
            p["equipment"]["items"] = [{"id": 11}, {"id": 21}]
        if unchanged_axis != "talents" and unchanged_axis != "all":
            p["talentsString"] = "independently-found-legal"
        if unchanged_axis != "rotation" and unchanged_axis != "all":
            p["rotation"]["priorityList"] = [3, 1, 2]
        def generate(reference, pools, rng, elite=None, item_names=None):
            assert elite is None  # never seed candidate with a paid prior winner
            assert reference == original
            return copy.deepcopy(candidate)
        def validate(ids, enchants):
            tried.append((ids, enchants))
            return True
        validator = SimpleNamespace(
            engine={10: {"name": "original"}, 20: {"name": "original2"},
                    11: {"name": "cold"}, 21: {"name": "cold2"}},
            validate=validate)
        source = SimpleNamespace(make_candidate=generate, player=player,
                                 RejectedGear=ValueError)
        selected = gate._cold_joint(original, source, validator, {}, random.Random(4))
        assert selected == candidate, unchanged_axis
    assert len(tried) == 4
    assert original == _base()
