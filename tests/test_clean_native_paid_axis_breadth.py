"""Clean: distinguish actually paid source-request axes from nominal candidate count.

These are fake transport receipts for Forever-owned reporting behavior only.
They are not MythicSim execution evidence or M1 acceptance.
"""
from __future__ import annotations

from src.v2.native_range_optimizer import (
    _retained_native_paid_axis_breadth,
    optimize,
    render_sampled_build_guide,
)


def _paid(level: int, identity: str, talent: str, apl_id: int) -> dict:
    return {
        "status": "MEASURED_NATIVE_FULLY_RECOVERED",
        "level": level, "mob_count": 2, "targets_killed": 2,
        "rng_mode": "balanced", "iterations": 1,
        "native_prepared": True, "native_world_ack": True,
        "source_request_sha256": identity * 64,
        "engine_binary_sha256": "f" * 64,
        "native_full_recovery_paid": True, "recover_to_full": True,
        "terminal_hp": 100.0, "terminal_max_hp": 100.0,
        "terminal_mana": 120.0, "terminal_max_mana": 120.0,
        "elapsed_seconds": 12.0, "terminal_recovery_seconds": 2.0,
        "talents": talent, "gear": {"items": [{"id": 101}]},
        "apl": {"priorityList": [{"id": apl_id}]}, "pet": None,
    }


def test_paid_request_axis_report_does_not_inflate_gear_or_pet_breadth():
    paid_a = _paid(20, "a", "100-0-0", 1)
    paid_b = _paid(20, "b", "010-0-0", 2)
    refused = {
        "status": "NATIVE_API_CANDIDATE_REFUSED",
        "level": 20, "native_prepared": False,
        "gear": {"items": [{"id": 888}]}, "pet": "Imp",
        "apl": {"priorityList": [{"id": 88}]},
    }
    unpaid = _paid(20, "c", "001-0-0", 3)
    unpaid["gear"] = {"items": [{"id": 999}]}
    unpaid["pet"] = "Felhunter"
    unpaid["native_full_recovery_paid"] = False

    def evaluate(*, level, **kwargs):
        if level == 20:
            return [paid_a, paid_b, refused, unpaid]
        return [{
            "status": "NATIVE_API_CANDIDATE_REFUSED",
            "level": level, "native_prepared": False,
            "gear": {"items": [{"id": 777}]}, "pet": "Voidwalker",
        }]

    result = optimize(
        20, 40, 20, 2, 14, evaluate=evaluate, mode="compatible",
    )
    assert result["status"] == "NO_COMPLETE_COMPATIBLE_SAMPLED_PATH"
    assert result["sampled_levels_completed"] == [20]
    assert result["competing_qualified_paths_by_level"]["20"] == 2
    assert len(result["rejected_native_attempts"]) == 3

    by_level = result["native_paid_request_axis_breadth_by_level"]
    assert by_level["20"] == {
        "verified_native_paid_requests": 2,
        "distinct_requested_talent_allocations": 2,
        "distinct_requested_gear_sets": 1,
        "distinct_requested_apls": 2,
        "distinct_requested_pet_values": 1,
        "uncompared_axes": ["gear", "pet"],
    }
    assert by_level["40"] == {
        "verified_native_paid_requests": 0,
        "distinct_requested_talent_allocations": 0,
        "distinct_requested_gear_sets": 0,
        "distinct_requested_apls": 0,
        "distinct_requested_pet_values": 0,
        "uncompared_axes": ["talents", "gear", "apl", "pet"],
    }


def test_paid_axis_breadth_rejects_disagreement_with_original_receipt():
    original = _paid(20, "a", "100-0-0", 1)
    tampered = _paid(20, "b", "010-0-0", 2)
    ranked_good = {
        **{key: original.get(key) for key in (
            "source_request_sha256", "engine_binary_sha256",
            "talents", "gear", "apl", "pet")},
        "receipt": original,
    }
    ranked_bad = {
        **{key: tampered.get(key) for key in (
            "source_request_sha256", "engine_binary_sha256",
            "talents", "gear", "apl", "pet")},
        "gear": {"items": [{"id": 999}]},
        "receipt": tampered,
    }
    result = {
        "mob_count": 2, "rng_mode": "balanced", "iterations": 1,
        "independent_level_rankings": {"20": [ranked_good, ranked_bad]},
    }
    assert _retained_native_paid_axis_breadth(result, 20) == (
        1, {"talents": 1, "gear": 1, "apl": 1, "pet": 1})


