"""Forever transport and route-scoring tests; no MythicSim rules revalidated."""
from __future__ import annotations

import pytest

from src.v2.native_range_optimizer import _receipt_error, optimize, sampled_levels


ENGINE = "b" * 64


def receipt(level, mob_count, label, seconds, parent=None, recovery=1.0):
    source = (f"{level:02x}{ord(label):02x}" + "a" * 60)
    return {
        "status": "MEASURED_NATIVE_FULLY_RECOVERED", "level": level, "mob_count": mob_count,
        "targets_killed": mob_count, "rng_mode": "balanced", "iterations": 1,
        "native_prepared": True, "native_world_ack": True,
        "native_full_recovery_paid": True, "recover_to_full": True,
        "terminal_hp": 100.0, "terminal_max_hp": 100.0,
        "terminal_mana": 200.0, "terminal_max_mana": 200.0,
        "elapsed_seconds": seconds, "terminal_recovery_seconds": recovery,
        "source_request_sha256": source, "engine_binary_sha256": ENGINE,
        "native_parent_source_sha256": (
            parent["source_request_sha256"] if parent else None
        ),
        "native_continuity_ack": True if parent else None,
        "native_continuity_from_level": parent["level"] if parent else None,
        "native_intermediate_levels_verified": True,
        "talents": label,
    }


def test_one_invocation_scores_five_levels_and_later_fast_path_beats_first():
    calls = []

    def evaluator(*, level, parent, mob_count, budget, rng_mode, iterations,
                  recover_to_full):
        calls.append((level, parent and parent["talents"], mob_count, budget,
                      rng_mode, iterations, recover_to_full))
        if parent is None:
            # A is first prepared but slower at L20; it wins the cumulative route.
            return [receipt(level, mob_count, "A", 6.0),
                    receipt(level, mob_count, "B", 3.0)]
        return [receipt(level, mob_count, parent["talents"],
                        1.0 if parent["talents"] == "A" else 9.0,
                        parent, recovery=0.5)]

    result = optimize(20, 60, 10, 3, 100, evaluate=evaluator, beam_width=2, mode="continuing")
    assert result["status"] == "SAMPLED_NATIVE_PATH_RANKED"
    assert result["sampled_levels_requested"] == [20, 30, 40, 50, 60]
    assert result["sampled_levels_completed"] == [20, 30, 40, 50, 60]
    assert len(calls) == 9  # one high-level call, two continuing source paths
    assert all(c[2] == 3 and c[4:] == ("balanced", 1, True) for c in calls)
    assert len(result["ranked_alternatives"]) == 2
    assert [s["talents"] for s in result["ranked_alternatives"][0]["steps"]] == ["A"] * 5
    assert result["ranked_alternatives"][0]["sampled_cumulative_seconds"] == 10.0
    assert result["ranked_alternatives"][1]["sampled_cumulative_seconds"] == 39.0
    assert result["full_10_60_continuous_leveling_route_proven"] is False
    assert result["native_candidates_examined"] == 10


def test_same_optimizer_accepts_dense_resolution_as_only_arguments():
    observed = []

    def single(*, level, parent, mob_count, budget, rng_mode, iterations,
               recover_to_full):
        observed.append((level, mob_count))
        return [receipt(level, mob_count, "A", 1.0, parent)]

    sparse = optimize(20, 60, 10, 3, 100, evaluate=single, mode="continuing")
    assert sparse["sampled_levels_completed"] == [20, 30, 40, 50, 60]
    assert observed == [(x, 3) for x in (20, 30, 40, 50, 60)]
    observed.clear()
    dense = optimize(10, 60, 1, 100, 100, evaluate=single, mode="continuing")
    assert dense["sampled_levels_completed"] == list(range(10, 61))
    assert observed == [(level, 100) for level in range(10, 61)]
    assert sampled_levels(20, 59, 10) == (20, 30, 40, 50, 59)


def test_native_paid_full_resource_terminal_time_changes_winner():
    def variants(*, level, parent, mob_count, **kwargs):
        # Fast combat with unpaid debt costs 25 seconds to restore both bars.
        return [receipt(level, mob_count, "A", 30.0, recovery=25.0),
                receipt(level, mob_count, "B", 14.0, recovery=2.0)]

    result = optimize(20, 20, 1, 3, 2, evaluate=variants, mode="continuing")
    assert result["ranked_alternatives"][0]["steps"][0]["talents"] == "B"
    assert result["ranked_alternatives"][0]["sampled_cumulative_seconds"] == 14.0
    assert result["ranked_alternatives"][0]["steps"][0]["terminal_recovery_seconds"] == 2.0


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(native_full_recovery_paid=False),
    lambda r: r.update(terminal_mana=199.0),
    lambda r: r.update(terminal_hp=99.0),
    lambda r: r.update(terminal_recovery_seconds=None),
    lambda r: r.update(native_world_ack=False),
    lambda r: r.update(targets_killed=2),
    lambda r: r.update(engine_binary_sha256=None),
    lambda r: r.update(elapsed_seconds=float("nan")),
])
def test_incomplete_or_unpaid_native_receipt_never_scores(mutate):
    def scorer(*, level, parent, mob_count, **kwargs):
        row = receipt(level, mob_count, "A", 10.0)
        mutate(row)
        return [row]

    result = optimize(20, 20, 1, 3, 1, evaluate=scorer, mode="continuing")
    assert result["status"] == "NO_COMPARABLE_NATIVE_PATH"
    assert result["sampled_levels_completed"] == []
    assert result["rejected_native_attempts"]
    assert result["native_candidates_examined"] == 1


@pytest.mark.parametrize("field,value", [
    ("native_continuity_ack", False),
    ("native_parent_source_sha256", "f" * 64),
    ("engine_binary_sha256", "c" * 64),
])
def test_sparse_path_rejects_unobserved_respec_or_cross_binary(field, value):
    def evaluator(*, level, parent, mob_count, **kwargs):
        row = receipt(level, mob_count, "A", 10.0, parent)
        if parent:
            row[field] = value
        return [row]

    result = optimize(20, 30, 10, 3, 2, evaluate=evaluator, mode="continuing")
    assert result["status"] == "SAMPLED_NATIVE_PREFIX_ONLY"
    assert result["sampled_levels_completed"] == [20]
    assert len(result["rejected_native_attempts"]) == 1


