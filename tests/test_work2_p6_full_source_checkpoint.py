"""P6 full-source checkpoint routing; no heavy search or hybrid PASS here."""
from pathlib import Path

import pytest

from tools import wf_gate_p6_full_source as p6


def _cold(budget, *, level=60):
    return {
        "class_key": "druid", "level": level,
        "requested_wall_budget_s": budget, "search_only": True,
        "validation_shortlist": [{"full_source_build": True}],
        "wall_s": budget - 0.1,
        "source_db_sha256": "a" * 64,
        "source_gear_catalogue_snapshot": {"schema": "source_gear_snapshot_v1"},
    }


def _comparison():
    return {
        "replays": [
            {"status": "COMPLETE", "count": 100, "s_per_mob": 13.0},
            {"status": "COMPLETE", "count": 100, "s_per_mob": 12.5},
        ],
        "T30_s_per_mob": 13.0, "T300_s_per_mob": 12.5,
        "ratio_T30_T300": 1.04,
        "numeric_p6_within_1pct": False,
        "N30_unique_paid": 24, "N300_unique_paid": 240,
        "same_source_legal_candidate_space_proven": True,
    }


@pytest.mark.parametrize("checkpoint,context", [
    (("druid", 60, "balance"),
     ["--checkpoint-class", "druid", "--checkpoint-level", "60",
      "--checkpoint-spec", "balance"]),
    (("druid", 30, "unrestricted"), []),
])
def test_p6_independent_full_cold_search_and_comparison_share_checkpoint(
        monkeypatch, checkpoint, context):
    calls = []

    def fake_execute(root, arguments, output, timeout_s, **kwargs):
        calls.append((arguments, output.name, timeout_s, kwargs))
        if arguments[0] == "--compare-30":
            return _comparison(), None
        return _cold(int(arguments[1]), level=checkpoint[1]), None

    monkeypatch.setattr(p6, "_execute", fake_execute)
    report = p6.run_full_source_comparison(
        Path("/project"), checkpoint[0], checkpoint[1], spec=checkpoint[2])
    assert len(calls) == 3
    assert calls[0] == (["--budget", "30", *context],
                        "cold-30.json", 420, {})
    assert calls[1] == (["--budget", "300", *context],
                        "cold-300.json", 720, {})
    assert calls[2][0][:1] == ["--compare-30"]
    if context:
        assert calls[2][0][-len(context):] == context
    else:
        assert len(calls[2][0]) == 4
    assert calls[2][2:] == (240, {"allowed_codes": (0, 1)})
    assert report["status"] == "FAIL"  # gsim receipt is not a hybrid P6 PASS
    assert report["source_replay_T30_T300"] == 1.04
    assert report["search_wall_s"] == [29.9, 299.9]
    assert "P6_NUMERIC_SATURATION_EXCEEDS_1_PERCENT" in report["reasons"]


def test_p6_l60_real_30s_failure_stops_before_300s(monkeypatch):
    calls = []

    def fake_execute(root, arguments, output, timeout_s, **kwargs):
        calls.append(arguments)
        return None, "PAID_SOURCE_RUN_FAILED:rc=1"

    monkeypatch.setattr(p6, "_execute", fake_execute)
    report = p6.run_full_source_comparison(
        Path("/project"), "druid", 60, spec="balance")
    assert calls == [["--budget", "30", "--checkpoint-class", "druid",
                      "--checkpoint-level", "60", "--checkpoint-spec", "balance"]]
    assert report["status"] == "FAIL"
    assert report["reasons"] == ["P6_30S_PAID_SOURCE_RUN_FAILED:rc=1"]