def test_refused_source_axes_keep_native_codes_without_becoming_paid_breadth():
    """Preserve Rust refusal diagnostics; never promote attempts to paid axes.

    Fake transport receipts test reporting only, not Rust execution.
    """
    paid = _paid(20, "a", "100-0-0", 1)
    refused_gear = {
        "status": "NATIVE_API_CANDIDATE_REFUSED",
        "candidate_id": "gear-L20", "level": 20,
        "native_prepared": False, "proposal_axis": "gear",
        "native_refusal_code": "native_item_not_eligible",
        "native_refusal": "refused sample gear proposal",
    }
    refused_pet = {
        "status": "NATIVE_API_CANDIDATE_REFUSED",
        "candidate_id": "pet-L20", "level": 20,
        "native_prepared": True, "proposal_axis": "pet",
        "native_refusal_code": "native_summon_unsupported",
        "native_refusal": "refused sample pet world",
    }

    # Compatible mode reserves search budget for later backward seeding;
    # six permits these three initial native attempts without overrun.
    result = optimize(
        20, 20, 1, 2, 6,
        evaluate=lambda **kwargs: [paid, refused_gear, refused_pet],
        mode="compatible",
    )
    assert result["status"] == "SAMPLED_COMPATIBLE_PATH_PROVISIONAL"
    assert result["native_candidates_examined"] == 3
    assert result["competing_qualified_paths_by_level"]["20"] == 1
    rejected = {row["candidate_id"]: row
                for row in result["rejected_native_attempts"]}
    assert set(rejected) == {"gear-L20", "pet-L20"}
    assert (rejected["gear-L20"]["proposal_axis"],
            rejected["gear-L20"]["native_refusal_code"],
            rejected["gear-L20"]["native_prepared"]) == (
                "gear", "native_item_not_eligible", False)
    assert (rejected["pet-L20"]["proposal_axis"],
            rejected["pet-L20"]["native_refusal_code"],
            rejected["pet-L20"]["native_prepared"]) == (
                "pet", "native_summon_unsupported", True)
    assert result["native_paid_request_axis_breadth_by_level"]["20"][
        "verified_native_paid_requests"] == 1
    assert result["native_paid_request_axis_breadth_by_level"]["20"][
        "uncompared_axes"] == ["talents", "gear", "apl", "pet"]


def test_guide_discloses_refused_axes_without_promoting_to_measured():
    """A source-native refusal is an attempted axis, not a paid alternative."""
    paid = _paid(20, "a", "100-0-0", 1)
    refused_gear = {
        "status": "NATIVE_API_CANDIDATE_REFUSED",
        "candidate_id": "refused-gear", "level": 20,
        "proposal_axis": "gear", "native_prepared": False,
        "native_refusal_code": "native_item_not_eligible",
    }
    refused_pet = {
        "status": "NATIVE_API_CANDIDATE_REFUSED",
        "candidate_id": "refused-pet", "level": 20,
        "proposal_axis": "pet", "native_prepared": True,
        "native_refusal_code": "native_summon_unsupported",
    }
    refused_without_code = {
        "status": "NATIVE_API_CANDIDATE_REFUSED",
        "candidate_id": "refused-apl", "level": 20,
        "proposal_axis": "apl", "native_prepared": False,
    }
    result = optimize(
        20, 20, 1, 2, 8,
        evaluate=lambda **kwargs: [
            paid, refused_gear, refused_pet, refused_without_code
        ],
        mode="compatible",
    )
    assert result["status"] == "SAMPLED_COMPATIBLE_PATH_PROVISIONAL"
    guide = render_sampled_build_guide(result)
    assert "- Native-paid candidate breadth: 1; talent allocations 1, gear sets 1, APLs 1, pet values 1." in guide
    assert ("- Refused native proposals (not paid or ranked): "
            "apl: 1 (no structured code), "
            "gear: 1 (native_item_not_eligible), "
            "pet: 1 (native_summon_unsupported)." in guide)
    assert "Only one compatible native-paid path retained" in guide
    assert result["native_paid_request_axis_breadth_by_level"]["20"][
        "verified_native_paid_requests"] == 1