def test_respects_global_native_candidate_budget_without_overrun():
    invoked = []
    def evaluator(*, level, parent, mob_count, budget, **kwargs):
        invoked.append((level, budget))
        return [receipt(level, mob_count, "A", 10.0, parent)]
    result = optimize(20, 60, 10, 3, 2, evaluate=evaluator, mode="continuing")
    assert invoked == [(20, 1), (30, 1)]
    assert result["native_candidates_examined"] == 2
    assert result["sampled_levels_completed"] == [20, 30]


def test_native_evaluator_cannot_override_budget_or_disable_full_recovery():
    def too_many(*, level, parent, mob_count, **kwargs):
        return [receipt(level, mob_count, "A", 10.0),
                receipt(level, mob_count, "B", 10.0)]
    with pytest.raises(ValueError, match="exceeded candidate budget"):
        optimize(20, 20, 1, 3, 1, evaluate=too_many, mode="continuing")
    with pytest.raises(ValueError, match="terminal recovery invalid"):
        optimize(20, 20, 1, 3, 1, evaluate=too_many, recover_to_full=False, mode="continuing")


def test_one_cli_process_orchestrates_several_native_evaluator_calls(tmp_path, monkeypatch):
    import json
    import subprocess
    from tools import wf_warlock_native_range_optimize as cli

    calls = []

    def fake_run(command, *, input, capture_output, text, timeout, check):
        request = json.loads(input)
        calls.append((command, request))
        level = request["level"]
        parent = request["parent"]
        options = ["A", "B"] if parent is None else [parent["talents"]]
        rows = [receipt(level, request["mob_count"], label, 3.0, parent)
                for label in options]
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(rows))

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    output = tmp_path / "native-range.json"
    code = cli.main([
        "--start-level", "20", "--end-level", "30", "--level-stride", "10",
        "--mob-count", "3", "--budget", "10", "--beam-width", "2",
        "--mode", "continuing",
        "--evaluator-command", "native-scorer --pinned",
        "--out", str(output),
    ])
    report = json.loads(output.read_text())
    assert code == 0
    assert report["sampled_levels_completed"] == [20, 30]
    assert len(report["ranked_alternatives"]) == 2
    assert [request["level"] for _, request in calls] == [20, 30, 30]
    assert all(command == ["native-scorer", "--pinned"] for command, _ in calls)
    assert all(request["recover_to_full"] is True for _, request in calls)
    assert all(request["mob_count"] == 3 and request["rng_mode"] == "balanced"
               and request["iterations"] == 1 for _, request in calls)


def test_native_candidate_budget_is_spread_across_all_requested_levels():
    paid = []

    def eager(*, level, parent, mob_count, budget, **kwargs):
        paid.append((level, budget))
        # Greedy single-level native scorers may spend their entire allocation.
        # Distinct opaque source identities; the optimizer never invents talents.
        return [receipt(level, mob_count, chr(65 + i), 2.0, parent)
                for i in range(budget)]

    report = optimize(20, 60, 10, 3, 100, evaluate=eager, beam_width=3, mode="continuing")
    assert report["sampled_levels_completed"] == [20, 30, 40, 50, 60]
    assert paid[0] == (20, 20)  # Not 100; 4 more levels must have capacity.
    assert report["native_candidates_examined"] <= 100
    assert all(report["native_attempts_by_level"][str(level)] >= 1
               for level in [20, 30, 40, 50, 60])


# Work2's real scored-candidate adapter; these are transport/receipt fixtures,
# not a simulated native battle or a test of Rust gameplay rules.
def _prepared_manifest(tmp_path, *, level=20, labels=("A", "B"),
                       parent_sha=None, native_continuity=False):
    import hashlib
    import json

    entries = []
    for label in labels:
        request_path = tmp_path / f"level{level}-{label}.source.json"
        request_path.write_text(json.dumps({"native_source_candidate": label,
                                            "level": level}) + "\n")
        source_sha = hashlib.sha256(request_path.read_bytes()).hexdigest()
        prepared_path = tmp_path / f"level{level}-{label}.prepared.json"
        prepared_path.write_text(json.dumps({
            "request_sha256": source_sha,
            "player": {"class": "ClassWarlock", "level": level,
                       "stats": {"Health": 100.0, "Mana": 200.0}},
        }) + "\n")
        entry = {"id": label, "level": level,
                 "parent_source_sha256": parent_sha,
                 "source_request": request_path.name,
                 "prepared": prepared_path.name}
        if native_continuity:
            proof = tmp_path / f"level{level}-{label}.continuity.json"
            proof.write_text(json.dumps({
                "source_request_sha256": source_sha,
                "native_parent_source_sha256": parent_sha,
                "native_continuity_from_level": level - 10,
                "native_continuity_ack": True,
                "native_intermediate_levels_verified": True,
            }) + "\n")
            entry["native_continuity_receipt"] = proof.name
        entries.append(entry)
    manifest = tmp_path / f"level{level}.manifest.json"
    manifest.write_text(json.dumps({"entries": entries}) + "\n")
    return manifest


def _fake_native_comparison(call_log, *, drop_terminal=False, fail=False):
    import hashlib
    import json
    import subprocess
    from pathlib import Path

    def run(cmd, *, capture_output, text, timeout, check):
        assert capture_output is True and text is True and not check
        assert "--binary" in cmd and "--out" in cmd
        count = int(cmd[cmd.index("--mob-count") + 1])
        out = Path(cmd[cmd.index("--out") + 1])
        assert out.exists()
        call_log.append(cmd)
        if fail:
            return subprocess.CompletedProcess(cmd, 3, stdout="",
                                               stderr="source-native runtime refused")
        candidates = []
        for offset, argument in enumerate(
                cmd[i + 1] for i, token in enumerate(cmd[:-1])
                if token == "--prepared"):
            cid, pathname = argument.split("=", 1)
            prepared_path = Path(pathname)
            prepared = json.loads(prepared_path.read_text())
            src = prepared["request_sha256"]
            elapsed = 10 + offset
            candidates.append({
                "candidate_id": cid, "prepared_sha256": hashlib.sha256(
                    prepared_path.read_bytes()).hexdigest(),
                "source_sha256": src, "mob_count": count,
                "rng_mode": "balanced", "iterations": 1,
                "status": "MEASURED_NATIVE_FULLY_RECOVERED",
                "elapsed_seconds": float(elapsed),
            })
            raw = {
                "source_sha256": src, "world_targets_killed": count,
                "actual_2d_ack": True,
            }
            if not drop_terminal:
                raw["native_terminal_recovery"] = {
                    "paid": True, "native_clock_accounted": True,
                    "start_clock_ns": int((elapsed - 2) * 1e9),
                    "end_clock_ns": int(elapsed * 1e9),
                    # Selected Rust can report buffed caps beyond prepare.
                    "health_after": 125.0, "mana_after": 250.0,
                    "max_health": 125.0, "max_mana": 250.0,
                }
            (out / f"{cid}.native.json").write_text(json.dumps(raw))
        return subprocess.CompletedProcess(cmd, 0,
            stdout=json.dumps({"candidates": candidates}), stderr="")
    return run


