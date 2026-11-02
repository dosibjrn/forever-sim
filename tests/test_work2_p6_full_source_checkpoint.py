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
