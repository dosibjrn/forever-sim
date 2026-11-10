"""Guide handoff from already paid native receipts; no native or M1 replay."""
import copy
import json
from pathlib import Path

import pytest

from tools import wf_warlock_paid_family_guide as guide


RUN = "https://github.com/dosibjrn/forever-sim/actions/runs/42836075370"
ARTIFACT = 13774186358


def _comparison():
    def measured(index, family, elapsed):
        return {
            "index": index, "status": "MEASURED_NATIVE_100",
            "dominant_talent_tree_index": family,
            "tree_index": family, "talents": f"{family}-native-talents",
            "targets_killed": 100, "native_world_ack": True,
            "paid_native_recovery": True, "elapsed_seconds": elapsed,
            "native_observation_id": f"real-native-{index}",
            "original_source_sha256": str(index) * 64,
            "executed_source_sha256": str(index + 3) * 64,
            "native_summary": f"candidate_{index:02d}/native_l47/summary.json",
            "requires_talent_respec_from_paid_source": family != 2,
            "final_hp": 500, "final_mana": 400,
        }
    return {
        "kind": "warlock_native_world_finalist_comparison_v1",
        "status": "MEASURED_CROSS_TREE_100", "level": 47,
        "native_binary_sha256": "a" * 64,
        "paid_predecessor": {"observation_id": "paid-real-L46"},
        "talent_respec_cost_measured": False,
        "m1_recording_performed": False,
        "distinct_build_families_compared": True,
        "pending_candidate_indexes": [],
        "candidates": [measured(1, 0, 885.4),
                       measured(2, 1, 951.7),
                       measured(3, 2, 777.7)],
        "world_winner": {"candidate_index": 3, "elapsed_seconds": 777.7},
    }


def _build(receipt):
    return guide.build(receipt, source_run_url=RUN, artifact_id=ARTIFACT)


def test_paid_l47_guide_handoff_uses_real_100_mob_elapsed_and_receipt_links(tmp_path):
    payload = _comparison()
    comparison = tmp_path / "original-comparison.json"
    comparison.write_text(json.dumps(payload))
    out = tmp_path / "guide-family.json"
    result = guide.publish(comparison=comparison, source_run_url=RUN,
                           artifact_id=ARTIFACT, out=out)
    assert json.loads(out.read_text()) == result
    assert result["status"] == "MEASURED_BOUNDED_FAMILY_COMPARISON"
    assert result["bounded_fastest_family"] == "Destruction"
    assert [row["family"] for row in result["measurements"]] == [
        "Destruction", "Affliction", "Demonology"]
    assert [row["seconds_per_mob"] for row in result["measurements"]] == [
        7.777, 8.854, 9.517]
    assert result["original_artifact_id"] == ARTIFACT
    assert result["source_run_url"] == RUN
    assert result["measurements"][0]["native_observation_id"] == "real-native-3"
    assert result["measurements"][0]["source_request_sha256"] == "3" * 64
    assert result["measurements"][0]["executed_source_sha256"] == "6" * 64
    assert result["measurements"][0]["requires_respec_from_paid_predecessor"] is False
    assert result["talent_respec_cost_measured"] is False
    assert result["continuous_level_route_measured"] is False
    assert result["full_route_optimum_measured"] is False
    assert result["stat_weights_measured"] is False


def test_pending_native_world_is_never_published_as_comparable_family():
    comparison = _comparison()
    comparison["status"] = "PARTIAL_WORLD_PAID"
    comparison["candidates"][1]["status"] = "PENDING_UNPAID"
    comparison["pending_candidate_indexes"] = [2]
    comparison["world_winner"] = None
    result = _build(comparison)
    assert result["status"] == "PROVISIONAL_NO_COMPARABLE_FAMILY_GUIDE"
    assert result["measurements"] == []
    assert result["bounded_fastest_family"] is None
    assert 2 in result["other_or_unpaid_candidate_indexes"]


def test_incomparable_native_world_is_never_published_as_winner():
    comparison = _comparison()
    comparison["status"] = "INCOMPARABLE_NATIVE_SCENARIOS"
    comparison["world_winner"] = None
    result = _build(comparison)
    assert result["status"] == "PROVISIONAL_NO_COMPARABLE_FAMILY_GUIDE"
    assert result["measurements"] == []


def test_equal_paid_100_mob_times_report_tie_not_invented_winner():
    comparison = _comparison()
    comparison["candidates"][0]["elapsed_seconds"] = 777.7
    comparison["status"] = "MEASURED_CROSS_TREE_TIE_100"
    comparison["world_winner"] = None
    result = _build(comparison)
    assert result["bounded_fastest_family"] is None
    assert result["tied_fastest_families"] == ["Affliction", "Destruction"]


@pytest.mark.parametrize("tamper", [
    lambda r: r["candidates"][0].pop("native_observation_id"),
    lambda r: r["candidates"][1].update(native_world_ack=False),
    lambda r: r["candidates"][2].update(targets_killed=99),
    lambda r: r["candidates"][0].update(executed_source_sha256=None),
    lambda r: r["candidates"][1].update(elapsed_seconds=float("nan")),
])
def test_paid_guide_rejects_incomplete_receipt_provenance(tamper):
    receipt = _comparison()
    tamper(receipt)
    with pytest.raises(ValueError, match="native-paid receipt provenance"):
        _build(receipt)


def test_paid_guide_rejects_wrong_winner_and_unsigned_run_identity():
    receipt = _comparison()
    receipt["world_winner"]["candidate_index"] = 1
    with pytest.raises(ValueError, match="winner claim"):
        _build(receipt)
    receipt = _comparison()
    with pytest.raises(ValueError, match="GitHub Actions run URL"):
        guide.build(receipt, source_run_url="https://example.com/run/777",
                    artifact_id=ARTIFACT)


def test_checked_in_l47_native_paid_guide_has_original_receipt_attribution():
    """Player guide can consume the actual original paid data, not a fabricated score."""
    path = (Path(__file__).resolve().parents[1] / "data" / "warlock"
            / "native_l47_paid_family_guide.json")
    result = json.loads(path.read_text())
    assert result["kind"] == "warlock_paid_family_guide_input_v1"
    assert result["status"] == "MEASURED_BOUNDED_FAMILY_COMPARISON"
    assert result["actor_level"] == 47
    assert result["source_run_url"] == RUN
    assert result["original_artifact_id"] == ARTIFACT
    assert result["selected_native_binary_sha256"] == (
        "133c96ba50b7589036e062e18a3315e28ac2562064cb99e96d501fc4ee054458")
    assert [(x["family"], x["seconds_per_mob"]) for x in result["measurements"]] == [
        ("Destruction", 7.777), ("Affliction", 8.854), ("Demonology", 9.517)]
    assert result["bounded_fastest_family"] == "Destruction"
    assert all(x["native_observation_id"] and x["native_summary"]
               and len(x["executed_source_sha256"]) == 64
               for x in result["measurements"])
    assert result["talent_respec_cost_measured"] is False
    assert result["continuous_level_route_measured"] is False
    assert result["full_route_optimum_measured"] is False
    assert result["m1_recording_performed"] is False