def test_scored_adapter_executes_native_prepared_candidates_and_returns_paid_receipts(tmp_path):
    import json
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request
    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"native-binary-test")
    manifest = _prepared_manifest(tmp_path)
    # Native Rust identifies deterministic protobuf, not raw source JSON.
    # Both distinct native digests must survive adapter + ACK scoring.
    for index, entry in enumerate(json.loads(manifest.read_text())["entries"]):
        prepared_path = tmp_path / entry["prepared"]
        prepared = json.loads(prepared_path.read_text())
        prepared["request_sha256"] = f"{index + 1:064x}"
        prepared_path.write_text(json.dumps(prepared) + "\n")
    calls = []

    def scorer(**kwargs):
        return evaluate_request(kwargs, manifest=manifest, binary=binary,
                                target_hp=400.0, scorer_command=["python", "work1-scorer"],
                                artifact_dir=tmp_path / "artifacts",
                                run_command=_fake_native_comparison(calls))

    result = optimize(20, 20, 1, 3, 2, evaluate=scorer, mode="continuing")
    assert result["status"] == "SAMPLED_NATIVE_PATH_RANKED"
    assert result["native_candidates_examined"] == 2
    assert len(calls) == 1
    assert result["ranked_alternatives"][0]["sampled_cumulative_seconds"] == 10.0
    steps = [r["steps"][0] for r in result["ranked_alternatives"]]
    assert [r["terminal_recovery_seconds"] for r in steps] == [2.0, 2.0]
    assert all(r["receipt"]["native_full_recovery_paid"] is True for r in steps)
    assert all(r["receipt"]["terminal_max_hp"] == 125.0
               and r["receipt"]["terminal_max_mana"] == 250.0 for r in steps)
    assert all(r["receipt"]["source_request_sha256"] for r in steps)
    assert all((tmp_path / "artifacts").exists() for _ in calls)


def test_adapter_honors_original_paid_receipt_path_and_rejects_wrong_digest(tmp_path):
    """Cached native ACKs retain their original filename, not a fresh call label."""
    import hashlib
    import json
    import subprocess
    from pathlib import Path

    from tools.wf_warlock_native_range_scored_adapter import evaluate_request

    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"native-binary-test")
    manifest = _prepared_manifest(tmp_path)
    original_dir = tmp_path / "immutable-paid"
    original_dir.mkdir()
    calls = []
    wrong_digest = False

    def original_paid_scorer(command, **kwargs):
        completed = _fake_native_comparison(calls)(command, **kwargs)
        payload = json.loads(completed.stdout)
        call_dir = Path(command[command.index("--out") + 1])
        for candidate in payload["candidates"]:
            cid = candidate["candidate_id"]
            just_paid = call_dir / f"{cid}.native.json"
            original = original_dir / f"saved-{cid}.native.json"
            just_paid.replace(original)
            candidate["native_raw_receipt_file"] = str(original)
            candidate["native_raw_receipt_sha256"] = (
                "0" * 64 if wrong_digest else hashlib.sha256(original.read_bytes()).hexdigest()
            )
            candidate["reused_exact_native_paid_receipt"] = True
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr="",
        )

    request = {
        "level": 20, "parent": None, "budget": 2, "mob_count": 3,
        "rng_mode": "balanced", "iterations": 1, "recover_to_full": True,
        "search_mode": "independent",
    }

    def evaluate():
        return evaluate_request(
            request, manifest=manifest, binary=binary, target_hp=400.0,
            scorer_command=["native-scorer"], artifact_dir=tmp_path / "attempts",
            run_command=original_paid_scorer,
        )

    paid = evaluate()
    assert len(calls) == 1
    assert len(paid) == 2
    assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED" for row in paid)
    assert all(row["reused_exact_native_paid_receipt"] is True for row in paid)
    assert all(Path(row["native_raw_receipt_file"]).parent == original_dir for row in paid)
    assert all(hashlib.sha256(Path(row["native_raw_receipt_file"]).read_bytes()).hexdigest()
               == row["native_raw_receipt_sha256"] for row in paid)

    wrong_digest = True
    refused = evaluate()
    assert len(calls) == 2
    assert all(row["status"].startswith(
        "NATIVE_SCORER_RECEIPT_REFUSAL:NATIVE_SCORER_ORIGINAL_RECEIPT_DIGEST_MISMATCH"
    ) for row in refused)


