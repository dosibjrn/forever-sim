"""P7.3 source-talent cold discovery contract, never a synthetic PASS."""
import copy
import random
from types import SimpleNamespace
import pytest
from tools import wf_gate_p7_3_live as gate


def _reference():
    return {"raid": {"parties": [{"players": [{
        "talentsString": "old", "equipment": {"items": [{"id": 17}]},
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": 1}}}]},
    }]}]}}


def test_cold_talent_discovery_preserves_full_gear_apl_and_original():
    original = _reference()
    baseline = copy.deepcopy(original)
    source = SimpleNamespace(random_build=lambda rng: [[1, 2], [0], [0]],
                             validate=lambda ranks: True,
                             encode=lambda ranks: "independent_legal")
    new = gate._cold_talents(original, random.Random(647003), source)
    assert new != original
    assert new["raid"]["parties"][0]["players"][0]["talentsString"] == "independent_legal"
    assert new["raid"]["parties"][0]["players"][0]["rotation"] == baseline["raid"]["parties"][0]["players"][0]["rotation"]
    assert new["raid"]["parties"][0]["players"][0]["equipment"] == baseline["raid"]["parties"][0]["players"][0]["equipment"]
    assert original == baseline


def test_illegal_source_talents_cannot_run():
    source = SimpleNamespace(random_build=lambda rng: None,
                             validate=lambda ranks: False)
    with pytest.raises(ValueError, match="ALLOCATION_ILLEGAL"):
        gate._cold_talents(_reference(), random.Random(1), source)


def test_saved_identity_mismatch_fails_closed(tmp_path):
    report = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert report["status"] == "BLOCKED"
    assert "P7_3_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT" in report["reasons"]


def test_full_p73_freezes_a_unique_talent_winner_before_stochastic_holdout(
        monkeypatch, tmp_path):
    """Tests real-producer call routing, NOT a 300s or 1000-fight acceptance."""
    import json
    import hashlib
    from tools import wf_gate_p7_3_live as p73

    base = _reference()
    base["raid"]["parties"][0]["players"][0].update({
        "class": "ClassDruid", "distanceFromTarget": 15})
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "1")
    # Allow cold and paid-elite attempts before the simulated 300s boundary.
    # Both may rediscover the same legal allocation; it is paid only once.
    clock = iter([0.0] * 10 + [300.0] * 10)
    monkeypatch.setattr(p73.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        p73, "_pinned_source_runtime",
        lambda *args: (base, {"reference_dps": 728.19}, tmp_path / "binary"))
    monkeypatch.setattr(
        p73, "_source_native_world_parity", lambda *a, **kw: None)
    source = SimpleNamespace(
        random_build=lambda rng, target=None: [[1], [0], [0]],
        parse=lambda value: [[1], [0], [0]],
        edit_neighbors=lambda ranks, rng: [[1], [0], [0]],
        validate=lambda ranks: True,
        encode=lambda ranks: "cold-source-legal")
    calls = []
    def native(binary, path, n, *, rng_mode):
        calls.append(("native", n, rng_mode, path.read_text()))
        return {"native_dps": 730.0}
    def world(binary, path, distance, iterations, *, rng_mode):
        calls.append(("world", iterations, rng_mode, path.read_text()))
        return {"world_mean_dps": 729.0,
                "native_damage_events": 10, "native_world_ticks": 15,
                "iterations_done": iterations}
    producer = SimpleNamespace(native_source_control=native, run=world)
    monkeypatch.setattr(
        p73, "_source_module",
        lambda path, name: source if "p73_talent" in str(path) else producer)

    from tools.wf_gate import _run_live_gate
    report = _run_live_gate(tmp_path, "druid", 60, "balance", "P7.3", "")
    assert [(kind, n, mode) for kind, n, mode, _ in calls] == [
        ("native", 3, "balanced"), ("world", 3, "balanced"),
        ("native", 1000, "stochastic"), ("world", 1000, "stochastic")]
    assert json.loads(calls[0][3]) == json.loads(calls[3][3])
    assert report["cold_unique_source_requests"] == 1
    assert report["winner_selection"] == "best_balanced_live_screen"
    assert report["paid_stochastic_finalists"] == 0
    assert report["stochastic_parent_proposals"] == 0
    # Real gate receipt exposes which talent build was frozen; a request
    # hash alone cannot distinguish unchanged-effective-rank hypotheses.
    assert report["source_original_talents"] == "old"
    assert report["cold_winner_talents"] == "cold-source-legal"
    assert report["source_legal_cold_candidates_paid"] == 1
    assert report["independent_300s_search_completed"] is True
    assert report["frozen_stochastic_iterations"] == 1000
    assert report["frozen_stochastic_reference_floor_met"] is True
    assert report["status"] == "PASS"  # mocked routing, not real native/world evidence
    assert report["runtime_proof"]["executed"] is True
    assert report["runtime_proof"]["source_revision"] == report["frozen_request_raw_sha256"]
    assert report["reasons"] == []


