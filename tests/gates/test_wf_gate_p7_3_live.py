"""P7.3 native-decided talent proposals, never a synthetic PASS."""
import copy
import random
from types import SimpleNamespace
import pytest
from src.engine_client import native_talent_proposals
from tools import wf_gate_p7_3_live as gate


def _reference():
    return {"raid": {"parties": [{"players": [{
        "talentsString": "5532220115501351--505", "equipment": {"items": [{"id": 17}]},
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": 1}}}]},
    }]}]}}


def test_cold_talent_discovery_preserves_full_gear_apl_and_original():
    original = _reference()
    baseline = copy.deepcopy(original)
    proposals = SimpleNamespace(
        cold_talent_string=lambda template, rng: "independent-proposal",
        mutate_talent_string=lambda parent, rng: "mutated-proposal")
    new = gate._cold_talents(original, random.Random(647003), proposals)
    assert new != original
    assert new["raid"]["parties"][0]["players"][0]["talentsString"] == "independent-proposal"
    assert new["raid"]["parties"][0]["players"][0]["rotation"] == baseline["raid"]["parties"][0]["players"][0]["rotation"]
    assert new["raid"]["parties"][0]["players"][0]["equipment"] == baseline["raid"]["parties"][0]["players"][0]["equipment"]
    assert original == baseline


def test_native_talent_proposals_preserve_format_budget_without_rank_rules():
    template = "5532220115501351--505"
    candidate = native_talent_proposals.cold_talent_string(
        template, random.Random(647003))
    assert [len(part) for part in candidate.split("-")] == [
        len(part) for part in template.split("-")]
    assert candidate.count("-") == template.count("-")
    assert sum(int(char) for char in candidate if char.isdigit()) == sum(
        int(char) for char in template if char.isdigit())

    class FirstChoice:
        @staticmethod
        def choice(values):
            return values[0]

        @staticmethod
        def randint(low, high):
            return low

    # Rank 9 is accepted as a proposal-format digit; native, not this helper,
    # decides whether any proposed rank is legal.
    moved = native_talent_proposals.mutate_talent_string("900--0", FirstChoice())
    assert moved == "810--0"
    assert sum(int(char) for char in moved if char.isdigit()) == 9
    assert max(int(char) for char in moved if char.isdigit()) == 8


def test_native_candidate_refusals_are_classified_without_world_fallback(
        monkeypatch, tmp_path):
    base = _reference()
    base["raid"]["parties"][0]["players"][0].update({
        "class": "ClassDruid", "distanceFromTarget": 15})
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *args: (base, {"reference_dps": 728.19}, tmp_path / "binary"))
    proposals = SimpleNamespace(
        cold_talent_string=lambda template, rng: "proposal-" + str(next(counter)),
        mutate_talent_string=lambda parent, rng: "mutated-proposal")
    counter = iter(range(3))
    monkeypatch.setattr(gate, "native_talent_proposals", proposals)

    statuses = iter(("INVALID", "UNSUPPORTED", "ERROR"))
    calls = []

    class NativeOutcome(RuntimeError):
        def __init__(self, status):
            self.status = status
            super().__init__("native outcome " + status)

    def native(binary, path, iterations, *, rng_mode):
        calls.append((iterations, rng_mode, path.read_text()))
        raise NativeOutcome(next(statuses))

    def world(*args, **kwargs):
        pytest.fail("native refusal/error must not reach the 2D world runner")

    monkeypatch.setattr(
        gate, "_source_module",
        lambda path, name: SimpleNamespace(native_source_control=native, run=world))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert len(calls) == 3
    assert report["native_invalid_candidates"] == 1
    assert report["native_unsupported_candidates"] == 1
    assert report["native_unscored_candidates"] == 0
    assert report["native_execution_errors"] == 1
    assert report["world_execution_errors"] == 0
    assert report["native_scored_candidates_paid"] == 0
    assert report["status"] == "FAIL"


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
    proposals = SimpleNamespace(
        cold_talent_string=lambda template, rng: "cold-native-proposal",
        mutate_talent_string=lambda parent, rng: "mutated-native-proposal")
    monkeypatch.setattr(p73, "native_talent_proposals", proposals)
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
        p73, "_source_module", lambda path, name: producer)

    from tools.wf_gate import _run_live_gate
    report = _run_live_gate(tmp_path, "druid", 60, "balance", "P7.3", "")
    assert [(kind, n, mode) for kind, n, mode, _ in calls] == [
        ("native", 3, "balanced"), ("world", 3, "balanced"),
        ("native", 1000, "stochastic"), ("world", 1000, "stochastic")]
    assert json.loads(calls[0][3]) == json.loads(calls[3][3])
    assert report["cold_unique_source_requests"] == 1
    assert report["winner_selection"] == "best_balanced_live_screen"
    assert report["search_rng_mode"] == "balanced"
    assert report["paid_stochastic_finalists"] == 0
    assert report["stochastic_parent_proposals"] == 0
    # Real gate receipt exposes which talent build was frozen; a request
    # hash alone cannot distinguish unchanged-effective-rank hypotheses.
    assert report["source_original_talents"] == "5532220115501351--505"
    assert report["cold_winner_talents"] == "cold-native-proposal"
    assert report["native_scored_candidates_paid"] == 1
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