def test_independent_paid_rankings_keep_exact_requested_build_fields(tmp_path):
    """A real ranked result must expose the native source build, not nulls."""
    import hashlib
    import json

    from tools.wf_warlock_native_range_scored_adapter import evaluate_request

    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"pinned-native-binary")
    manifest = _prepared_manifest(tmp_path)
    for index, entry in enumerate(json.loads(manifest.read_text())["entries"]):
        source = manifest.parent / entry["source_request"]
        prepared_path = manifest.parent / entry["prepared"]
        player = {
            "class": "ClassWarlock", "level": 20,
            "talentsString": ("110-0-0" if index == 0 else "0-110-0"),
            "equipment": {"items": [{"id": 100 + index}]},
            "rotation": {"priorityList": [{"action": {"castSpell": {
                "spellId": {"spellId": 101 + index}}}}]},
            "warlock": {"options": {"classOptions": {"summon": 3 + index}}},
        }
        source.write_text(json.dumps({
            "raid": {"parties": [{"players": [player]}]},
            "encounter": {"targets": [{"level": 20}]},
        }) + "\n")
        prepared = json.loads(prepared_path.read_text())
        prepared["request_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        prepared_path.write_text(json.dumps(prepared) + "\n")

    observed = []
    def evaluator(**request):
        return evaluate_request(
            request, manifest=manifest, binary=binary, target_hp=400.0,
            scorer_command=["native-work1-scorer"], artifact_dir=tmp_path / "paid",
            run_command=_fake_native_comparison(observed),
        )

    report = optimize(20, 20, 1, 3, 2, evaluate=evaluator, mode="independent")
    assert report["status"] == "INDEPENDENT_NATIVE_ANCHORS_RANKED"
    assert len(observed) == 1
    assert report["ranked_alternatives"] == []  # Not stitched into a route.
    builds = report["independent_level_rankings"]["20"]
    assert [r["talents"] for r in builds] == ["110-0-0", "0-110-0"]
    assert [r["pet"] for r in builds] == [3, 4]
    assert [r["gear"]["items"][0]["id"] for r in builds] == [100, 101]
    assert [r["apl"]["priorityList"][0]["action"]["castSpell"]["spellId"]["spellId"]
            for r in builds] == [101, 102]
    for ranked in builds:
        raw = ranked["receipt"]
        assert raw["talents"] == ranked["talents"]
        assert raw["pet"] == ranked["pet"]
        assert raw["gear"] == ranked["gear"]
        assert raw["apl"] == ranked["apl"]
        source = __import__("pathlib").Path(raw["source_request_file"])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == ranked["source_request_sha256"]


@pytest.mark.parametrize("mode", ["independent", "continuing"])
def test_single_prepared_root_scores_paid_mobs_without_unearned_winner(tmp_path, mode):
    """One Rust-prepared root is measurable even when alternatives refuse.

    A single genuine fully recovered native sample remains provisional, not
    proof of a performance-optimized or continuously played leveling route.
    """
    import json

    from tools.wf_warlock_native_range_scored_adapter import evaluate_request

    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"pinned-native")
    manifest = _prepared_manifest(tmp_path, labels=("only",))
    source = json.loads(manifest.read_text())
    source["refusals"] = [{
        "candidate_id": "alternative", "status": "NATIVE_PREPARE_REFUSED",
        "native_refusal": "Rust declined alternate build",
    }]
    manifest.write_text(json.dumps(source))
    paid = []

    def native_run(binary_arg, prepared_path, **params):
        prepared = json.loads(prepared_path.read_text())
        paid.append(params)
        return {
            "source_sha256": prepared["request_sha256"],
            "world_target_hp": 400.0, "world_targets_killed": 3,
            "continuous_native_actor": True, "actual_2d_ack": True,
            "native_recovery_clock_accounted": True,
            "native_recovery_mode": "decisions_food_water",
            "paid_recovery": True,
            "native_health_damage": {
                "observed": True, "damage_taken": 30.0, "damage_events": 3},
            "native_windows": [
                {"index": i, "native_kill_ns": (i + 1) * 1_000_000_000,
                 "actor_health": 80.0} for i in range(3)
            ],
            "native_actor_mana_after_world_kills": [120.0] * 3,
            "world_elapsed_seconds": 3.0,
            "native_terminal_recovery": {
                "paid": True, "native_clock_accounted": True,
                "start_clock_ns": 3_000_000_000,
                "end_clock_ns": 5_000_000_000,
                "health_before": 80.0, "mana_before": 120.0,
                "health_after": 100.0, "mana_after": 200.0,
                "max_health": 100.0, "max_mana": 200.0,
            },
        }

    def evaluator(**request):
        return evaluate_request(
            request, manifest=manifest, binary=binary, target_hp=400.0,
            scorer_command=["work1-native-scorer"],
            artifact_dir=tmp_path / "raw", run_native_single=native_run,
        )

    report = optimize(20, 20, 1, 3, 2, evaluate=evaluator, mode=mode)
    assert len(paid) == 1
    assert paid[0]["target_count"] == 3
    assert paid[0]["recovery_policy"] == "decisions"
    assert paid[0]["health_threshold"] == paid[0]["mana_threshold"] == 1.0
    assert report["status"] == (
        "INDEPENDENT_NATIVE_ANCHORS_PARTIAL" if mode == "independent"
        else "SAMPLED_NATIVE_PREFIX_ONLY"
    )
    assert report["sampled_levels_completed"] == [20]
    assert report["native_candidates_examined"] == 2
    if mode == "independent":
        assert report["ranked_alternatives"] == []
        ranks = report["independent_level_rankings"]["20"]
        assert len(ranks) == 1
        assert ranks[0]["native_elapsed_seconds"] == 5.0
        assert ranks[0]["terminal_recovery_seconds"] == 2.0
        assert ranks[0]["continuity_unverified"] is True
    else:
        assert len(report["ranked_alternatives"]) == 1
        step = report["ranked_alternatives"][0]["steps"][0]
        assert step["native_elapsed_seconds"] == 5.0
        assert step["terminal_recovery_seconds"] == 2.0
        assert step["receipt"]["native_world_ack"] is True
        assert step["receipt"]["native_full_recovery_paid"] is True
    assert report["rejected_native_attempts"][0]["native_status"] == "NATIVE_PREPARE_REFUSED"


def test_scored_adapter_does_not_pay_unproved_sparse_ancestry(tmp_path):
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request
    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"native-binary-test")
    calls = []
    manifest = _prepared_manifest(tmp_path, level=30, parent_sha="a" * 64)
    request = {"level": 30, "parent": {"level": 20,
               "source_request_sha256": "a" * 64},
               "mob_count": 3, "budget": 2, "rng_mode": "balanced",
               "iterations": 1, "recover_to_full": True}
    result = evaluate_request(request, manifest=manifest, binary=binary,
                              target_hp=400.0, scorer_command=["work1-scorer"],
                              artifact_dir=tmp_path / "receipts",
                              run_command=_fake_native_comparison(calls))
    assert len(result) == 2
    assert all("CONTINUITY" in r["status"] for r in result)
    assert calls == []


