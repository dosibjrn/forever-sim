"""Independent native anchor sampling never invents sampled-level ancestry."""

import hashlib
import json
import subprocess

from src.v2.native_range_optimizer import optimize
from tools.wf_warlock_native_source_frontier import produce_frontier


def receipt(level, mobs, label, elapsed, recovery=1.0):
    return {
        "status": "MEASURED_NATIVE_FULLY_RECOVERED",
        "candidate_id": label, "level": level, "mob_count": mobs,
        "targets_killed": mobs, "rng_mode": "balanced", "iterations": 1,
        "native_prepared": True, "native_world_ack": True,
        "native_full_recovery_paid": True, "recover_to_full": True,
        "terminal_hp": 100.0, "terminal_max_hp": 100.0,
        "terminal_mana": 200.0, "terminal_max_mana": 200.0,
        "terminal_recovery_seconds": recovery, "elapsed_seconds": elapsed,
        "source_request_sha256": hashlib.sha256(
            f"{level}:{label}".encode()).hexdigest(),
        "engine_binary_sha256": "a" * 64,
        "talents": label,
    }


def test_one_invocation_ranks_five_paid_independent_levels_with_no_fake_route():
    calls = []

    def evaluator(**request):
        calls.append(request)
        level = request["level"]
        mobs = request["mob_count"]
        # A spends less time fighting but is slower AFTER charged restoration.
        return [receipt(level, mobs, "A", 12.0, recovery=10.0),
                receipt(level, mobs, "B", 8.0, recovery=1.0)]

    result = optimize(20, 60, 10, 3, 20, evaluate=evaluator)
    assert [row["level"] for row in calls] == [20, 30, 40, 50, 60]
    assert all(row["parent"] is None
               and row["search_mode"] == "independent"
               and row["recover_to_full"] is True
               and row["rng_mode"] == "balanced"
               and row["iterations"] == 1 for row in calls)
    assert result["status"] == "INDEPENDENT_NATIVE_ANCHORS_RANKED"
    assert result["sampled_levels_completed"] == [20, 30, 40, 50, 60]
    assert result["ranked_alternatives"] == []  # Not a legal route.
    assert result["continuity_unverified"] is True
    assert result["full_10_60_continuous_leveling_route_proven"] is False
    assert result["independent_sample_sum_is_route_time"] is False
    assert result["independent_sample_winner_elapsed_sum_seconds"] == 40.0
    for level in [20, 30, 40, 50, 60]:
        ranked = result["independent_level_rankings"][str(level)]
        assert [row["talents"] for row in ranked] == ["B", "A"]
        assert ranked[0]["native_elapsed_seconds"] == 8.0
        assert ranked[0]["terminal_recovery_seconds"] == 1.0
        assert all(row["continuity_unverified"] for row in ranked)


def test_native_refusal_does_not_stop_later_independent_anchor_or_count_as_rank():
    seen = []

    def evaluator(**request):
        level = request["level"]
        seen.append(level)
        if level == 30:
            return [{"status": "NATIVE_PREPARE_REFUSED",
                     "candidate_id": "refused", "native_prepared": False}]
        return [receipt(level, request["mob_count"], "A", 10.0),
                receipt(level, request["mob_count"], "B", 9.0)]

    report = optimize(20, 60, 10, 3, 20, evaluate=evaluator,
                      mode="independent")
    assert seen == [20, 30, 40, 50, 60]
    assert report["status"] == "INDEPENDENT_NATIVE_ANCHORS_PARTIAL"
    assert report["sampled_levels_completed"] == [20, 40, 50, 60]
    assert report["independent_level_rankings"]["30"] == []
    assert report["native_attempts_by_level"]["30"] == 1
    assert report["independent_sample_winner_elapsed_sum_seconds"] is None
    assert any(row["level"] == 30 for row in report["rejected_native_attempts"])


