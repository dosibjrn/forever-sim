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


def test_reused_manifest_refusals_only_spend_matching_level_budget(tmp_path):
    """L30 native refusals cannot starve an independent L20 sample."""
    binary = tmp_path / "selected-rust"
    binary.write_bytes(b"same selected Rust binary")
    manifest = tmp_path / "multi-level-frontier.json"
    manifest.write_text(json.dumps({
        "entries": [],
        "refusals": [
            {"candidate_id": "L30_rejected", "status": "NATIVE_PREPARE_REFUSED",
             "native_refusal": "Rust rejected level 30 proposal", "level": 30,
             "parent_source_sha256": None},
            {"candidate_id": "L20_rejected", "status": "NATIVE_PREPARE_REFUSED",
             "native_refusal": "Rust rejected level 20 proposal", "level": 20,
             "parent_source_sha256": None},
        ],
    }))
    rows = evaluate_request(
        {**_request(), "budget": 1}, manifest=manifest, binary=binary,
        target_hp=400, scorer_command=["native-scorer"],
        artifact_dir=tmp_path / "paid",
        run_command=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("source-native refusal cannot invoke paid combat")),
    )
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == "L20_rejected"
    assert rows[0]["native_refusal"] == "Rust rejected level 20 proposal"
    assert not (tmp_path / "paid").exists()


def test_reused_manifest_refusals_only_spend_matching_parent_budget(tmp_path):
    """One native parent's refusals cannot exhaust another continuing beam."""
    binary = tmp_path / "selected-rust"
    binary.write_bytes(b"same selected Rust binary")
    manifest = tmp_path / "two-parents.json"
    manifest.write_text(json.dumps({
        "entries": [],
        "refusals": [
            {"candidate_id": "different_parent", "status": "NATIVE_PREPARE_REFUSED",
             "level": 30, "parent_source_sha256": "b" * 64},
            {"candidate_id": "matching_parent", "status": "NATIVE_PREPARE_REFUSED",
             "level": 30, "parent_source_sha256": "a" * 64},
        ],
    }))
    rows = evaluate_request(
        {**_request(), "level": 30, "budget": 1,
         "parent": {"level": 20, "source_request_sha256": "a" * 64}},
        manifest=manifest, binary=binary, target_hp=400,
        scorer_command=["native-scorer"], artifact_dir=tmp_path / "paid",
        run_command=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("refusals must not invoke native paid combat")),
    )
    assert [row["candidate_id"] for row in rows] == ["matching_parent"]
    assert not (tmp_path / "paid").exists()


def test_live_native_frontier_emits_refusal_scope_for_reusable_manifest(tmp_path):
    """The actual Rust prepare producer must label refusals for later reuse."""
    import subprocess
    from tools.wf_warlock_native_source_frontier import produce_frontier

    binary = tmp_path / "native-engine"
    binary.write_bytes(b"native binary")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "level": 20,
            "talentsString": "1-0-0",
        }]}]},
        "encounter": {"targets": [{"level": 20}]},
    }))

    def native(cmd, **kwargs):
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
                "level": 20, "talents": {"status": "ok", "trees": [
                    {"talents": [{"index": 0, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                ]},
            }))
        assert cmd[1] == "prepare"
        return subprocess.CompletedProcess(cmd, 2, stderr="Rust native prepare refused")

    result = produce_frontier(
        {**_request(), "budget": 1},
        binary=binary, seed_source=seed, out=tmp_path / "frontier",
        runner=native,
    )
    assert result["entries"] == []
    assert result["level"] == 20
    assert result["parent_source_sha256"] is None
    assert len(result["refusals"]) == 1
    assert result["refusals"][0]["level"] == 20
    assert result["refusals"][0]["parent_source_sha256"] is None
    assert "Rust native prepare refused" in result["refusals"][0]["native_refusal"]
