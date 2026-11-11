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
        assert command[command.index("--actor-level") + 1] == "30"
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


def test_failed_native_anchor_producer_preserves_refusal_and_visits_later_levels(
    tmp_path, monkeypatch,
):
    """An L30 native producer failure must not erase L20 or starve L40-L60."""
    from tools import wf_warlock_native_range_optimize as cli
    from tools import wf_warlock_native_range_scored_adapter as scored

    levels_requested = []
    scored_levels = []

    def source_producer(command, *, input, capture_output, text, timeout, check):
        request = json.loads(input)
        level = request["level"]
        levels_requested.append(level)
        assert request["parent"] is None
        assert request["mob_count"] == 3
        assert request["recover_to_full"] is True
        if level == 30:
            return subprocess.CompletedProcess(
                command, 7, stderr="native options refused level 30",
            )
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"entries": [], "refusals": []}),
        )

    def paid_scorer(request, **kwargs):
        scored_levels.append(request["level"])
        return [
            receipt(request["level"], 3, "slower", 12.0),
            receipt(request["level"], 3, "faster", 9.0),
        ]

    monkeypatch.setattr(scored, "evaluate_request", paid_scorer)
    evaluator = cli.live_native_frontier_evaluator(
        ["native-frontier"], binary=tmp_path / "native-binary",
        target_hp=400.0, scorer_command=["native-scorer"],
        artifact_dir=tmp_path, run_command=source_producer,
    )
    outcome = optimize(20, 60, 10, 3, 20, evaluate=evaluator)
    assert levels_requested == [20, 30, 40, 50, 60]
    assert scored_levels == [20, 40, 50, 60]  # No fabricated L30 payment.
    assert outcome["status"] == "INDEPENDENT_NATIVE_ANCHORS_PARTIAL"
    assert outcome["sampled_levels_completed"] == [20, 40, 50, 60]
    assert outcome["native_attempts_by_level"]["30"] == 1
    assert outcome["independent_level_rankings"]["30"] == []
    assert outcome["native_candidates_examined"] == 9
    refusal = next(row for row in outcome["rejected_native_attempts"]
                   if row["level"] == 30)
    assert refusal["native_status"] == "NATIVE_FRONTIER_PRODUCER_EXECUTION_ERROR"
    assert "exit 7: native options refused level 30" in refusal["native_refusal"]
    stored = list(tmp_path.glob("source-frontier-*/native-frontier-failure.json"))
    assert len(stored) == 1
    assert json.loads(stored[0].read_text())["native_refusal"] == refusal["native_refusal"]

def test_one_cli_request_uses_level_specific_scenario_hp_unless_overridden(
    tmp_path, monkeypatch,
):
    """Sampling L20 and L60 must not silently fight identical-health mobs."""
    from tools import wf_warlock_native_range_optimize as cli
    from tools import wf_warlock_native_range_scored_adapter as scored

    target_hps = []

    def native_source(command, *, input, capture_output, text, timeout, check):
        request = json.loads(input)
        assert request["parent"] is None
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"entries": [], "refusals": []}),
        )

    def native_paid(request, *, target_hp, **kwargs):
        target_hps.append((request["level"], target_hp))
        return [
            receipt(request["level"], 3, "A", 12.0),
            receipt(request["level"], 3, "B", 9.0),
        ]

    monkeypatch.setattr(cli.subprocess, "run", native_source)
    monkeypatch.setattr(scored, "evaluate_request", native_paid)

    arguments = [
        "--start-level", "20", "--end-level", "60", "--level-stride", "40",
        "--mob-count", "3", "--budget", "4",
        "--native-frontier-command", "native-frontier",
        "--native-binary", str(tmp_path / "native"),
        "--native-receipts-dir", str(tmp_path / "receipts"),
        "--out", str(tmp_path / "result.json"),
    ]
    assert cli.main(arguments) == 0
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["sampled_levels_completed"] == [20, 60]
    assert target_hps == [(20, 484.0), (60, 3052.0)]

    # An explicit fixed HP remains available for byte-compatible prior
    # scenarios, but is never silently imposed on the new sampled range.
    target_hps.clear()
    assert cli.main(arguments + ["--native-target-hp", "400"]) == 0
    assert target_hps == [(20, 400.0), (60, 400.0)]

