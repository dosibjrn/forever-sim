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
        mutate_talent_string=lambda parent, rng: "mutated-proposal",
        lower_one_rank_neighbors=lambda reference: ["5532220115501351--504"])
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
    base["raid"]["parties"][0]["players"][0].update({"class": "ClassDruid"})
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *args, **kwargs: (base, {"reference_dps": 728.19}, tmp_path / "binary"))
    serial = iter(range(8))
    proposals = SimpleNamespace(
        cold_talent_string=lambda template, rng: "cold-" + str(next(serial)),
        mutate_talent_string=lambda parent, rng: "mutated-" + str(next(serial)),
        lower_one_rank_neighbors=lambda reference: [])
    monkeypatch.setattr(gate, "native_talent_proposals", proposals)
    statuses = iter(("INVALID", "UNSUPPORTED", "ERROR", "INVALID",
                     "UNSUPPORTED", "ERROR", "INVALID", "UNSUPPORTED"))
    calls = []

    class NativeOutcome(RuntimeError):
        def __init__(self, status):
            self.status = status
            super().__init__("native outcome " + status)

    def native(binary, path, iterations, *, rng_mode):
        calls.append((iterations, rng_mode, path.read_text()))
        raise NativeOutcome(next(statuses))

    def world(*args, **kwargs):
        pytest.fail("native P7.3 never calls the 2D world")

    monkeypatch.setattr(
        gate, "_source_module",
        lambda path, name: SimpleNamespace(native_source_control=native, run=world))
    report = gate.run_live(tmp_path, "druid", 60, spec="unrestricted")
    assert len(calls) == 8
    assert all((n, mode) == (3, "balanced") for n, mode, _ in calls)
    assert report["native_invalid_candidates"] == 3
    assert report["native_unsupported_candidates"] == 3
    assert report["native_execution_errors"] == 2
    assert report["source_legal_cold_candidates_paid"] == 0
    assert report["status"] == "FAIL"
    assert report["reasons"] == ["P7_3_NO_NATIVE_PAID_CHANGED_TALENT_CANDIDATE"]

def test_saved_identity_mismatch_fails_closed(tmp_path):
    report = gate.run_live(tmp_path, "priest", 60, spec="holy")
    assert report["status"] == "BLOCKED"
    assert "P7_3_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT" in report["reasons"]


def test_p73_changed_talent_is_paid_directly_by_native_without_retired_gates(
        monkeypatch, tmp_path):
    base = _reference()
    base["raid"]["parties"][0]["players"][0].update({"class": "ClassDruid"})
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *args, **kwargs: (base, {
            "reference_dps": 728.19, "selected_engine_revision": "selected-rust",
            "selected_reference_profile": "balance"}, tmp_path / "binary"))
    proposals = SimpleNamespace(
        cold_talent_string=lambda template, rng: "cold-proposal",
        mutate_talent_string=lambda parent, rng: "mutated-proposal",
        # The provider probes minimal native-decided rank edits first. Keep
        # this transport mock aligned with the genuine proposal interface.
        lower_one_rank_neighbors=lambda reference: ["5532220115501351--504"])
    monkeypatch.setattr(gate, "native_talent_proposals", proposals)
    calls = []

    def native(binary, path, n, *, rng_mode):
        calls.append((n, rng_mode, path.read_text()))
        return {"iterations": 3, "native_dps": 729.0}

    def world(*args, **kwargs):
        pytest.fail("P7.3 has no P7-only 2D, stochastic, or 300s requirement")

    monkeypatch.setattr(
        gate, "_source_module",
        lambda path, name: SimpleNamespace(native_source_control=native, run=world))
    report = gate.run_live(tmp_path, "druid", 60, spec="unrestricted")
    assert len(calls) == 1
    assert calls[0][:2] == (3, "balanced")
    import json
    paid = json.loads(calls[0][2])["raid"]["parties"][0]["players"][0]
    original = base["raid"]["parties"][0]["players"][0]
    assert paid["talentsString"] == "5532220115501351--504"
    assert paid["equipment"] == original["equipment"]
    assert paid["rotation"] == original["rotation"]
    assert report["status"] == "PASS"
    assert report["winner_native_dps"] == 729.0
    assert report["source_original_talents"] == original["talentsString"]
    assert report["cold_winner_talents"] == "5532220115501351--504"
    assert report["checkpoint_spec"] == "unrestricted"
    assert report["reference_profile"] == "balance"
    assert report["native_source_revision"] == "selected-rust"
    assert report["source_legal_cold_candidates_paid"] == 1
    assert report["independent_300s_search_completed"] is False
    assert "frozen_stochastic_iterations" not in report

def test_p73_invalid_full_search_flag_blocks_without_running(monkeypatch, tmp_path):
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "maybe")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *a, **kwargs: (_reference(), {"reference_dps": 728.19},
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


def test_p73_unchanged_talents_never_credit_a_native_gate(monkeypatch, tmp_path):
    base = _reference()
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *a, **kwargs: (base, {"reference_dps": 728.19}, tmp_path / "binary"))
    reference = base["raid"]["parties"][0]["players"][0]["talentsString"]
    monkeypatch.setattr(gate, "native_talent_proposals", SimpleNamespace(
        cold_talent_string=lambda template, rng: reference,
        mutate_talent_string=lambda parent, rng: reference,
        lower_one_rank_neighbors=lambda parent: []))
    def native(*args, **kwargs):
        pytest.fail("unchanged talent string must never be paid or credited")
    monkeypatch.setattr(gate, "_source_module", lambda *args: SimpleNamespace(
        native_source_control=native))
    report = gate.run_live(tmp_path, "druid", 60, spec="unrestricted")
    assert report["status"] == "FAIL"
    assert report["cold_unique_source_requests"] == 0
    assert report["source_legal_cold_candidates_paid"] == 0