def test_scored_adapter_accepts_only_native_recorded_sparse_ancestry(tmp_path):
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request
    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"native-binary-test")
    parent_sha = "a" * 64
    manifest = _prepared_manifest(tmp_path, level=30, parent_sha=parent_sha,
                                  native_continuity=True)
    calls = []
    request = {"level": 30, "parent": {"level": 20,
                "source_request_sha256": parent_sha},
               "mob_count": 3, "budget": 2, "rng_mode": "balanced",
               "iterations": 1, "recover_to_full": True}
    result = evaluate_request(request, manifest=manifest, binary=binary,
                              target_hp=400.0, scorer_command=["work1-scorer"],
                              artifact_dir=tmp_path / "receipts",
                              run_command=_fake_native_comparison(calls))
    assert len(calls) == 1
    assert len(result) == 2
    assert all(r["native_continuity_ack"] is True for r in result)
    assert all(r["native_intermediate_levels_verified"] is True for r in result)
    assert all(r["native_parent_source_sha256"] == parent_sha for r in result)


def test_scored_adapter_never_converts_missing_native_terminal_to_free_recovery(tmp_path):
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request
    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"native-binary-test")
    manifest = _prepared_manifest(tmp_path)
    calls = []

    def evaluator(**kwargs):
        return evaluate_request(kwargs, manifest=manifest, binary=binary,
                                target_hp=400.0, scorer_command=["work1-scorer"],
                                artifact_dir=tmp_path / "artifacts",
                                run_command=_fake_native_comparison(
                                    calls, drop_terminal=True))
    result = optimize(20, 20, 1, 3, 2, evaluate=evaluator, mode="continuing")
    assert len(calls) == 1
    assert result["status"] == "NO_COMPARABLE_NATIVE_PATH"
    assert len(result["rejected_native_attempts"]) == 2


def test_scored_adapter_preserves_native_scorer_failure_without_fake_scores(tmp_path):
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request
    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"native-binary-test")
    manifest = _prepared_manifest(tmp_path)
    calls = []
    result = evaluate_request(
        {"level": 20, "parent": None, "mob_count": 3, "budget": 2,
         "rng_mode": "balanced", "iterations": 1, "recover_to_full": True},
        manifest=manifest, binary=binary, target_hp=400.0,
        scorer_command=["work1-scorer"], artifact_dir=tmp_path / "receipts",
        run_command=_fake_native_comparison(calls, fail=True))
    assert len(calls) == 1
    assert len(result) == 2
    assert all(r["native_prepared"] is False for r in result)
    assert all("NATIVE_SCORER_EXIT_3" in r["status"] for r in result)


def test_one_call_cli_directly_runs_work1_native_scorer_manifest_adapter(tmp_path, monkeypatch):
    import json
    from tools import wf_warlock_native_range_optimize as cli
    from tools import wf_warlock_native_range_scored_adapter as adapter

    calls = []

    def checked_adapter(request, *, manifest, binary, target_hp,
                        scorer_command, artifact_dir, paid_cache_dir):
        assert paid_cache_dir == tmp_path / "raw-receipts" / "paid-cache"
        assert paid_cache_dir.is_dir()
        calls.append((request["level"], request["parent"],
                      request["mob_count"], target_hp, scorer_command))
        parent = request["parent"]
        return [
            receipt(request["level"], request["mob_count"], label, 2.0,
                    parent, recovery=0.5)
            for label in (("A", "B") if parent is None else (parent["talents"],))
        ]

    monkeypatch.setattr(adapter, "evaluate_request", checked_adapter)
    output = tmp_path / "scored-route.json"
    code = cli.main([
        "--start-level", "20", "--end-level", "30", "--level-stride", "10",
        "--mob-count", "3", "--budget", "10", "--beam-width", "2",
        "--mode", "continuing",
        "--native-prepared-manifest", str(tmp_path / "manifest.json"),
        "--native-binary", str(tmp_path / "pinned-rust"),
        "--native-target-hp", "400", "--native-receipts-dir",
        str(tmp_path / "raw-receipts"),
        "--native-scorer-command", "python existing-work1-native-scorer.py",
        "--out", str(output),
    ])
    report = json.loads(output.read_text())
    assert code == 0
    assert report["status"] == "SAMPLED_NATIVE_PATH_RANKED"
    assert report["sampled_levels_completed"] == [20, 30]
    assert [call[0] for call in calls] == [20, 30, 30]
    assert all(call[2:] == (3, 400.0, ["python", "existing-work1-native-scorer.py"])
               for call in calls)


def test_one_call_cli_manifest_mode_requires_real_native_source_inputs(tmp_path):
    from tools import wf_warlock_native_range_optimize as cli
    with pytest.raises(SystemExit, match="2"):
        cli.main([
            "--native-prepared-manifest", str(tmp_path / "manifest.json"),
            "--out", str(tmp_path / "out.json"),
        ])


def test_scored_adapter_malformed_source_prevents_paid_native_invocation(tmp_path):
    import json
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request
    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"native-binary-test")
    manifest = _prepared_manifest(tmp_path)
    root = json.loads(manifest.read_text())
    for entry in root["entries"]:
        request_file = tmp_path / entry["source_request"]
        request_file.write_text(request_file.read_text() + "new native source bytes")
    calls = []
    result = evaluate_request(
        {"level": 20, "parent": None, "mob_count": 3, "budget": 2,
         "rng_mode": "balanced", "iterations": 1, "recover_to_full": True},
        manifest=manifest, binary=binary, target_hp=400.0,
        scorer_command=["work1-scorer"], artifact_dir=tmp_path / "raw",
        run_command=_fake_native_comparison(calls))
    assert calls == []
    assert len(result) == 2
    # Invalid JSON must still refuse before native combat; it must not be
    # mislabeled as a comparison of protobuf and JSON-file SHA digests.
    assert all("NATIVE_PREPARED_OR_CONTINUITY_REFUSAL" in r["status"]
               for r in result)


def test_scored_adapter_native_timeout_is_retained_as_unscored_refusal(tmp_path):
    import subprocess
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request
    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"native-binary-test")
    manifest = _prepared_manifest(tmp_path)

    def timed_out(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1800)

    result = evaluate_request(
        {"level": 20, "parent": None, "mob_count": 3, "budget": 2,
         "rng_mode": "balanced", "iterations": 1, "recover_to_full": True},
        manifest=manifest, binary=binary, target_hp=400.0,
        scorer_command=["work1-scorer"], artifact_dir=tmp_path / "raw",
        run_command=timed_out)
    assert len(result) == 2
    assert all("NATIVE_SCORER_TRANSPORT_ERROR" in r["status"] for r in result)
    assert all(r["native_prepared"] is False for r in result)