def test_one_sparse_compatible_optimizer_call_returns_one_three_level_build_path():
    """Sparse rank compatibility is not a demand to simulate intervening levels."""
    calls = []
    talents = {
        20: [("5-0-0", 3.0), ("0-5-0", 5.0)],
        40: [("0-55-0", 1.0), ("55-0-0", 7.0)],
        60: [("0-555-0", 1.0), ("555-0-0", 6.0)],
    }

    def native(**request):
        calls.append(request)
        level = request["level"]
        rows = []
        for name, seconds in talents[level]:
            row = receipt(level, request["mob_count"], name, seconds)
            row["talents"] = name
            row["apl"] = {"priorityList": [name]}
            row["gear"] = {"items": [level]}
            rows.append(row)
        return rows

    result = optimize(
        20, 60, 20, 2, 12, evaluate=native, mode="compatible",
        class_name="warlock", talent_tree="unconstrained", backend="native",
        rng_mode="balanced", iterations=1, recover_to_full=True,
    )
    assert [r["level"] for r in calls] == [20, 40, 60]
    assert all(r["parent"] is None and r["mob_count"] == 2
               and r["recover_to_full"] is True
               and r["rng_mode"] == "balanced" and r["iterations"] == 1
               for r in calls)
    assert result["status"] == "SAMPLED_COMPATIBLE_PATH_RANKED"
    assert result["intermediate_level_simulations_run"] is False
    assert result["full_10_60_continuous_leveling_route_proven"] is False
    best = result["ranked_alternatives"][0]
    assert [step["level"] for step in best["steps"]] == [20, 40, 60]
    # Independent fastest L20 (5-0-0) is incompatible with the faster
    # L40/L60 alternative (0-25-0 / 0-45-0).
    assert [step["talents"] for step in best["steps"]] == [
        "0-5-0", "0-55-0", "0-555-0",
    ]
    assert best["sampled_cumulative_seconds"] == 7.0
    assert [step["gear"]["items"] for step in best["steps"]] == [
        [20], [40], [60],
    ]
    assert all(step["apl"] for step in best["steps"])


def test_sparse_compatible_rejects_respec_and_does_not_fabricate_route():
    def native(**request):
        level = request["level"]
        name = {20: "5-0-0", 40: "0-25-0", 60: "0-45-0"}[level]
        row = receipt(level, request["mob_count"], name, 9.0)
        row["talents"] = name
        return [row]

    report = optimize(20, 60, 20, 2, 6, evaluate=native, mode="compatible")
    assert report["status"] == "NO_COMPLETE_COMPATIBLE_SAMPLED_PATH"
    assert report["sampled_levels_compatible"] == [20]
    assert report["ranked_alternatives"] == []
    assert report["no_respec_within_sampled_path"] is False


def test_generic_optimize_cli_accepts_class_tree_stride_two_mobs_and_balanced(
    tmp_path, capsys,
):
    """No Warlock-specific command or separate JSON contract is needed."""
    from src.v2.native_range_optimizer import main as optimize_main
    calls = []
    by_level = {
        20: ["5-0-0", "0-5-0"],
        40: ["55-0-0", "0-55-0"],
        60: ["555-0-0", "0-555-0"],
    }

    def native(**request):
        calls.append(request)
        result = []
        for name in by_level[request["level"]]:
            row = receipt(request["level"], request["mob_count"], name, 4.0)
            row.update(talents=name, apl={"actions": ["native"]},
                       gear={"items": [{"id": 101}]})
            result.append(row)
        return result

    output = tmp_path / "optimizer-result.json"
    exit_code = optimize_main([
        "--class", "warlock", "--tree", "unconstrained",
        "--start-level", "20", "--end-level", "60",
        "--level-stride", "20", "--n-mobs", "2",
        "--rng", "balanced", "--backend", "rust",
        "--recover-at-end", "true", "--budget", "12",
        "--out", str(output),
    ], evaluate=native)
    report = json.loads(output.read_text())
    assert exit_code == 0
    assert [row["level"] for row in calls] == [20, 40, 60]
    assert all(row["mob_count"] == 2 and row["parent"] is None
               for row in calls)
    assert report["class"] == "warlock"
    assert report["tree"] == "unconstrained"
    assert report["search_mode"] == "compatible"
    assert [step["level"] for step in
            report["ranked_alternatives"][0]["steps"]] == [20, 40, 60]
    printed = capsys.readouterr().out
    assert "L20 talents=" in printed
    assert "L40 talents=" in printed
    assert "L60 talents=" in printed
    assert "gear=" in printed and "apl=" in printed