def test_minimal_rank_neighbors_are_generic_source_edits_not_legality_checks():
    original = "5532220115501351--505"
    variants = native_talent_proposals.lower_one_rank_neighbors(original)
    assert variants
    assert len(variants) == sum(c != "0" for c in original if c.isdigit())
    assert len(set(variants)) == len(variants)
    assert all(sum(map(int, (c for c in s if c.isdigit()))) ==
               sum(map(int, (c for c in original if c.isdigit()))) - 1
               for s in variants)
    assert all(v.count("-") == original.count("-") for v in variants)


def test_structured_native_talent_refusal_is_not_a_python_engine_error():
    refusal = RuntimeError(
        'NATIVE_SOURCE_CONTROL_FAILED exit=5 request_sha256=abc '
        'output={"prepared":false,"refusal":{"code":"talents",'
        '"reason":"druid talent rank rejected by native"}}')
    assert gate._native_refusal(refusal) == (
        "INVALID", "NATIVE_TALENTS:druid talent rank rejected by native")
    assert gate._native_refusal(RuntimeError("native process crashed")) == (
        "ERROR", "native process crashed")



def test_one_point_transfers_keep_budget_without_python_legality():
    source = "5532220115501351--505"
    variants = native_talent_proposals.one_point_transfer_neighbors(
        source, limit=16)
    assert len(variants) == len(set(variants)) == 16
    # Proposal order is a search heuristic, not a native legality contract.
    # The bounded stream must reach both same-tree and cross-tree edits.
    source_tree_points = [sum(int(c) for c in tree) for tree in source.split("-")]
    proposed_tree_points = [
        [sum(int(c) for c in tree) for tree in variant.split("-")]
        for variant in variants
    ]
    assert any(points == source_tree_points for points in proposed_tree_points)
    assert any(points != source_tree_points for points in proposed_tree_points)
    assert all(len(v) == len(source) for v in variants)
    for candidate in variants:
        deltas = [int(after) - int(before)
                  for before, after in zip(source, candidate)
                  if before != "-" and after != "-" and before != after]
        assert sorted(deltas) == [-1, 1]
        assert candidate.count("-") == source.count("-")
        assert sum(int(c) for c in candidate if c.isdigit()) == 51


def test_p73_native_transfer_follows_rank_refusal(monkeypatch, tmp_path):
    """After native refuses a simple rank removal, try a budget-fixed neighbor."""
    import json

    base = _reference()
    monkeypatch.setenv("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    monkeypatch.setattr(
        gate, "_pinned_source_runtime",
        lambda *args, **kw: (base, {"reference_dps": 728.19},
                             tmp_path / "binary"))

    class Proposals:
        @staticmethod
        def lower_one_rank_neighbors(parent):
            return ["5532220115501351--504"]

        @staticmethod
        def one_point_transfer_neighbors(parent):
            return ["5532220115501351--514"]

        @staticmethod
        def mutate_talent_string(*args):
            pytest.fail("point-preserving source candidate should be paid first")

        @staticmethod
        def cold_talent_string(*args):
            pytest.fail("point-preserving source candidate should be paid first")

    monkeypatch.setattr(gate, "native_talent_proposals", Proposals)
    native_requests = []

    def native_score(binary, path, iterations, *, rng_mode):
        candidate = json.loads(path.read_text())
        native_requests.append(candidate["raid"]["parties"][0]["players"][0])
        assert iterations == 3 and rng_mode == "balanced"
        if len(native_requests) == 1:
            raise RuntimeError(
                'NATIVE_SOURCE_CONTROL_FAILED exit=5 request_sha256=abc '
                'output={"prepared":false,"refusal":{"code":"talents",'
                '"reason":"refused by selected native"}}')
        return {"iterations": 3, "native_dps": 712.5}

    monkeypatch.setattr(
        gate, "_source_module",
        lambda *args: SimpleNamespace(native_source_control=native_score))
    result = gate.run_live(tmp_path, "druid", 60)
    assert result["status"] == "PASS"  # transport test, not real paid evidence
    assert result["native_invalid_candidates"] == 1
    assert result["native_execution_errors"] == 0
    assert result["point_preserving_delta_proposals"] == 1
    assert result["source_legal_cold_candidates_paid"] == 1
    assert result["cold_winner_talents"] == "5532220115501351--514"
    assert [p["talentsString"] for p in native_requests] == [
        "5532220115501351--504", "5532220115501351--514"]
    reference = base["raid"]["parties"][0]["players"][0]
    assert all(p["equipment"] == reference["equipment"] and
               p["rotation"] == reference["rotation"] for p in native_requests)


def test_bounded_native_talent_transfers_explore_within_and_across_trees():
    """Search diversity only: these are not Python legality decisions."""
    original = "10-10-10"
    proposals = native_talent_proposals.one_point_transfer_neighbors(
        original, limit=4)
    assert len(proposals) == 4
    assert len(set(proposals)) == 4
    original_tree_points = [sum(map(int, part)) for part in original.split("-")]
    tree_points = [[sum(map(int, part)) for part in value.split("-")]
                   for value in proposals]
    assert any(points == original_tree_points for points in tree_points)
    assert any(points != original_tree_points for points in tree_points)
    assert all(sum(points) == sum(original_tree_points) for points in tree_points)
    assert native_talent_proposals.one_point_transfer_neighbors(
        original, limit=0) == []
    with pytest.raises(ValueError, match="TALENT_PROPOSAL_LIMIT_NEGATIVE"):
        native_talent_proposals.one_point_transfer_neighbors(original, limit=-1)
