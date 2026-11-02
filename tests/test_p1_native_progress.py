"""P1 partial progress is native behavior only, never gsim or APL metadata.

Test-only synthetic rows are used to test arithmetic; none is native evidence
and no test here awards a formal P1 PASS.
"""
import pytest

from tools.p1_native_progress import (
    THRESHOLDS, VERIFIED_EFFECT, milestone_progress, native_p1_progress,
)
from tools.p1_native_source_inventory import inventory


def _scope(n=100):
    return {
        "source_only": True, "game_ir_required": False,
        "class": "hunter", "level": 20,
        "scenario": "current_solo_leveling_100mob_v1",
        "candidates": [{"spell_id": x} for x in range(1, n + 1)],
        "separate": [
            {"spell_id": 10001, "status": "NOT_RELEVANT_TO_SIMULATION"},
            {"spell_id": 10002, "status": "ACQUISITION_UNRESOLVED"},
            {"spell_id": 10003, "status": "NATIVE_AUTO_ATTACK"},
        ],
    }


def _real_direct_test(sid):
    # Deliberately synthetic schema input: only production runner may create
    # genuine executable evidence, and this function alone never certifies P1.
    return {"spell_id": sid, "status": VERIFIED_EFFECT,
            "proof_kind": "NATIVE_DIRECT_EFFECT",
            "executor": "msim-rust", "native_executed": True,
            "controlled_behavior_assertion_passed": True,
            "observable_effects": [{"kind": "target_hp_delta", "delta": -10}]}


@pytest.mark.parametrize("n,expected", [
    (0, []), (49, []), (50, [50]), (79, [50]),
    (80, [50, 80]), (85, [50, 80, 85]),
    (88, [50, 80, 85, 88]), (91, [50, 80, 85, 88, 91]),
    (93, [50, 80, 85, 88, 91, 93]),
    (95, [50, 80, 85, 88, 91, 93, 95]),
    (97, [50, 80, 85, 88, 91, 93, 95, 97]),
    (99, list(THRESHOLDS)), (100, list(THRESHOLDS)),
])
def test_pareto_threshold_boundaries(n, expected):
    result = milestone_progress(n, 100)
    assert result["milestones_reached"] == expected
    assert result["progress_naksut"] == len(expected)
    assert result["formal_gate_pass"] is False
    assert result["progress_naksut"] <= 9


def test_unknowns_conservatively_stay_in_denominator():
    result = milestone_progress(80, 100, unknown=100)
    assert result["conservative_denominator"] == 200
    assert result["progress_naksut"] == 0


def test_empty_or_impossible_population_never_auto_green():
    assert milestone_progress(0, 0)["effect_coverage_fraction"] is None
    assert milestone_progress(0, 0)["progress_naksut"] == 0
    with pytest.raises(ValueError, match="MORE_SUCCESSES"):
        milestone_progress(101, 100)
    with pytest.raises(ValueError, match="INVALID_PROGRESS"):
        milestone_progress(True, 100)


def test_gsim_and_native_apl_diagnostic_do_not_grant_any_effect_ticks():
    scope = _scope(3)
    observed = native_p1_progress(scope, [
        {"spell_id": 1, "status": "EFFECT_OBSERVED",
         "proof_kind": "GSIM_ABLATION_DIAGNOSTIC", "native_executed": False},
        {"spell_id": 2, "status": "NATIVE_APL_ABLATION_DIFFERENCE",
         "proof_kind": "RUST_APL_ABLATION_DIAGNOSTIC_NOT_ISOLATED_P1",
         "native_executed": True, "effect_observed": True},
        {"spell_id": 3, "status": VERIFIED_EFFECT,
         "proof_kind": "NATIVE_DIRECT_EFFECT", "native_executed": False,
         "executor": "msim-rust", "controlled_behavior_assertion_passed": True,
         "observable_effects": [{"kind": "damage", "delta": 99}]},
    ])
    assert observed["verified"] == 0
    assert observed["progress_naksut"] == 0
    assert observed["diagnostic_only_spell_ids"] == [1, 2, 3]
    assert observed["not_relevant_spell_ids"] == [10001]
    assert observed["source_unknown_count"] == 1
    assert observed["formal_gate_pass"] is False


def test_verifiable_native_direct_effects_count_conservatively_no_formal_pass():
    scope = _scope(100)
    results = [_real_direct_test(i) for i in range(1, 100)]
    measured = native_p1_progress(scope, results)
    assert measured["verified"] == 99
    # One unresolved acquisition on top of 100 provisional source candidates:
    # 99 / 101 < 99%, so eighth rather than ninth milestone.
    assert measured["conservative_denominator"] == 101
    assert measured["milestones_reached"][-1] == 97
    assert measured["progress_naksut"] == 8
    assert measured["formal_gate_pass"] is False
    assert measured["source_legality_confirmed"] is False


def test_no_foreign_results_duplicate_green_or_waiver_smuggling():
    scope = _scope(2)
    with pytest.raises(ValueError, match="RUNTIME_RESULT_NOT_IN_SOURCE_SCOPE"):
        native_p1_progress(scope, [_real_direct_test(555)])
    with pytest.raises(ValueError, match="DUPLICATE_RUNTIME_TEST"):
        native_p1_progress(scope, [_real_direct_test(1), _real_direct_test(1)])
    excluded = native_p1_progress(scope, [_real_direct_test(10001)])
    assert excluded["verified"] == 0
    assert excluded["not_relevant_count"] == 1


def test_real_hunter_inventory_progress_never_counts_raw_index_as_verified():
    source = inventory("hunter", 20)
    measured = native_p1_progress(source)
    assert measured["source_candidate_count"] > 0
    assert measured["verified"] == 0
    assert measured["progress_naksut"] == 0
    assert measured["source_legality_confirmed"] is False
    assert measured["formal_gate_pass"] is False