def test_range_report_retains_candidate_id_and_native_failure_detail():
    def native_refusal(*, level, parent, mob_count, **kwargs):
        return [{"candidate_id": "affliction", "source_request_sha256": "f" * 64,
                 "status": "NATIVE_TERMINAL_FULL_RECOVERY_NOT_RECORDED",
                 "native_refusal": "native source returned no post-final-kill recovery",
                 "native_prepared": False}]
    report = optimize(20, 20, 1, 3, 1, evaluate=native_refusal, mode="continuing")
    assert report["status"] == "NO_COMPARABLE_NATIVE_PATH"
    row = report["rejected_native_attempts"][0]
    assert row["candidate_id"] == "affliction"
    assert row["native_status"] == "NATIVE_TERMINAL_FULL_RECOVERY_NOT_RECORDED"
    assert row["native_refusal"] == "native source returned no post-final-kill recovery"



def test_scored_adapter_keeps_single_native_successor_for_a_competing_parent(tmp_path):
    """Single child per parent must not kill the surviving two-path beam."""
    import json
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request

    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"exact-native-binary")
    parent_sha = "a" * 64
    manifest = _prepared_manifest(
        tmp_path, level=30, labels=("only",), parent_sha=parent_sha,
        native_continuity=True)
    observed = []

    def native_runner(binary_arg, prepared_arg, **kwargs):
        observed.append((binary_arg, prepared_arg, kwargs))
        prepared = json.loads(prepared_arg.read_text())
        return {
            "source_sha256": prepared["request_sha256"],
            "world_target_hp": 400.0,
            "world_targets_killed": 3,
            "continuous_native_actor": True,
            "actual_2d_ack": True,
            "native_recovery_clock_accounted": True,
            "native_recovery_mode": "decisions_food_water",
            "paid_recovery": True,
            # Work1's shared scorer now requires genuine hostile source damage
            # in addition to ACK kills and fully charged terminal restoration.
            "native_health_damage": {
                "observed": True, "damage_taken": 30.0, "damage_events": 3},
            "native_windows": [
                {"index": i, "native_kill_ns": (i + 1) * 1_000_000_000,
                 "actor_health": 80.0} for i in range(3)
            ],
            "native_actor_mana_after_world_kills": [120.0] * 3,
            "world_elapsed_seconds": 3.0,
            "native_terminal_recovery": {
                "paid": True, "native_clock_accounted": True,
                "start_clock_ns": 3_000_000_000,
                "end_clock_ns": 5_000_000_000,
                "health_before": 80.0, "mana_before": 120.0,
                "health_after": 100.0, "mana_after": 200.0,
                "max_health": 100.0, "max_mana": 200.0,
            },
        }

    def no_batch_scorer(*args, **kwargs):
        raise AssertionError("single continuation must not invoke two-candidate CLI")

    rows = evaluate_request(
        {"level": 30, "parent": {"level": 20,
                                 "source_request_sha256": parent_sha},
         "mob_count": 3, "budget": 1, "rng_mode": "balanced",
         "iterations": 1, "recover_to_full": True},
        manifest=manifest, binary=binary, target_hp=400.0,
        scorer_command=["work1-native-scorer"], artifact_dir=tmp_path / "raw",
        run_command=no_batch_scorer, run_native_single=native_runner)
    assert len(observed) == 1
    assert observed[0][2] == {
        "target_count": 3, "mob_health": 400.0, "rng_mode": "balanced",
        "recovery_policy": "decisions", "health_threshold": 1.0,
        "mana_threshold": 1.0, "require_native_health_damage": False,
    }
    assert len(rows) == 1
    row = rows[0]
    assert row["native_prepared"] is True
    assert row["native_full_recovery_paid"] is True
    assert row["elapsed_seconds"] == 5.0
    assert row["terminal_recovery_seconds"] == 2.0
    assert row["native_parent_source_sha256"] == parent_sha
    assert row["native_continuity_ack"] is True
    assert json.loads(
        (tmp_path / "raw").glob("level-30-native-*").__next__().joinpath(
            "only.native.json").read_text())["world_targets_killed"] == 3


def test_single_native_successor_never_gets_free_terminal_recovery(tmp_path):
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request

    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"exact-native-binary")
    parent_sha = "a" * 64
    manifest = _prepared_manifest(
        tmp_path, level=30, labels=("only",), parent_sha=parent_sha,
        native_continuity=True)
    # An ACK alone is not a valid paid terminal full-resource receipt.
    def incomplete_native(*args, **kwargs):
        return {"source_sha256": "x" * 64, "world_targets_killed": 3,
                "actual_2d_ack": True}

    rows = evaluate_request(
        {"level": 30, "parent": {"level": 20,
                                 "source_request_sha256": parent_sha},
         "mob_count": 3, "budget": 1, "rng_mode": "balanced",
         "iterations": 1, "recover_to_full": True},
        manifest=manifest, binary=binary, target_hp=400.0,
        scorer_command=["work1-native-scorer"], artifact_dir=tmp_path / "raw",
        run_native_single=incomplete_native)
    assert len(rows) == 1
    assert rows[0]["native_prepared"] is False
    assert "INCOMPLETE_NATIVE_WORLD" in rows[0]["status"]