def test_sparse_and_dense_independent_calls_share_same_evaluator():
    calls = []

    def evaluator(**request):
        calls.append((request["level"], request["mob_count"],
                      request["parent"], request["search_mode"]))
        return [receipt(request["level"], request["mob_count"], "A", 7.0),
                receipt(request["level"], request["mob_count"], "B", 6.0)]

    sparse = optimize(20, 60, 10, 3, 20, evaluate=evaluator,
                      mode="independent")
    assert sparse["status"] == "INDEPENDENT_NATIVE_ANCHORS_RANKED"
    assert calls == [(level, 3, None, "independent")
                     for level in (20, 30, 40, 50, 60)]
    calls.clear()
    dense = optimize(10, 60, 1, 100, 200, evaluate=evaluator,
                     mode="independent")
    assert dense["status"] == "INDEPENDENT_NATIVE_ANCHORS_RANKED"
    assert dense["sampled_levels_completed"] == list(range(10, 61))
    assert calls == [(level, 100, None, "independent")
                     for level in range(10, 61)]


def test_live_native_source_prepares_independent_level_without_ancestry(tmp_path):
    source = tmp_path / "seed.json"
    source.write_text(json.dumps({
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "level": 20, "talentsString": "11-0-0",
        }]}]},
        "encounter": {"targets": [{"level": 20}]},
    }))
    binary = tmp_path / "rust"
    binary.write_bytes(b"source-native-binary")
    prepared_levels = []

    def native(command, **kwargs):
        if command[1] == "options":
            assert command[-1] == "30"
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({
                "level": 30, "talents": {"status": "ok", "trees": [
                    {"talents": [{"index": 0, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                ]},
            }))
        request_path = tmp_path / "seed.json"
        actual = __import__("pathlib").Path(command[command.index("--request") + 1])
        target = __import__("pathlib").Path(command[command.index("--outfile") + 1])
        proposal = json.loads(actual.read_text())
        actor = proposal["raid"]["parties"][0]["players"][0]
        prepared_levels.append(actor["level"])
        assert cmd[cmd.index("--actor-level") + 1] == "30"
        assert actor["level"] == proposal["encounter"]["targets"][0]["level"] == 30
        target.write_text(json.dumps({
            "request_sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": 30},
        }))
        return subprocess.CompletedProcess(command, 0)

    found = produce_frontier({
        "level": 30, "parent": None, "search_mode": "independent",
        "budget": 3, "mob_count": 3, "rng_mode": "balanced",
        "iterations": 1, "recover_to_full": True,
    }, binary=binary, seed_source=source,
        out=tmp_path / "native", runner=native)
    assert prepared_levels == [30, 30, 30]  # Never fake L21-L29.
    assert len(found["entries"]) == 3
    assert all(entry["parent_source_sha256"] is None
               and "native_continuity_receipt" not in entry
               for entry in found["entries"])
    assert json.loads(source.read_text())["raid"]["parties"][0]["players"][0]["level"] == 20


def test_one_cli_invocation_defaults_to_independent_anchor_scoring(tmp_path, monkeypatch):
    from tools import wf_warlock_native_range_optimize as cli
    calls = []

    def fake_run(command, *, input, capture_output, text, timeout, check):
        request = json.loads(input)
        calls.append(request)
        level = request["level"]
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps([
            receipt(level, request["mob_count"], "A", 15.0),
            receipt(level, request["mob_count"], "B", 8.0),
        ]))

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    out = tmp_path / "independent.json"
    exit_code = cli.main([
        "--start-level", "20", "--end-level", "60",
        "--level-stride", "10", "--mob-count", "3", "--budget", "20",
        "--evaluator-command", "native-scored-evaluator", "--out", str(out),
    ])
    report = json.loads(out.read_text())
    assert exit_code == 0
    assert report["status"] == "INDEPENDENT_NATIVE_ANCHORS_RANKED"
    assert len(calls) == 5
    assert all(row["parent"] is None for row in calls)
    assert report["ranked_alternatives"] == []