def test_p73_paid_elite_mutates_native_paid_parent_not_saved_reference():
    """Only a candidate already paid by native+2D can guide local proposals."""
    base = _reference()
    original = copy.deepcopy(base)
    elite = copy.deepcopy(base)
    elite["raid"]["parties"][0]["players"][0]["talentsString"] = "paid-best"
    calls = []

    class Proposals:
        @staticmethod
        def cold_talent_string(template, rng):
            calls.append(("cold", template))
            return "cold-proposal"

        @staticmethod
        def mutate_talent_string(parent, rng):
            calls.append(("mutate", parent))
            return "mutated-proposal"

    cold = gate._cold_talents(base, random.Random(1), Proposals)
    assert calls == [("cold", "5532220115501351--505")]
    assert cold["raid"]["parties"][0]["players"][0]["talentsString"] == "cold-proposal"
    calls.clear()
    improved = gate._cold_talents(
        base, random.Random(1), Proposals, elite=elite)
    assert calls == [("mutate", "paid-best")]
    assert improved["raid"]["parties"][0]["players"][0]["talentsString"] == "mutated-proposal"
    assert base == original
    assert elite["raid"]["parties"][0]["players"][0]["talentsString"] == "paid-best"


def test_p73_paid_elite_rejects_fixed_gear_or_apl_change():
    base = _reference()
    class Proposals:
        @staticmethod
        def cold_talent_string(template, rng):
            raise AssertionError("must reject altered paid candidate first")

        @staticmethod
        def mutate_talent_string(parent, rng):
            raise AssertionError("must reject altered paid candidate first")

    for axis in ("equipment", "rotation"):
        elite = copy.deepcopy(base)
        elite["raid"]["parties"][0]["players"][0][axis] = {"illegal": True}
        with pytest.raises(ValueError, match="P73_PAID_ELITE_CHANGED_FIXED_DIMENSIONS"):
            gate._cold_talents(base, random.Random(3), Proposals, elite=elite)


def test_p73_local_full_draw_uses_paid_target_as_budget_template():
    base = _reference()
    elite = copy.deepcopy(base)
    elite["raid"]["parties"][0]["players"][0]["talentsString"] = "paid-best"
    calls = []

    class Proposals:
        @staticmethod
        def cold_talent_string(template, rng):
            calls.append(template)
            return "cold-paid-budget"

        @staticmethod
        def mutate_talent_string(parent, rng):
            raise AssertionError("high RNG must choose local full draw")

    class HighRandom(random.Random):
        def random(self):
            return 0.99

    result = gate._cold_talents(
        base, HighRandom(8), Proposals, elite=elite)
    assert calls == ["paid-best"]
    assert result["raid"]["parties"][0]["players"][0]["talentsString"] == "cold-paid-budget"


def test_p73_paid_elite_archive_can_choose_other_scored_winner():
    """Reproduced search issue: local mutations must not only see rank #1."""
    class ChooseLast:
        @staticmethod
        def choice(options):
            return options[-1]

    top = {"source": "paid-best", "talentsString": "a"}
    other = {"source": "paid-second", "talentsString": "b"}
    from tools.wf_gate_p7_3_live import _paid_elite_choice
    # These entries are deliberately already native+2D-paid; caller appends
    # them only AFTER native/world parity and a valid score.
    elites = [(900.0, top), (800.0, other)]
    assert _paid_elite_choice(elites, ChooseLast(), 2) is other
    assert _paid_elite_choice(elites, ChooseLast(), 5) is None
    assert _paid_elite_choice([], ChooseLast(), 2) is None


def test_p73_paid_elite_archive_caps_native_paid_pool_to_top_18():
    from tools.wf_gate_p7_3_live import _paid_elite_choice

    class PickLast:
        @staticmethod
        def choice(options):
            assert len(options) == 18
            return options[-1]

    elites = [(float(100-i), {"rank": i}) for i in range(22)]
    assert _paid_elite_choice(elites, PickLast(), 1)["rank"] == 17
