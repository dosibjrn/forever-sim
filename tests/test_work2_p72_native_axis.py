"""Forever-owned P7.2 native scorer dispatch, not a Warcraft rules audit."""
from pathlib import Path
from types import SimpleNamespace
import copy

from tools import wf_gate_p7_2_live as p72


def _source():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassDruid",
            "talentsString": "0-0-0",
            "equipment": {"items": [{"id": 101}]},
            "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": 5176}}}]},
            "distanceFromTarget": 20.0,
        }]}]},
        "encounter": {"targets": [{"level": 63}]},
        "simOptions": {"iterations": 1000, "randomSeed": "1179706472"},
    }


def _run(monkeypatch, *, mutation_result, native_result=None, native_error=None):
    original = _source()
    observed = []

    def score(_binary, request, iterations, *, rng_mode):
        observed.append((copy.deepcopy(__import__("json").loads(request.read_text())),
                         iterations, rng_mode))
        if native_error is not None:
            raise RuntimeError(native_error)
        return native_result or {"iterations": 3, "native_dps": 22.0}

    mutation = SimpleNamespace(mutate_apl=lambda *args, **kwargs: mutation_result)
    production = SimpleNamespace(native_source_control=score)
    monkeypatch.setattr(
        p72, "_pinned_source_runtime",
        lambda *args, **kwargs: (original, {
            "reference_dps": 20.0,
            "selected_engine_revision": "selected-rust-sha",
        }, Path("/selected/forever-engine")))
    monkeypatch.setattr(
        p72, "_source_module",
        lambda _path, name: mutation if "mutator" in name else production)
    monkeypatch.delenv("FOREVER_P7_FULL_SOURCE_SEARCH", raising=False)
    result = p72.run_live(Path("/not-needed"), "druid", 60, spec="balance")
    return original, observed, result


def test_distinct_apl_pays_selected_native_only_and_passes_without_retired_holdouts(monkeypatch):
    changed = [{"action": {"castSpell": {"spellId": 8921}}}]
    original, observed, result = _run(monkeypatch, mutation_result=changed)
    assert result["status"] == "PASS"
    assert result["production_engine"] == "pinned_mythicsim_rust_native"
    assert result["source_legal_cold_candidates_paid"] == 1
    assert result["winner_native_dps"] == 22.0
    assert result["source_fixed_gear_and_talents"] is True
    assert result["runtime_proof"]["executed"] is True
    assert result["independent_300s_search_completed"] is False
    assert "frozen_stochastic_iterations" not in result
    assert len(observed) == 1
    candidate, iterations, mode = observed[0]
    assert (iterations, mode) == (3, "balanced")
    assert candidate["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"] == changed
    assert candidate["raid"]["parties"][0]["players"][0]["equipment"] == (
        original["raid"]["parties"][0]["players"][0]["equipment"])
    assert candidate["raid"]["parties"][0]["players"][0]["talentsString"] == (
        original["raid"]["parties"][0]["players"][0]["talentsString"])


def test_unchanged_apl_cannot_claim_paid_native_candidate(monkeypatch):
    unchanged = _source()["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
    _, observed, result = _run(monkeypatch, mutation_result=unchanged)
    assert result["status"] == "FAIL"
    assert result["source_legal_cold_candidates_paid"] == 0
    assert observed == []


def test_native_refusal_does_not_claim_p7_2_pass(monkeypatch):
    _, observed, result = _run(
        monkeypatch,
        mutation_result=[{"action": {"castSpell": {"spellId": 8921}}}],
        native_error="NATIVE_SOURCE_CONTROL_FAILED exit=5")
    assert len(observed) == 1
    assert result["status"] == "FAIL"
    assert result["source_legal_cold_candidates_paid"] == 0
    assert "NATIVE_SOURCE_CONTROL_FAILED" in result["cold_candidate_failures"][0]
