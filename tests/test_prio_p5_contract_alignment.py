"""Legacy diagnostic P5 breadth follows the approved 2× rule.

These synthetic validator checks are NOT production P5 acceptance evidence;
the public CLI still requires a real paid 300s + 100-mob native/world run.
"""
from tools.wf_gate import _validate_p5


def _search_evidence(unique, budget):
    return {
        "search_wall_s": float(budget),
        "unique_full_builds": unique,
        "complete_100mob_replays": 1,
        "best_full_s_per_mob": 12.5,
        "unlock_coverage_pass": True,
        "uncovered_unlock_families": [],
        "independent_replay_outside_budget": True,
        "talent_gear_apl_jointly_searched": True,
        "full_legal_builds": True,
        "mob_count": 100,
    }


def _prior_p4(unique=5):
    return {"P4": {"status": "PASS", "evidence": _search_evidence(unique, 30)}}


def test_exact_approved_double_breadth_passes_legacy_diagnostic():
    # Previously mislabeled FAIL by the obsolete 10× condition.
    assert _validate_p5(_search_evidence(10, 300), _prior_p4()) == []


def test_one_below_approved_double_breadth_fails():
    errors = _validate_p5(_search_evidence(9, 300), _prior_p4())
    assert len(errors) == 1
    assert "required>=2x" in errors[0]


def test_double_breadth_does_not_waive_real_100mob_replay():
    record = _search_evidence(10, 300)
    record["complete_100mob_replays"] = 0
    assert "NO_COMPLETED_100MOB_REPLAY" in _validate_p5(record, _prior_p4())


def test_double_breadth_needs_independently_passed_p4():
    assert "P4_NOT_PASS" in _validate_p5(_search_evidence(10, 300), {})
