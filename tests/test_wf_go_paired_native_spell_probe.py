"""Paired schema regressions; synthetic reports NEVER count as native causal evidence."""
from __future__ import annotations

import pytest

from tools.wf_gsim_go_paired_native_spell_probe import compare_paired_reports


def sample(range_yards: float, casts: int):
    return {
        "status": "NATIVE_GO_WORLD_DAMAGE_ACK_NOT_P7",
        "native_process_reused": True,
        "gsim_runtime_real": True,
        "native_spell_action_ack": bool(casts),
        "checkpoint_certified": False,
        "native_binary_sha256": "native-binary-hash",
        "native_source_revision": "pinned-source",
        "native_request_sha256": "same-request-hash",
        "observations": [
            {"world_tick": {"distance_yards": range_yards},
             "native_spell_counters": [],
             "gsim_applied_world_ack": {"world_after_sha256": "a", "applied_event_ids": []},
             "native_world_ack_confirmation": {"observed_world_after_sha256": "a", "native_spell_action_ack": False}},
            {"world_tick": {"distance_yards": range_yards},
             "native_spell_counters": ([{
                 "action_id": "SpellID:123", "rank": 1, "casts": casts, "hits": casts,
                 "crits": 0, "ticks": 0, "total_damage": float(casts) * 100,
             }] if casts else []),
             "gsim_applied_world_ack": {"world_after_sha256": "b" if casts else "a",
                                         "applied_event_ids": ["native-effect-1"] if casts else []},
             "native_world_ack_confirmation": {"observed_world_after_sha256": "b" if casts else "a",
                                                "native_spell_action_ack": bool(casts)}},
        ]
    }


def test_paired_native_metric_delta_remains_not_druid_p7_even_with_world_ack():
    pair = compare_paired_reports(sample(3, 2), sample(80, 0))
    assert pair["range_perturbation_applied"]
    assert pair["native_spell_counter_delta_observed"]
    assert pair["status"] == "NATIVE_SPELL_DELTA_AND_WORLD_ACK_NOT_DRUID_P7"
    assert pair["native_spell_action_ack"] is True
    assert pair["checkpoint_certified"] is False
    assert pair["druid_l60_balance_proven"] is False


def test_world_perturbation_without_native_effect_does_not_pass():
    pair = compare_paired_reports(sample(3, 0), sample(80, 0))
    assert pair["status"] == "NO_NATIVE_SPELL_DELTA_OBSERVED"
    assert pair["native_spell_counter_delta_observed"] is False


@pytest.mark.parametrize("change", [
    lambda x: x.update(native_request_sha256="different-request"),
    lambda x: x.update(native_source_revision="different-source"),
    lambda x: x.update(native_binary_sha256="different-binary"),
    lambda x: x.update(native_spell_action_ack=True),
    lambda x: x.update(checkpoint_certified=True),
    lambda x: x.update(native_process_reused=False),
])
def test_different_requests_or_fabricated_claims_rejected(change):
    near, far = sample(3, 1), sample(80, 0)
    change(far)
    with pytest.raises(ValueError):
        compare_paired_reports(near, far)


def test_no_world_perturbation_rejected_even_with_native_metric_difference():
    with pytest.raises(ValueError, match="PERTURBATION_ABSENT"):
        compare_paired_reports(sample(3, 2), sample(3, 0))