def test_live_scored_adapter_reuses_paid_ack_across_fresh_call_dirs(tmp_path, monkeypatch):
    """The real adapter consumes Work1's stable cache, not a temp-dir label."""
    import hashlib
    import json
    import subprocess
    from pathlib import Path

    import tools.wf_warlock_native_candidate_scoring as scorer
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request

    binary = tmp_path / "native-engine"
    binary.write_bytes(b"selected-rust-v1")
    manifest = _prepared_manifest(tmp_path)
    cache = tmp_path / "paid-cache"
    native_kills = []

    def identity(executable, *, actor_level, mob_count, target_hp):
        return {
            "cache_schema": 1, "forever_commit": "f" * 40,
            "native_binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "actor_level": actor_level, "mob_count": mob_count,
            "target_hp": target_hp, "rng_mode": "balanced", "iterations": 1,
            "recovery_policy": "decisions", "health_threshold": 1.0,
            "mana_threshold": 1.0, "require_native_health_damage": False,
        }

    monkeypatch.setattr(scorer, "_exact_paid_cache_identity", identity)

    def native(executable, source, **kwargs):
        native_kills.append((source.name, kwargs["target_count"]))
        source_sha = json.loads(source.read_text())["request_sha256"]
        return {
            "source_sha256": source_sha,
            "world_target_hp": kwargs["mob_health"],
            "world_targets_killed": kwargs["target_count"],
            "continuous_native_actor": True,
            "actual_2d_ack": True,
            "paid_recovery": True,
            "native_recovery_clock_accounted": True,
            "native_recovery_mode": "decisions_food_water",
            "native_health_damage": {
                "observed": True, "damage_taken": 20., "damage_events": 3},
            "native_windows": [
                {"index": i, "native_kill_ns": (i + 1) * 1_000_000_000,
                 "actor_health": 80.} for i in range(3)],
            "native_actor_mana_after_world_kills": [120.] * 3,
            "world_elapsed_seconds": 3.,
            "native_terminal_recovery": {
                "paid": True, "native_clock_accounted": True,
                "start_clock_ns": 3_000_000_000,
                "end_clock_ns": 5_000_000_000,
                "health_before": 80., "mana_before": 120.,
                "health_after": 100., "mana_after": 200.,
                "max_health": 100., "max_mana": 200.,
            },
        }

    def run_scorer(cmd, **kwargs):
        assert "--paid-cache-dir" in cmd
        prepared = dict(arg.split("=", 1) for i, token in enumerate(cmd[:-1])
                        if token == "--prepared" for arg in [cmd[i + 1]])
        screen = scorer.compare_prepared_candidates(
            binary=binary, prepared_paths={
                cid: Path(filename) for cid, filename in prepared.items()},
            actor_level=int(cmd[cmd.index("--level") + 1]),
            mob_count=int(cmd[cmd.index("--mob-count") + 1]),
            target_hp=float(cmd[cmd.index("--target-hp") + 1]),
            run_native=native,
            artifact_dir=Path(cmd[cmd.index("--out") + 1]),
            paid_cache_dir=Path(cmd[cmd.index("--paid-cache-dir") + 1]))
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(screen),
                                           stderr="")

    request = {
        "level": 20, "parent": None, "budget": 2, "mob_count": 3,
        "rng_mode": "balanced", "iterations": 1, "recover_to_full": True,
    }

    def evaluate():
        return evaluate_request(
            request, manifest=manifest, binary=binary, target_hp=400.,
            scorer_command=["native-scorer"], artifact_dir=tmp_path / "invocations",
            paid_cache_dir=cache, run_command=run_scorer)

    first = evaluate()
    assert len(native_kills) == 2
    assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED" for row in first)
    assert all(not row["reused_exact_native_paid_receipt"] for row in first)
    original_files = [row["native_raw_receipt_file"] for row in first]
    assert all(Path(file).parent == cache for file in original_files)

    second = evaluate()
    assert len(native_kills) == 2  # zero new paid hostile chains
    assert all(row["reused_exact_native_paid_receipt"] for row in second)
    assert [row["native_raw_receipt_file"] for row in second] == original_files
    assert all(row["terminal_hp"] == row["terminal_max_hp"]
               and row["terminal_mana"] == row["terminal_max_mana"]
               and row["elapsed_seconds"] == 5. for row in second)

    binary.write_bytes(b"selected-rust-v2")
    changed = evaluate()
    assert len(native_kills) == 4
    assert all(not row["reused_exact_native_paid_receipt"] for row in changed)


def test_sparse_paid_parent_ack_does_not_require_unmeasured_intermediate_levels():
    parent = receipt(20, 2, "A", 8.0)
    child = receipt(40, 2, "A", 9.0, parent)
    child.pop("native_intermediate_levels_verified")
    assert _receipt_error(
        child, level=40, parent=parent, mob_count=2,
        rng_mode="balanced", iterations=1,
    ) is None
    child["native_continuity_ack"] = False
    assert _receipt_error(
        child, level=40, parent=parent, mob_count=2,
        rng_mode="balanced", iterations=1,
    ) == "native continuing talent/actor edge unproved"


def test_m05_same_native_optimizer_dispatch_and_paid_cache_reuse():
    """The live density runner must not turn PR updates into repeated paid work."""
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
                / "native-paid-route-regressions.yml").read_text()
    m05 = workflow.split("  sparse-optimizer-real:\n", 1)[1]
    assert "github.event.action == 'reopened'" in m05
    assert "github.event.action == 'opened'" in m05
    assert "m05_stride:" in workflow and "m05_cache_run_id:" in workflow
    assert '--start-level 20 --end-level 60 --level-stride "$M05_STRIDE"' in m05
    assert '--n-mobs 2 --recover-at-end true --rng balanced' in m05
    assert '--backend rust --budget "$M05_BUDGET"' in m05
    assert "inputs.m05_stride == '1' && '450'" in m05
    assert "inputs.m05_stride == '5' && '110'" in m05
    assert "requested-sparse-optimize-42980239306" in m05
    assert "requested-m05-optimize-{0}" in m05
    assert "inputs.m05_cache_run_id || '42980239306'" in m05
    assert "if: always()" in m05 and "path: project/runs/" in m05
    assert "dd53c747abca5bb86ba2bfe0c8090dffd7f5e1c9" in m05