def test_generic_cli_defaults_to_level_specific_hostile_hp(tmp_path, monkeypatch):
    """Generic CLI must forward per-level scenario HP to native, or a fixed override.

    No Warcraft mechanics are evaluated here; this verifies only Forever's
    request forwarding through the same one-call compatible optimizer.
    """
    from src.scenarios.leveling_targets import representative_hp
    from src.v2.native_range_optimizer import main as generic_main
    from tools import wf_warlock_native_persistent_optimizer as native_cli

    binary = tmp_path / "native-engine"
    binary.write_bytes(b"pinned-engine-placeholder")
    source = tmp_path / "initial-source.json"
    source.write_text("{}")
    seen = []

    class FakePersistentNativeEvaluator:
        def __init__(self, binary, source, artifact_dir, *, target_hp=None,
                     explore_world_policies=False):
            assert explore_world_policies is True  # ordinary Warlock CLI
            self.target_hp = target_hp

        def __call__(self, **request):
            level = request["level"]
            hp = (float(representative_hp(level)) if self.target_hp is None
                  else float(self.target_hp))
            seen.append((level, hp, request["mob_count"]))
            digits = "1" * (level // 20)
            rows = []
            for i, talents in enumerate((f"{digits}-0-0", f"0-{digits}-0")):
                row = receipt(level, request["mob_count"], f"{level}-{i}", 7.0 + i)
                row["talents"] = talents
                rows.append(row)
            return rows

        def close(self):
            pass

    monkeypatch.setattr(native_cli, "PersistentNativeEvaluator",
                        FakePersistentNativeEvaluator)
    base_args = [
        "--class", "warlock", "--tree", "unconstrained",
        "--start-level", "20", "--end-level", "60", "--level-stride", "20",
        "--n-mobs", "2", "--budget", "6", "--rng", "balanced",
        "--backend", "rust", "--recover-at-end", "true",
        "--native-binary", str(binary), "--source", str(source),
        "--out", str(tmp_path / "generic.json"),
    ]

    assert generic_main(base_args) == 0
    assert seen == [
        (level, float(representative_hp(level)), 2)
        for level in (20, 40, 60)
    ]
    assert seen[0][1] == 484.0
    assert seen[-1][1] == 3052.0
    assert json.loads((tmp_path / "generic.json").read_text())[
        "status"] == "SAMPLED_COMPATIBLE_PATH_RANKED"

    seen.clear()
    assert generic_main(base_args + ["--target-hp", "400"]) == 0
    assert seen == [(level, 400.0, 2) for level in (20, 40, 60)]



def test_generic_optimizer_entrypoint_bypasses_legacy_class_registry():
    """Actual -m runner must dispatch Warlock before old engine argv parsing."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "src.v2.runner", "optimize",
         "--class", "warlock", "--start-level", "20", "--end-level", "60",
         "--level-stride", "20", "--n-mobs", "2", "--rng", "balanced",
         "--backend", "rust", "--recover-at-end", "true", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--n-mobs" in proc.stdout and "--backend" in proc.stdout
    assert "source-native sampled compatible build optimization" in proc.stdout.lower()
    assert "invalid choice: 'warlock'" not in proc.stderr


def test_paid_l60_demo_family_can_backseed_native_l20_ancestor_and_win_route():
    """The cheapest L20 root need not minimize cumulative native-paid time."""
    seen = []

    def native(**request):
        level = request["level"]
        seen.append(request)
        if level == 20:
            choices = [("5-0-0", 1.0)]
            if request.get("candidate_hints"):
                choices.append(("0-5-0", 4.0))
        elif level == 40:
            choices = [("55-0-0", 10.0), ("0-55-0", 4.0)]
        else:
            choices = [("555-0-0", 20.0), ("0-555-0", 1.0)]
        return [
            dict(receipt(level, request["mob_count"], talent, seconds),
                 talents=talent, gear={"items": [level]}, pet="native",
                 apl={"priorityList": [talent]})
            for talent, seconds in choices
        ][:request["budget"]]

    result = optimize(20, 60, 20, 2, 24, evaluate=native,
                      mode="compatible", beam_width=2)
    assert result["status"] == "SAMPLED_COMPATIBLE_PATH_RANKED"
    assert result["native_candidates_examined"] <= 24
    assert result["backward_seeded_native_attempts"] > 0
    assert any(request["level"] == 20 and request.get("candidate_hints")
               for request in seen)
    assert [step["talents"] for step in result["ranked_alternatives"][0]["steps"]] == [
        "0-5-0", "0-55-0", "0-555-0",
    ]
    assert result["ranked_alternatives"][0]["sampled_cumulative_seconds"] == 9.0
    assert result["ranked_alternatives"][1]["sampled_cumulative_seconds"] == 31.0
    assert result["intermediate_level_simulations_run"] is False
    assert result["full_10_60_continuous_leveling_route_proven"] is False


def test_paid_later_talent_hint_proposes_bounded_ancestors_not_legality():
    from tools.wf_warlock_native_source_frontier import _backward_ancestor_variants

    proposals = list(_backward_ancestor_variants(
        [{"talents": "0-555-0", "from_level": 60}], points_available=5))
    assert proposals
    assert all(sum(map(int, "".join(p.split("-")))) == 5 for p in proposals)
    assert all(p.startswith("0-") and p.endswith("-0") for p in proposals)
    # With no source-native point budget, don't manufacture level-derived
    # talent caps; Rust's options API must provide the actual bound.
    assert list(_backward_ancestor_variants(
        [{"talents": "0-555-0"}], points_available=None)) == []
