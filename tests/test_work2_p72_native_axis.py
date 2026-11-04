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


def test_public_gate_receipt_keeps_real_native_score_and_changed_apl(
        monkeypatch, capsys):
    import json
    from tools import wf_gate
    changed = [{"action": {"castSpell": {"spellId": 8921}}}]
    report = {
        "status": "PASS",
        "reasons": [],
        "runtime_proof": {"executed": True, "engine_revision": "selected-rust",
                          "source_revision": "paid-candidate",
                          "run_id": "native-paid-1"},
        "production_engine": "pinned_mythicsim_rust_native",
        "native_source_revision": "selected-rust",
        "source_request_raw_sha256": "source-sha",
        "source_legal_cold_candidates_paid": 1,
        "cold_winner_request_sha256": "paid-candidate",
        "winner_native_dps": 22.0,
        "original_apl_hash": "original-hash",
        "cold_winner_apl": changed,
        "source_fixed_gear_and_talents": True,
        "reference_profile": "balance",
        "checkpoint_spec": "unrestricted",
        "selected_validation": "3_native_balanced_fights_per_distinct_apl",
    }
    monkeypatch.setattr(wf_gate, "_run_live_gate", lambda *args: report)
    assert wf_gate.main(["--class", "druid", "--level", "60",
                         "--spec", "unrestricted", "--gate", "P7.2"]) == 0
    result = json.loads(capsys.readouterr().out)
    row = result["results"][0]
    assert row["winner_native_dps"] == 22.0
    assert row["cold_winner_apl"] == changed
    assert row["source_fixed_gear_and_talents"] is True
    assert row["cold_winner_request_sha256"] == "paid-candidate"
    assert row["reference_profile"] == "balance"
    assert row["checkpoint_spec"] == "unrestricted"

def test_p72_tries_reference_policy_mutation_then_cold_candidates(monkeypatch):
    """A P7.2 axis probe need not rebuild a random cold policy to find a
    native-legal change; failed/no-op local proposals still reach cold search.
    """
    import json

    baseline = _source()
    source_apl = baseline["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
    changed = [{"action": {"castSpell": {"spellId": 8921}}}]
    attempts = []
    scored = []

    def mutate(actions, source_actions, _rng, *, cold):
        attempts.append((copy.deepcopy(actions), cold))
        assert source_actions == source_apl
        # The first local proposal happens to be a no-op. The next local
        # proposal is distinct but refused; the cold candidate is paid.
        if len(attempts) == 1:
            return copy.deepcopy(source_apl)
        return changed if cold else [{"action": {"castSpell": {"spellId": 1126}}}]

    def native(_binary, request_path, iterations, *, rng_mode):
        request = json.loads(request_path.read_text())
        policy = request["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
        scored.append(policy)
        assert iterations == 3 and rng_mode == "balanced"
        if policy[0]["action"]["castSpell"]["spellId"] == 1126:
            raise RuntimeError("NATIVE_REFUSAL")
        return {"iterations": 3, "native_dps": 25.0}

    monkeypatch.setattr(p72, "_pinned_source_runtime",
                        lambda *args, **kwargs: (
                            baseline, {"reference_dps": 20.0,
                                       "selected_engine_revision": "selected-rust-sha"},
                            Path("/selected/forever-engine")))
    mutation = SimpleNamespace(mutate_apl=mutate)
    production = SimpleNamespace(native_source_control=native)
    monkeypatch.setattr(p72, "_source_module",
                        lambda _path, name: mutation if "mutator" in name else production)
    monkeypatch.delenv("FOREVER_P7_FULL_SOURCE_SEARCH", raising=False)

    report = p72.run_live(Path("/not-needed"), "druid", 60, spec="unrestricted")

    assert [is_cold for _, is_cold in attempts] == [False, False, True, True]
    assert attempts[0][0] == source_apl
    assert attempts[1][0] == source_apl
    assert attempts[2][0] is None
    assert report["status"] == "PASS"
    assert report["source_legal_cold_candidates_paid"] == 1
    assert report["winner_native_dps"] == 25.0
    assert report["checkpoint_spec"] == "unrestricted"
    assert len(scored) == 2
    assert scored[0] != scored[1]
    assert "NATIVE_REFUSAL" in report["cold_candidate_failures"][0]