def test_p73_invalid_full_search_flag_blocks_without_running(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "maybe")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *a: (_reference(), {"reference_dps": 728.19},
                     tmp_path / "binary"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report == {"status": "BLOCKED",
                      "reasons": ["P7_3_INVALID_FULL_SOURCE_SEARCH_MODE"]}


def test_p73_paid_elite_uses_source_legal_neighbors_not_saved_reference():
    """An elite is only an executed winner from this search, not the baseline."""
    base = _reference()
    original = copy.deepcopy(base)
    elite = copy.deepcopy(base)
    elite["raid"]["parties"][0]["players"][0]["talentsString"] = "paid-best"
    calls = []
    class TalentSource:
        @staticmethod
        def random_build(rng, target=None):
            calls.append(("cold" if target is None else "local", target))
            return [[1], [0], [0]]
        @staticmethod
        def parse(value):
            calls.append(("parse", value))
            return [[4], [0], [0]]
        @staticmethod
        def validate(ranks):
            return True
        @staticmethod
        def edit_neighbors(ranks, rng):
            calls.append(("neighbor", ranks))
            return [[3], [1], [0]]
        @staticmethod
        def encode(ranks):
            return "legal-" + str(ranks)

    cold = gate._cold_talents(base, random.Random(1), TalentSource)
    assert calls == [("cold", None)]  # no saved-reference seed
    assert cold["raid"]["parties"][0]["players"][0]["talentsString"] != "old"
    calls.clear()
    improved = gate._cold_talents(
        base, random.Random(1), TalentSource, elite=elite)
    assert ("parse", "paid-best") in calls
    assert ("neighbor", [[4], [0], [0]]) in calls
    assert all(not (op == "cold") for op, _ in calls)
    assert improved["raid"]["parties"][0]["players"][0]["talentsString"] == "legal-[[3], [1], [0]]"
    assert base == original
    assert elite["raid"]["parties"][0]["players"][0]["talentsString"] == "paid-best"


def test_p73_paid_elite_rejects_fixed_gear_or_apl_change():
    base = _reference()
    class TalentSource:
        @staticmethod
        def parse(value):
            raise AssertionError("must reject altered paid candidate first")

    for axis in ("equipment", "rotation"):
        elite = copy.deepcopy(base)
        elite["raid"]["parties"][0]["players"][0][axis] = {"illegal": True}
        with pytest.raises(ValueError, match="P73_PAID_ELITE_CHANGED_FIXED_DIMENSIONS"):
            gate._cold_talents(base, random.Random(3), TalentSource, elite=elite)


def test_p73_local_full_draw_uses_paid_target_not_saved_reference():
    base = _reference()
    elite = copy.deepcopy(base)
    elite["raid"]["parties"][0]["players"][0]["talentsString"] = "paid-best"
    calls = []
    class TalentSource:
        @staticmethod
        def parse(value):
            assert value == "paid-best"
            return [[4], [0], [0]]
        @staticmethod
        def validate(ranks):
            return True
        @staticmethod
        def random_build(rng, target=None):
            calls.append(target)
            return [[3], [0], [1]]
        @staticmethod
        def edit_neighbors(ranks, rng):
            raise AssertionError("high RNG must choose local full draw")
        @staticmethod
        def encode(ranks):
            return "legal-targeted"
    class HighRandom(random.Random):
        def random(self):
            return 0.99
    result = gate._cold_talents(
        base, HighRandom(8), TalentSource, elite=elite)
    assert calls == [[[4], [0], [0]]]
    assert result["raid"]["parties"][0]["players"][0]["talentsString"] == "legal-targeted"


def test_p73_paid_elite_archive_can_choose_other_scored_winner():
    """Reproduced search issue: local mutations must not only see rank #1."""
    class ChooseLast:
        @staticmethod
        def choice(options):
            return options[-1]

    top = {"source": "paid-best", "talentsString": "a"}
    other = {"source": "paid-second", "talentsString": "b"}
    from tools.wf_gate_p7_3_live import _paid_elite_choice
    # These entries are deliberately already paid/source-legal; caller appends
    # them only AFTER native/world parity and a valid score.
    elites = [(900.0, top), (800.0, other)]
    assert _paid_elite_choice(elites, ChooseLast(), 2) is other
    assert _paid_elite_choice(elites, ChooseLast(), 5) is None
    assert _paid_elite_choice([], ChooseLast(), 2) is None


def test_p73_paid_elite_archive_caps_source_pool_to_top_18():
    from tools.wf_gate_p7_3_live import _paid_elite_choice

    class PickLast:
        @staticmethod
        def choice(options):
            assert len(options) == 18
            return options[-1]

    elites = [(float(100-i), {"rank": i}) for i in range(22)]
    assert _paid_elite_choice(elites, PickLast(), 1)["rank"] == 17



        monkeypatch, tmp_path):
    """The independent paid re-rank must use native+2D, not screen-only DPS."""
    source = _reference()
    source["simOptions"] = {"randomSeed": "42"}
    original = copy.deepcopy(source)
    calls = []

    def native(binary, path, n, *, rng_mode):
        req = __import__("json").loads(path.read_text())
        calls.append(("native", req, n, rng_mode))
        return {"native_dps": 735.0}

    def world(binary, path, distance, iterations, *, rng_mode):
        req = __import__("json").loads(path.read_text())
        calls.append(("world", req, iterations, rng_mode))
        return {"world_mean_dps": 734.0,
                "iterations_done": 24, "native_damage_events": 10,
                "native_world_ticks": 12}

    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda native, live, count: None)
    producer = SimpleNamespace(native_source_control=native, run=world)
    score, receipt = gate._paid_stochastic_finalist(
        producer, tmp_path / "engine", source, 15)
    assert score == 734.0
    assert receipt["world_mean_dps"] == 734.0
    assert [k for k, *_ in calls] == ["native", "world"]
    assert all(n == 24 and mode == "stochastic" for _, _, n, mode in calls)
    assert all(req["simOptions"]["randomSeed"] == "1947003"
               for _, req, _, _ in calls)
    assert all(req["raid"] == original["raid"] for _, req, _, _ in calls)
    assert source == original  # finalist comparison never mutates original