@pytest.mark.parametrize("mode", ["independent", "continuing", "compatible"])
def test_single_beam_pays_real_samples_without_inventing_competition(mode):
    """A one-slot beam is a valid search limit, not a native refusal.

    One authentic sampled path is provisional; it must not be called a
    performance-ranked competition or a continuously simulated journey.
    """
    calls = []

    def evaluator(*, level, parent, mob_count, **kwargs):
        calls.append((level, parent is not None))
        row = receipt(level, mob_count, "A", 7.0, parent, recovery=2.0)
        row["talents"] = "100-0-0"  # source-prepared allocation, opaque to this test
        return [row]

    result = optimize(20, 40, 20, 2, 2, evaluate=evaluator,
                      beam_width=1, mode=mode)
    assert result["status"] == {
        "independent": "INDEPENDENT_NATIVE_ANCHORS_PARTIAL",
        "continuing": "SAMPLED_NATIVE_PREFIX_ONLY",
        "compatible": "SAMPLED_COMPATIBLE_PATH_PROVISIONAL",
    }[mode]
    assert result["native_candidates_examined"] == 2
    assert result["sampled_levels_completed"] == [20, 40]
    assert result["rejected_native_attempts"] == []
    assert calls == ([(20, False), (40, True)] if mode == "continuing"
                     else [(20, False), (40, False)])
    if mode == "independent":
        assert result["ranked_alternatives"] == []
        assert all(len(result["independent_level_rankings"][str(level)]) == 1
                   for level in (20, 40))
    else:
        assert len(result["ranked_alternatives"]) == 1
        assert result["ranked_alternatives"][0]["sampled_cumulative_seconds"] == 14.0
        assert all(step["receipt"]["native_full_recovery_paid"] is True
                   for step in result["ranked_alternatives"][0]["steps"])


def test_compatible_optimizer_does_not_require_optional_native_hint_api():
    """A no-hint native scorer must not crash or pay fake backseed searches."""
    called = []

    def evaluate(*, level, parent, mob_count, budget, rng_mode, iterations,
                 recover_to_full, search_mode):
        assert parent is None and search_mode == "independent"
        called.append(level)
        row = receipt(level, mob_count, "A" if level == 20 else "B", 9.0)
        row["talents"] = "100-0-0" if level == 20 else "010-0-0"
        return [row]

    result = optimize(20, 40, 20, 2, 12, evaluate=evaluate, mode="compatible")
    assert result["status"] == "NO_COMPLETE_COMPATIBLE_SAMPLED_PATH"
    assert result["sampled_levels_completed"] == [20, 40]
    assert result["sampled_levels_compatible"] == [20]
    assert result["native_candidates_examined"] == 2
    assert result["backward_seeded_native_attempts"] == 0
    assert called == [20, 40]


def test_sampled_guide_uses_paid_native_receipts_without_continuous_route_claim():
    import hashlib
    import json
    from src.v2.native_range_optimizer import main

    seen = []

    def evaluator(*, level, parent, mob_count, budget, rng_mode,
                  iterations, recover_to_full, **kwargs):
        assert parent is None and mob_count == 2
        assert rng_mode == "balanced" and iterations == 1
        assert recover_to_full is True
        seen.append(level)
        out = []
        for talent, score in (("1-0-0", 5.0), ("2-0-0", 6.0)):
            row = receipt(level, mob_count, "A", score)
            row["source_request_sha256"] = hashlib.sha256(
                f"{level}/{talent}".encode()).hexdigest()
            row["talents"] = (talent if level == 20
                              else ("11-0-0" if talent == "1-0-0" else "21-0-0"))
            row["gear"] = {"items": [{"id": 1234}]}
            row["apl"] = {"priorityList": [{"action": {"castSpell": {"spellId": 42}}}]}
            row["pet"] = "Imp"
            out.append(row)
        return out

    # Temporary native-world stand-ins only test serialization and guide
    # presentation. They are not published as genuine measured gameplay.
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        result_path = root / "result.json"
        guide_path = root / "nested" / "GUIDE.md"
        code = main([
            "--class", "warlock", "--tree", "unconstrained",
            "--start-level", "20", "--end-level", "21",
            "--level-stride", "1", "--n-mobs", "2",
            "--budget", "10", "--out", str(result_path),
            "--guide-out", str(guide_path),
        ], evaluate=evaluator)
        assert code == 0
        assert seen == [20, 21]  # one request, no additional paid guide calls
        result = json.loads(result_path.read_text())
        assert result["sampled_levels_compatible"] == [20, 21]
        guide = guide_path.read_text()
        assert "Level 20" in guide and "Level 21" in guide
        assert "tree 1, slot 2: +1" in guide
        assert "1234" in guide and "Imp" in guide
        assert "Native APL" in guide
        assert "2 hostile mob(s)" in guide
        assert "Not a continuous leveling route" in guide
        assert f"{result['ranked_alternatives'][0]['sampled_cumulative_seconds']:.3f} s" in guide
        assert result["full_10_60_continuous_leveling_route_proven"] is False

        # No-Rust, no-new-paid-work consumption of the existing --out JSON.
        import subprocess
        import sys
        offline = root / "offline" / "GUIDE.md"
        executed = subprocess.run([
            sys.executable, "-m", "src.v2.runner", "native-guide",
            "--in", str(result_path), "--out", str(offline),
        ], capture_output=True, text=True, check=False)
        assert executed.returncode == 0, executed.stderr
        assert offline.read_text() == guide
        assert seen == [20, 21]

        # A copied/modified JSON cannot be presented as the original paid
        # measurements, even if its level list remains complete.
        from copy import deepcopy
        from src.v2.native_range_optimizer import render_sampled_build_guide
        bad = deepcopy(result)
        bad["ranked_alternatives"][0]["steps"][0]["receipt"]["native_full_recovery_paid"] = False
        with pytest.raises(ValueError, match="unpaid or refused native receipt"):
            render_sampled_build_guide(bad)
        bad = deepcopy(result)
        bad["ranked_alternatives"][0]["steps"][0]["native_elapsed_seconds"] += 10
        with pytest.raises(ValueError, match="elapsed/recovery disagrees"):
            render_sampled_build_guide(bad)
        bad = deepcopy(result)
        bad["ranked_alternatives"][1]["sampled_cumulative_seconds"] += 1
        with pytest.raises(ValueError, match="cumulative score disagrees"):
            render_sampled_build_guide(bad)
        bad = deepcopy(result)
        del bad["ranked_alternatives"][0]["steps"][0]["receipt"]
        with pytest.raises(ValueError, match="original native paid receipts"):
            render_sampled_build_guide(bad)
        assert seen == [20, 21]  # validation never starts new native work


def test_sampled_guide_refuses_unmeasured_or_partial_path():
    from src.v2.native_range_optimizer import render_sampled_build_guide
    with pytest.raises(ValueError, match="without a measured compatible path"):
        render_sampled_build_guide({"ranked_alternatives": []})
    with pytest.raises(ValueError, match="incomplete sampled path"):
        render_sampled_build_guide({
            "ranked_alternatives": [{"steps": [{"level": 20}]}],
            "sampled_levels_requested": [20, 21],
        })
