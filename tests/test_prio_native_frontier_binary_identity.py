"""Native frontier engine identity is a transport invariant, not a game rule."""
import hashlib
import json

import pytest

from tools.wf_warlock_native_range_scored_adapter import evaluate_request


def _request():
    return {
        "level": 20, "parent": None, "budget": 2, "mob_count": 3,
        "rng_mode": "balanced", "iterations": 1, "recover_to_full": True,
    }


def test_live_frontier_rejects_cross_engine_preparation_before_paid_scorer(tmp_path):
    binary = tmp_path / "selected-rust"
    binary.write_bytes(b"the selected scoring executable")
    manifest = tmp_path / "frontier.json"
    paid = tmp_path / "native-paid"

    def never_pay(*args, **kwargs):
        raise AssertionError("a wrong source binary must not trigger a paid call")

    for advertised in ("0" * 64, "not-a-sha", 42):
        manifest.write_text(json.dumps({
            "native_binary_sha256": advertised,
            "entries": [
                {"id": "a", "level": 20, "parent_source_sha256": None,
                 "prepared": "missing-a.json", "source_request": "missing-a.source.json"},
                {"id": "b", "level": 20, "parent_source_sha256": None,
                 "prepared": "missing-b.json", "source_request": "missing-b.source.json"},
            ],
        }))
        with pytest.raises(ValueError, match="NATIVE_FRONTIER_SCORER_ENGINE_MISMATCH"):
            evaluate_request(
                _request(), manifest=manifest, binary=binary, target_hp=400,
                scorer_command=["native-scorer"], artifact_dir=paid,
                run_command=never_pay,
            )
        assert not paid.exists()


def test_matching_frontier_binary_preserves_native_refusal_without_payment(tmp_path):
    binary = tmp_path / "selected-rust"
    binary.write_bytes(b"the selected scoring executable")
    manifest = tmp_path / "frontier.json"
    manifest.write_text(json.dumps({
        "native_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "entries": [],
        "refusals": [{
            "candidate_id": "source_000", "status": "NATIVE_PREPARE_REFUSED",
            "native_refusal": "Rust prepare rejected candidate",
        }],
    }))
    result = evaluate_request(
        _request(), manifest=manifest, binary=binary, target_hp=400,
        scorer_command=["native-scorer"], artifact_dir=tmp_path / "native-paid",
        run_command=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("native refusal must not pay a scorer")),
    )
    assert len(result) == 1
    assert result[0]["status"] == "NATIVE_PREPARE_REFUSED"
    assert result[0]["native_refusal"] == "Rust prepare rejected candidate"
    assert not (tmp_path / "native-paid").exists()