def test_p73_paid_stochastic_finalist_rejects_unpaired_native_world(
        monkeypatch, tmp_path):
    source = _reference()
    source["simOptions"] = {"randomSeed": "42"}
    producer = SimpleNamespace(
        native_source_control=lambda *args, **kw: {"native_dps": 1.0},
        run=lambda *args, **kw: {"world_mean_dps": 2.0,
                                "iterations_done": 24,
                                "native_damage_events": 1,
                                "native_world_ticks": 1})
    monkeypatch.setattr(gate, "_source_native_world_parity",
                        lambda *args: "real native/world mismatch")
    with pytest.raises(ValueError, match="P73_FINALIST_NATIVE_WORLD_PARITY"):
        gate._paid_stochastic_finalist(producer, tmp_path / "engine", source, 15)


def test_p73_early_stochastic_feedback_is_paid_and_preserves_cold_diversity():
    """Search uses only paid source-native+2D contenders, not reference seeds."""
    due = gate._p73_early_rerank_due
    assert not due(119.9, 0)
    assert due(120.0, 0)
    assert not due(139.9, 1)
    assert due(140.0, 1)
    assert due(220.0, 5)
    assert not due(220.0, 6)
    assert not due(240.0, 0)

    balanced_req = {"raid": "balanced paid contender"}
    stochastic_req = {"raid": "stochastic paid contender"}
    balanced = [(900.0, balanced_req)]
    # The second value is a real paid world receipt; the fourth is the
    # untouched source-legal request, not the seed-mutated rerank request.
    stochastic = [(750.0, {"world_mean_dps": 750.0}, "source-sha",
                   stochastic_req, 720.0)]
    assert gate._p73_paid_parent_pool(balanced, stochastic, 1) == [
        (750.0, stochastic_req)]
    assert gate._p73_paid_parent_pool(balanced, stochastic, 3) is balanced
    assert gate._p73_paid_parent_pool(balanced, [], 1) is balanced

    class PickFirst:
        @staticmethod
        def choice(options):
            return options[0]
    parent = gate._p73_paid_parent_pool(balanced, stochastic, 1)
    assert gate._paid_elite_choice(parent, PickFirst(), 1) is stochastic_req
    assert gate._paid_elite_choice(parent, PickFirst(), 5) is None