def test_p6_sourced_gsim_100mob_within_one_percent_is_gate_pass(monkeypatch):
    """Real production subprocess reports are mocked; this tests ONLY the gate predicate."""
    calls = []

    def fake_execute(root, arguments, output, timeout_s, **kwargs):
        calls.append(arguments)
        if arguments[0] == "--compare-30":
            matched = _comparison()
            matched.update({
                "replays": [
                    {"status": "COMPLETE", "count": 100,
                     "mob_completed": 100, "s_per_mob": 12.50},
                    {"status": "COMPLETE", "count": 100,
                     "mob_completed": 100, "s_per_mob": 12.45},
                ],
                "T30_s_per_mob": 12.50,
                "T300_s_per_mob": 12.45,
                "ratio_T30_T300": 12.50 / 12.45,
                "numeric_p6_within_1pct": True,
                "same_source_legal_candidate_space_proven": True,
                "winning_gear_source_legality_verified": True,
                "p5_2x_breadth": True,
            })
            return matched, None
        search = _cold(int(arguments[1]))
        search["p4_talent_unlock_coverage_pass"] = True
        return search, None

    monkeypatch.setattr(p6, "_execute", fake_execute)
    report = p6.run_full_source_comparison(
        Path("/project"), "druid", 60, spec="balance")

    assert len(calls) == 3
    assert report["status"] == "PASS"
    assert report["reasons"] == []
    assert report["production_engine"] == "gsim_CombatRuntime"
    assert report["full_p6_selected_backend_acceptance"] is True
    assert report["runtime_proof"]["executed"] is True
    assert report["runtime_proof"]["engine_revision"].startswith("gsim-")
    assert len(report["runtime_proof"]["source_revision"]) == 64
    assert report["runtime_proof"]["run_id"].startswith("source-paid-p6-")
    assert report["source_replay_T30_T300"] <= 1.01


@pytest.mark.parametrize("broken,expected", [
    ("missing_kill", "P6_INDEPENDENT_100MOB_REPLAY_INCOMPLETE"),
    ("wrong_source", "P6_INDEPENDENT_COLD_SOURCE_SPACE_NOT_MATCHED"),
    ("illegal_winner", "P6_WINNING_GEAR_SOURCE_LEGALITY_NOT_VERIFIED"),
    ("no_unlock", "P6_SOURCE_UNLOCK_PAID_EVALUATIONS_INCOMPLETE"),
    ("thin_p5", "P6_P5_COLD_WINNER_PAID_BREADTH_NOT_VERIFIED"),
    ("too_slow", "P6_NUMERIC_SATURATION_EXCEEDS_1_PERCENT"),
])
def test_p6_true_approved_failures_still_fail(monkeypatch, broken, expected):
    def fake_execute(root, arguments, output, timeout_s, **kwargs):
        if arguments[0] == "--compare-30":
            comparison = {
                "replays": [{"status": "COMPLETE", "count": 100, "mob_completed": 100,
                             "s_per_mob": 12.5} for _ in range(2)],
                "T30_s_per_mob": 12.5, "T300_s_per_mob": 12.5,
                "ratio_T30_T300": 1.0,
                "numeric_p6_within_1pct": True,
                "same_source_legal_candidate_space_proven": True,
                "winning_gear_source_legality_verified": True,
                "p5_2x_breadth": True,
            }
            if broken == "missing_kill":
                comparison["replays"][0]["mob_completed"] = 99
            elif broken == "wrong_source":
                comparison["same_source_legal_candidate_space_proven"] = False
            elif broken == "illegal_winner":
                comparison["winning_gear_source_legality_verified"] = False
            elif broken == "thin_p5":
                comparison["p5_2x_breadth"] = False
            elif broken == "too_slow":
                comparison["numeric_p6_within_1pct"] = False
                comparison["ratio_T30_T300"] = 1.02
            return comparison, None
        search = _cold(int(arguments[1]))
        search["p4_talent_unlock_coverage_pass"] = broken != "no_unlock"
        return search, None

    monkeypatch.setattr(p6, "_execute", fake_execute)
    report = p6.run_full_source_comparison(Path("/project"), "druid", 60, spec="balance")
    assert report["status"] == "FAIL"
    assert expected in report["reasons"]
    assert not report.get("runtime_proof")
    assert report["full_p6_selected_backend_acceptance"] is False
