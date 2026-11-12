"""Forever-owned competitive native scoring; no mechanics or world replay in tests."""
import copy
import hashlib
import json
from pathlib import Path

from tools.wf_warlock_native_candidate_scoring import (
    compare_prepared_candidates, score_native_chain,
)


def _prepared(sha, level=30):
    return {"request_sha256": sha, "player": {
        "class": "ClassWarlock", "level": level,
        "stats": {"Health": 1000.0, "Mana": 1500.0}}}


def _receipt(sha, *, kill_seconds=15, recovery_seconds=5, last_mana=900):
    clocks = [int(x * 1e9) for x in (5, 10, kill_seconds)]
    return {"source_sha256": sha, "world_target_hp": 1200.,
            "world_targets_killed": 3, "continuous_native_actor": True,
            "actual_2d_ack": True, "paid_recovery": True,
            "native_recovery_clock_accounted": True,
            "native_recovery_mode": "decisions_food_water",
            "native_health_damage": {
                "observed": True, "damage_taken": 125.0, "damage_events": 3},
            "world_elapsed_seconds": kill_seconds,
            "native_windows": [
                {"index": i, "native_kill_ns": ns, "actor_health": 600.}
                for i, ns in enumerate(clocks)],
            "native_actor_mana_after_world_kills": [1100., 1000., last_mana],
            "native_terminal_recovery": {
                "paid": True, "native_clock_accounted": True,
                "start_clock_ns": clocks[-1],
                "end_clock_ns": int((kill_seconds + recovery_seconds) * 1e9),
                "health_before": 600., "mana_before": last_mana,
                "health_after": 1000., "mana_after": 1500.,
                "max_health": 1000., "max_mana": 1500.,
            }}


def test_later_native_faster_candidate_beats_first_preparable(tmp_path):
    files = {}
    for cid in ("first", "later", "third"):
        path = tmp_path / f"{cid}.json"
        path.write_text(json.dumps(_prepared(cid[0] * 64)))
        files[cid] = path
    paid = {"first": (18, 12), "later": (16, 2), "third": (17, 5)}
    calls = []

    def run(binary, path, **kwargs):
        cid = path.stem
        calls.append((cid, kwargs))
        combat, recovery = paid[cid]
        return _receipt(cid[0] * 64, kill_seconds=combat,
                        recovery_seconds=recovery)

    output = compare_prepared_candidates(binary=Path("source-native"),
                                         prepared_paths=files, actor_level=30,
                                         mob_count=3, target_hp=1200.,
                                         run_native=run, artifact_dir=tmp_path / "receipts")
    assert output["winner_candidate_id"] == "later"
    assert output["winner_elapsed_seconds"] == 18
    assert output["comparable_candidates"] == 3
    assert [cid for cid, _ in calls] == ["first", "later", "third"]
    assert all(kw["rng_mode"] == "balanced" and kw["target_count"] == 3
               and kw["health_threshold"] == kw["mana_threshold"] == 1.0
               and kw["recovery_policy"] == "decisions"
               and kw["require_native_health_damage"] is False for _, kw in calls)
    assert len(list((tmp_path / "receipts").glob("*.native.json"))) == 3
    # Per-candidate native breakdown is part of the scored output: Work2
    # can consume the paid post-kill debt without reconstructing a model.
    first, later = output["candidates"][:2]
    assert first["world_elapsed_before_terminal_seconds"] == 18
    assert first["terminal_recovery_seconds"] == 12
    assert later["world_elapsed_before_terminal_seconds"] == 16
    assert later["terminal_recovery_seconds"] == 2
    assert later["elapsed_seconds"] == (
        later["world_elapsed_before_terminal_seconds"]
        + later["terminal_recovery_seconds"])
    assert later["terminal_health"] == later["terminal_max_health"] == 1000
    assert later["terminal_mana"] == later["terminal_max_mana"] == 1500
    receipt_path = Path(later["native_raw_receipt_file"])
    assert receipt_path == tmp_path / "receipts" / "later.native.json"
    assert later["native_raw_receipt_sha256"] == hashlib.sha256(
        receipt_path.read_bytes()).hexdigest()


def test_terminal_time_changes_winner_even_when_combat_is_faster(tmp_path):
    paths = {}
    for name in ("combat_fast", "fully_fast"):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(_prepared(name[0] * 64)))
        paths[name] = path

    def runner(binary, path, **kwargs):
        if path.stem == "combat_fast":
            return _receipt("c" * 64, kill_seconds=12, recovery_seconds=14)
        return _receipt("f" * 64, kill_seconds=16, recovery_seconds=3)

    result = compare_prepared_candidates(binary=Path("rust"), prepared_paths=paths,
                                         actor_level=30, mob_count=3,
                                         target_hp=1200., run_native=runner)
    assert result["winner_candidate_id"] == "fully_fast"
    assert result["winner_elapsed_seconds"] == 19



def test_native_resource_caps_take_precedence_over_prepared_base_stats():
    prepared = _prepared("a" * 64)
    result = _receipt("a" * 64)
    terminal = result["native_terminal_recovery"]
    # A source-native buff raises live caps beyond prepared base stats.
    terminal.update(health_after=1200.0, mana_after=1700.0,
                    max_health=1200.0, max_mana=1700.0)
    assert score_native_chain(result, prepared, mob_count=3,
                              expected_target_hp=1200.) == (
        20.0, "MEASURED_NATIVE_FULLY_RECOVERED")


def test_terminal_receipt_must_include_native_full_resource_caps():
    prepared = _prepared("a" * 64)
    result = _receipt("a" * 64)
    del result["native_terminal_recovery"]["max_mana"]
    assert score_native_chain(result, prepared, mob_count=3,
                              expected_target_hp=1200.) == (
        None, "NATIVE_TERMINAL_BOTH_RESOURCES_NOT_FULL")

def test_decisions_no_between_pull_refill_still_scores_source_clock():
    # The Rust bridge may report paid_recovery=False when Decisions needed
    # no between-kill refill. Its separate native_recovery_clock_accounted
    # receipt still certifies those actual shared-clock travel gaps.
    prepared = _prepared("a" * 64)
    result = _receipt("a" * 64)
    result["paid_recovery"] = False
    assert score_native_chain(result, prepared, mob_count=3,
                              expected_target_hp=1200.) == (
        20.0, "MEASURED_NATIVE_FULLY_RECOVERED")
    # The same conditional chain must still pay its final full HP+mana debt.
    result["native_terminal_recovery"]["end_clock_ns"] = 15_000_000_000
    assert score_native_chain(result, prepared, mob_count=3,
                              expected_target_hp=1200.) == (
        None, "NATIVE_TERMINAL_FREE_RESOURCE_RESET")


def test_decisions_conditional_rest_requires_native_gap_receipts():
    prepared = _prepared("a" * 64)
    result = _receipt("a" * 64)
    result["paid_recovery"] = False
    result["native_recovery_clock_accounted"] = False
    assert score_native_chain(result, prepared, mob_count=3,
                              expected_target_hp=1200.) == (
        None, "INCOMPLETE_NATIVE_WORLD_OR_BETWEEN_KILL_RECEIPT")
    # An unknown legacy/native flag is not permission to assume no rest.
    result["native_recovery_clock_accounted"] = True
    del result["paid_recovery"]
    assert score_native_chain(result, prepared, mob_count=3,
                              expected_target_hp=1200.) == (
        None, "INCOMPLETE_NATIVE_WORLD_OR_BETWEEN_KILL_RECEIPT")


def test_missing_native_terminal_never_becomes_free_recovery():
    prepared = _prepared("a" * 64)
    result = _receipt("a" * 64)
    del result["native_terminal_recovery"]
    assert score_native_chain(result, prepared, mob_count=3,
                              expected_target_hp=1200.) == (
        None, "NATIVE_TERMINAL_FULL_RECOVERY_NOT_RECORDED")


def test_unpaid_partial_or_forged_terminal_refuses_rank():
    base = _receipt("a" * 64)
    prepared = _prepared("a" * 64)
    cases = [
        (lambda r: r["native_terminal_recovery"].update(end_clock_ns=15_000_000_000),
         "NATIVE_TERMINAL_FREE_RESOURCE_RESET"),
        (lambda r: r["native_terminal_recovery"].update(mana_after=1400),
         "NATIVE_TERMINAL_BOTH_RESOURCES_NOT_FULL"),
        (lambda r: r["native_terminal_recovery"].update(health_before=900),
         "NATIVE_TERMINAL_BOTH_RESOURCES_NOT_FULL"),
        (lambda r: r["native_terminal_recovery"].update(start_clock_ns=13_000_000_000),
         "NATIVE_TERMINAL_RECOVERY_CLOCK_NOT_PAID"),
        (lambda r: r.update(world_targets_killed=2),
         "INCOMPLETE_NATIVE_WORLD_OR_BETWEEN_KILL_RECEIPT"),
        (lambda r: r.update(source_sha256="b" * 64),
         "INCOMPLETE_NATIVE_WORLD_OR_BETWEEN_KILL_RECEIPT"),
        (lambda r: r.update(native_recovery_clock_accounted=False),
         "INCOMPLETE_NATIVE_WORLD_OR_BETWEEN_KILL_RECEIPT"),
    ]
    for mutate, expected in cases:
        row = copy.deepcopy(base)
        mutate(row)
        score, reason = score_native_chain(row, prepared, mob_count=3,
                                           expected_target_hp=1200.)
        assert score is None and reason == expected


def test_one_paid_candidate_and_one_refusal_are_not_optimized(tmp_path):
    paths = {}
    for cid in ("good", "dead"):
        path = tmp_path / f"{cid}.json"
        path.write_text(json.dumps(_prepared(cid[0] * 64)))
        paths[cid] = path

    def runner(binary, path, **kwargs):
        if path.stem == "dead":
            raise AssertionError("real native player died at kill 2")
        return _receipt("g" * 64)

    result = compare_prepared_candidates(binary=Path("rust"), prepared_paths=paths,
                                         actor_level=30, mob_count=3, target_hp=1200.,
                                         run_native=runner)
    assert result["comparable_candidates"] == 1
    assert result["winner_candidate_id"] is None
    assert result["status"] == "PROVISIONAL_NO_COMPETITIVE_FULL_RECOVERY"
    assert result["candidates"][1]["status"] == "NATIVE_REFUSAL"
    assert "terminal_recovery_seconds" not in result["candidates"][1]
    assert "native_raw_receipt_sha256" not in result["candidates"][1]


def test_duplicate_native_prepared_source_is_not_an_optimized_comparison(tmp_path):
    paths = {}
    for candidate_id in ("original", "same_build"):
        path = tmp_path / f"{candidate_id}.json"
        path.write_text(json.dumps(_prepared("a" * 64)))
        paths[candidate_id] = path
    calls = []

    def runner(binary, path, **kwargs):
        calls.append(path.stem)
        return _receipt("a" * 64)

    output = compare_prepared_candidates(
        binary=Path("rust"), prepared_paths=paths, actor_level=30,
        mob_count=3, target_hp=1200., run_native=runner,
        artifact_dir=tmp_path / "receipts")
    assert calls == ["original"]
    assert output["comparable_candidates"] == 1
    assert output["status"] == "PROVISIONAL_NO_COMPETITIVE_FULL_RECOVERY"
    assert output["winner_candidate_id"] is None
    assert output["candidates"][1]["status"] == "DUPLICATE_NATIVE_PREPARED_SOURCE"
    assert output["candidates"][1]["duplicate_of"] == "original"
    assert not (tmp_path / "receipts" / "same_build.native.json").exists()


def test_duplicate_proposal_does_not_hide_a_later_faster_native_build(tmp_path):
    paths = {}
    for candidate_id, source in (("first", "a" * 64),
                                 ("alias", "a" * 64),
                                 ("later", "b" * 64)):
        path = tmp_path / f"{candidate_id}.json"
        path.write_text(json.dumps(_prepared(source)))
        paths[candidate_id] = path
    calls = []

    def runner(binary, path, **kwargs):
        calls.append(path.stem)
        if path.stem == "first":
            return _receipt("a" * 64, kill_seconds=15, recovery_seconds=10)
        return _receipt("b" * 64, kill_seconds=17, recovery_seconds=2)

    output = compare_prepared_candidates(
        binary=Path("rust"), prepared_paths=paths, actor_level=30,
        mob_count=3, target_hp=1200., run_native=runner)
    assert calls == ["first", "later"]
    assert output["comparable_candidates"] == 2
    assert output["winner_candidate_id"] == "later"
    assert output["winner_elapsed_seconds"] == 19
    assert output["candidates"][1]["status"] == "DUPLICATE_NATIVE_PREPARED_SOURCE"



def test_single_native_successor_is_paid_but_not_mislabeled_optimized(tmp_path):
    path = tmp_path / "only.json"
    path.write_text(json.dumps(_prepared("a" * 64)))
    calls = []

    def runner(binary, prepared, **kwargs):
        calls.append((prepared.stem, kwargs["target_count"]))
        return _receipt("a" * 64, kill_seconds=12, recovery_seconds=7)

    output = compare_prepared_candidates(
        binary=Path("rust"), prepared_paths={"only": path}, actor_level=30,
        mob_count=3, target_hp=1200., run_native=runner)
    assert calls == [("only", 3)]
    assert output["comparable_candidates"] == 1
    assert output["candidates"][0]["elapsed_seconds"] == 19
    assert output["winner_candidate_id"] is None
    assert output["status"] == "PROVISIONAL_NO_COMPETITIVE_FULL_RECOVERY"


def test_same_source_sha_with_different_prepared_bytes_is_a_refusal(tmp_path):
    paths = {}
    for candidate_id, source, max_hp in (
        ("first", "a" * 64, 1000.),
        ("conflict", "a" * 64, 1300.),
        ("genuine", "b" * 64, 1000.),
    ):
        path = tmp_path / f"{candidate_id}.json"
        prepared = _prepared(source)
        prepared["player"]["stats"]["Health"] = max_hp
        path.write_text(json.dumps(prepared))
        paths[candidate_id] = path
    calls = []

    def runner(binary, prepared, **kwargs):
        calls.append(prepared.stem)
        if prepared.stem == "first":
            return _receipt("a" * 64, kill_seconds=16, recovery_seconds=9)
        return _receipt("b" * 64, kill_seconds=17, recovery_seconds=2)

    output = compare_prepared_candidates(
        binary=Path("rust"), prepared_paths=paths, actor_level=30,
        mob_count=3, target_hp=1200., run_native=runner)
    assert calls == ["first", "genuine"]
    assert output["comparable_candidates"] == 2
    assert output["winner_candidate_id"] == "genuine"
    assert output["candidates"][1]["status"] == "CONFLICTING_NATIVE_PREPARED_SOURCE"
    assert output["candidates"][1]["duplicate_of"] == "first"
    assert output["candidates"][1]["elapsed_seconds"] is None


def test_invalid_prepared_source_sha_does_not_consume_paid_mobs(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(_prepared("bad-native-source")))
    calls = []

    def runner(*args, **kwargs):
        calls.append(True)
        raise AssertionError("invalid native source identity must be refused")

    output = compare_prepared_candidates(
        binary=Path("rust"), prepared_paths={"invalid": invalid},
        actor_level=30, mob_count=3, target_hp=1200.,
        run_native=runner)
    assert calls == []
    assert output["comparable_candidates"] == 0
    assert output["winner_candidate_id"] is None
    assert output["candidates"][0]["status"] == "INVALID_NATIVE_PREPARED_IDENTITY_OR_CAPACITY"


def test_missing_or_malformed_native_damage_receipt_is_still_refused():
    prepared = _prepared("a" * 64)
    cases = [
        lambda r: r.pop("native_health_damage"),
        lambda r: r["native_health_damage"].update(observed=False),
        lambda r: r["native_health_damage"].update(damage_taken=-1.),
        lambda r: r["native_health_damage"].update(damage_events=-1),
        lambda r: r["native_health_damage"].update(damage_events=0),
    ]
    for mutate in cases:
        result = _receipt("a" * 64)
        mutate(result)
        assert score_native_chain(result, prepared, mob_count=3,
                                  expected_target_hp=1200.) == (
            None, "NATIVE_HEALTH_DAMAGE_RECEIPT_MISSING_OR_INVALID")


def test_zero_damage_is_observed_native_outcome_not_missing_telemetry():
    prepared = _prepared("a" * 64)
    result = _receipt("a" * 64)
    result["native_health_damage"].update(
        observed=True, damage_taken=0.0, damage_events=0)
    # Native world ACK, original source and post-last-kill paid full HP/mana
    # are still required; player HP loss itself must not be optimized for.
    assert score_native_chain(result, prepared, mob_count=3,
                              expected_target_hp=1200.) == (
        20.0, "MEASURED_NATIVE_FULLY_RECOVERED")
    result["native_terminal_recovery"]["mana_after"] = 1400.
    assert score_native_chain(result, prepared, mob_count=3,
                              expected_target_hp=1200.) == (
        None, "NATIVE_TERMINAL_BOTH_RESOURCES_NOT_FULL")


def test_observed_no_player_damage_may_win_native_paid_comparison(tmp_path):
    paths = {}
    for cid in ("avoids_damage", "takes_damage"):
        path = tmp_path / f"{cid}.json"
        path.write_text(json.dumps(_prepared(cid[0] * 64)))
        paths[cid] = path

    def runner(binary, path, **kwargs):
        assert kwargs["require_native_health_damage"] is False
        result = _receipt(path.stem[0] * 64,
                          kill_seconds=14 if path.stem == "avoids_damage" else 13,
                          recovery_seconds=2 if path.stem == "avoids_damage" else 7)
        if path.stem == "avoids_damage":
            result["native_health_damage"].update(
                observed=True, damage_taken=0., damage_events=0)
        return result

    output = compare_prepared_candidates(
        binary=Path("rust"), prepared_paths=paths, actor_level=30,
        mob_count=3, target_hp=1200., run_native=runner)
    assert output["comparable_candidates"] == 2
    assert output["winner_candidate_id"] == "avoids_damage"
    assert output["winner_elapsed_seconds"] == 16
    assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
               for row in output["candidates"])


def test_exact_paid_receipt_reuse_requires_same_engine_source_and_scenario(
        tmp_path, monkeypatch):
    """A genuine fully recovered receipt is not paid again at identical inputs."""
    import tools.wf_warlock_native_candidate_scoring as scorer

    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"exact-engine")
    prepared = tmp_path / "candidate.json"
    prepared.write_text(json.dumps(_prepared("a" * 64)))
    artifacts = tmp_path / "receipts"
    calls = []

    def identity(binary, *, actor_level, mob_count, target_hp):
        return {
            "cache_schema": 1, "forever_commit": "f" * 40,
            "native_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "actor_level": actor_level, "mob_count": mob_count,
            "target_hp": target_hp, "rng_mode": "balanced", "iterations": 1,
            "recovery_policy": "decisions", "health_threshold": 1.0,
            "mana_threshold": 1.0, "require_native_health_damage": False,
        }

    monkeypatch.setattr(scorer, "_exact_paid_cache_identity", identity)

    def native(binary, prepared, **kwargs):
        calls.append((binary.read_bytes(), kwargs["target_count"]))
        return _receipt("a" * 64)

    def evaluate():
        return compare_prepared_candidates(
            binary=binary, prepared_paths={"candidate": prepared},
            actor_level=30, mob_count=3, target_hp=1200.,
            run_native=native, artifact_dir=artifacts)

    initial = evaluate()
    assert len(calls) == 1
    assert initial["candidates"][0]["reused_exact_native_paid_receipt"] is False
    repeat = evaluate()
    assert len(calls) == 1
    assert repeat["candidates"][0]["reused_exact_native_paid_receipt"] is True
    assert repeat["candidates"][0]["elapsed_seconds"] == 20.0
    # A resumed frontier may re-label the exact same prepared source. It must
    # reference the original paid ACK, not spend three more native kills or
    # create a second, unauthenticated paid file for the new label.
    renamed = tmp_path / "renamed.json"
    renamed.write_bytes(prepared.read_bytes())
    alias = compare_prepared_candidates(
        binary=binary, prepared_paths={"new_frontier_label": renamed},
        actor_level=30, mob_count=3, target_hp=1200.,
        run_native=native, artifact_dir=artifacts)
    assert len(calls) == 1
    assert alias["candidates"][0]["reused_exact_native_paid_receipt"] is True
    assert alias["candidates"][0]["elapsed_seconds"] == 20.0
    assert alias["candidates"][0]["native_raw_receipt_file"] == str(
        artifacts / "candidate.native.json")
    assert not (artifacts / "new_frontier_label.native.json").exists()
    # A modified receipt is no longer original paid evidence.
    raw = artifacts / "candidate.native.json"
    raw.write_text(raw.read_text().replace(
        '"world_target_hp": 1200.0', '"world_target_hp": 999.0'))
    altered = evaluate()
    assert len(calls) == 2
    assert altered["candidates"][0]["reused_exact_native_paid_receipt"] is False
    # A different compiled native engine cannot inherit the previous score.
    binary.write_bytes(b"new-engine")
    changed = evaluate()
    assert len(calls) == 3
    assert changed["candidates"][0]["reused_exact_native_paid_receipt"] is False


def test_native_timeout_refuses_only_one_candidate(tmp_path):
    import subprocess
    paths = {}
    for label in ("timed_out", "paid"):
        path = tmp_path / (label + ".json")
        path.write_text(json.dumps(_prepared(label[0] * 64)))
        paths[label] = path

    def native(binary, prepared, **kwargs):
        if prepared.stem == "timed_out":
            raise subprocess.TimeoutExpired(cmd="native-world-pulls", timeout=30)
        return _receipt("p" * 64)

    result = compare_prepared_candidates(
        binary=Path("native"), prepared_paths=paths,
        actor_level=30, mob_count=3, target_hp=1200., run_native=native)
    assert result["comparable_candidates"] == 1
    assert result["candidates"][0]["status"] == "NATIVE_REFUSAL"
    assert result["candidates"][1]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert result["candidates"][1]["elapsed_seconds"] == 20.0


def test_cross_frontier_shared_paid_cache_reuses_exact_ack_only(tmp_path, monkeypatch):
    """New output directories do not force duplicate native kills."""
    import tools.wf_warlock_native_candidate_scoring as scorer

    binary = tmp_path / "rust-engine"
    binary.write_bytes(b"native-recovery-v1")
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps(_prepared("a" * 64)))
    cache = tmp_path / "shared-cache"
    calls = []

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

    def paid_native(executable, source, **kwargs):
        calls.append((executable.read_bytes(), source.read_bytes(),
                      kwargs["target_count"], kwargs["mob_health"]))
        result = _receipt(json.loads(source.read_text())["request_sha256"])
        result["world_target_hp"] = kwargs["mob_health"]
        return result

    def evaluate(label, source=prepared, target_hp=1200.0):
        return compare_prepared_candidates(
            binary=binary, prepared_paths={"proposal": source},
            actor_level=30, mob_count=3, target_hp=target_hp,
            run_native=paid_native, artifact_dir=tmp_path / label,
            paid_cache_dir=cache)["candidates"][0]

    first = evaluate("frontier-1")
    assert len(calls) == 1
    assert first["reused_exact_native_paid_receipt"] is False
    original = Path(first["native_raw_receipt_file"])
    assert original.parent == cache
    assert first["elapsed_seconds"] == 20.0

    again = evaluate("frontier-2")
    assert len(calls) == 1
    assert again["reused_exact_native_paid_receipt"] is True
    assert again["native_raw_receipt_file"] == str(original)
    assert again["native_raw_receipt_sha256"] == hashlib.sha256(
        original.read_bytes()).hexdigest()
    assert not list((tmp_path / "frontier-2").glob("*.native.json"))

    # A tampered original is not evidence; pay again without overwriting it.
    original.write_text(original.read_text().replace(
        '"world_target_hp": 1200.0', '"world_target_hp": 999.0'))
    tampered = evaluate("frontier-3")
    assert len(calls) == 2
    assert tampered["reused_exact_native_paid_receipt"] is False
    assert Path(tampered["native_raw_receipt_file"]).parent == tmp_path / "frontier-3"

    binary.write_bytes(b"native-recovery-v2")
    assert evaluate("frontier-4")["reused_exact_native_paid_receipt"] is False
    assert len(calls) == 3
    alternate = tmp_path / "alternate.json"
    alternate.write_text(json.dumps(_prepared("b" * 64)))
    assert evaluate("frontier-5", alternate)["reused_exact_native_paid_receipt"] is False
    assert len(calls) == 4
    assert evaluate("frontier-6", alternate, 1400.)[
        "reused_exact_native_paid_receipt"] is False
    assert len(calls) == 5


def test_native_paid_cache_identity_survives_workflow_only_git_commits(tmp_path, monkeypatch):
    """Non-runtime edits reuse receipts; native changes and dirty sources never do."""
    import subprocess
    from tools import wf_warlock_native_candidate_scoring as scorer

    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"native engine A")
    assert "src/shared" in scorer._PAID_RUNTIME_GIT_PATHS
    shas = ["a" * 40 for _ in scorer._PAID_RUNTIME_GIT_PATHS]
    dirty = ["clean"]

    def git(argv, *, cwd, capture_output, text, check, timeout):
        assert argv[0] == "git" and cwd.is_dir()
        if argv[1] == "status":
            # Unrelated working-tree changes are outside the same paths used
            # to fingerprint the paid runtime. Changed/untracked runtime
            # files are unsafe even if HEAD's Git object IDs still match.
            assert argv[2:5] == ["--porcelain", "--untracked-files=all", "--"]
            assert tuple(argv[5:]) == scorer._PAID_RUNTIME_GIT_PATHS
            rows = {
                "clean": "",
                "unrelated-workflow": "",
                "runtime-modified": " M tools/wf_warlock_native_candidate_scoring.py\n",
                "runtime-untracked": "?? src/game/untracked_runtime.py\n",
                "shared-modified": " M src/shared/stat_math.py\n",
                "shared-untracked": "?? src/shared/new_runtime.py\n",
            }
            return subprocess.CompletedProcess(argv, 0, rows[dirty[0]])
        assert argv[1] == "rev-parse"
        assert tuple(value.removeprefix("HEAD:") for value in argv[2:]) == scorer._PAID_RUNTIME_GIT_PATHS
        return subprocess.CompletedProcess(argv, 0, "\n".join(shas) + "\n")

    monkeypatch.setattr(scorer.subprocess, "run", git)
    def identity():
        return scorer._exact_paid_cache_identity(
            binary, actor_level=30, mob_count=2, target_hp=1200.0)

    first = identity()
    assert first and first["cache_schema"] == 2
    assert "forever_commit" not in first
    # A workflow-only commit changes HEAD, not the tracked runtime object IDs.
    assert identity() == first
    dirty[0] = "unrelated-workflow"
    assert identity() == first
    dirty[0] = "clean"
    shas[-1] = "b" * 40  # Actual paid adapter implementation changed.
    changed = identity()
    assert changed != first
    assert changed["forever_paid_runtime_sha256"] != first["forever_paid_runtime_sha256"]
    shas[-1] = "a" * 40
    # The gsim runtime calls src.shared.stat_math: editing the shared code
    # must change the exact paid fingerprint without repaying unrelated edits.
    shared_index = scorer._PAID_RUNTIME_GIT_PATHS.index("src/shared")
    shas[shared_index] = "c" * 40
    assert identity()["forever_paid_runtime_sha256"] != first["forever_paid_runtime_sha256"]
    shas[shared_index] = "a" * 40
    binary.write_bytes(b"native engine B")
    assert identity()["native_binary_sha256"] != first["native_binary_sha256"]
    binary.write_bytes(b"native engine A")
    dirty[0] = "runtime-modified"
    assert identity() is None
    dirty[0] = "runtime-untracked"
    assert identity() is None
    dirty[0] = "shared-modified"
    assert identity() is None
    dirty[0] = "shared-untracked"
    assert identity() is None


def test_migrate_legacy_local_label_into_shared_paid_cache(tmp_path, monkeypatch):
    """Adding the stable cache must reuse local ACK and seed future frontiers."""
    from tools import wf_warlock_native_candidate_scoring as scorer

    binary = tmp_path / "engine"
    binary.write_bytes(b"selected-rust-engine")
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps(_prepared("a" * 64)))
    artifacts, shared = tmp_path / "local", tmp_path / "shared"
    calls = []

    def identity(engine, *, actor_level, mob_count, target_hp):
        return {
            "cache_schema": 2, "forever_paid_runtime_sha256": "f" * 64,
            "native_binary_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
            "actor_level": actor_level, "mob_count": mob_count,
            "target_hp": target_hp, "rng_mode": "balanced", "iterations": 1,
            "recovery_policy": "decisions", "health_threshold": 1.0,
            "mana_threshold": 1.0, "require_native_health_damage": False,
        }

    monkeypatch.setattr(scorer, "_exact_paid_cache_identity", identity)

    def native(engine, request, **kwargs):
        calls.append(kwargs["target_count"])
        return _receipt("a" * 64)

    def evaluate(label, folder, cache=None):
        screen = compare_prepared_candidates(
            binary=binary, prepared_paths={label: prepared}, actor_level=30,
            mob_count=3, target_hp=1200., run_native=native,
            artifact_dir=folder, paid_cache_dir=cache)
        return screen["candidates"][0]

    first = evaluate("original", artifacts)
    assert calls == [3]
    assert first["reused_exact_native_paid_receipt"] is False
    local_receipt = artifacts / "original.native.json"
    original_bytes = local_receipt.read_bytes()

    # Same genuinely paid actor/scenario, new proposal label and cache mode.
    migrated = evaluate("renamed", artifacts, shared)
    assert calls == [3], "cache migration must never execute duplicate mobs"
    assert migrated["reused_exact_native_paid_receipt"] is True
    assert migrated["elapsed_seconds"] == 20.
    shared_receipt = Path(migrated["native_raw_receipt_file"])
    assert shared_receipt.parent == shared
    assert shared_receipt.read_bytes() == original_bytes
    assert local_receipt.read_bytes() == original_bytes
    assert not (artifacts / "renamed.native.json").exists()

    # Another frontier directory now resolves the promoted original ACK.
    next_frontier = evaluate("new_frontier", tmp_path / "next", shared)
    assert calls == [3]
    assert next_frontier["reused_exact_native_paid_receipt"] is True
    assert Path(next_frontier["native_raw_receipt_file"]) == shared_receipt


def test_failed_shared_cache_write_reuses_local_paid_ack(tmp_path, monkeypatch):
    """A shared-cache I/O refusal must not cause an identical second payment."""
    from tools import wf_warlock_native_candidate_scoring as scorer

    binary = tmp_path / "engine"
    binary.write_bytes(b"selected-rust-engine")
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps(_prepared("a" * 64)))
    local, shared = tmp_path / "local", tmp_path / "shared"
    calls = []

    def identity(engine, *, actor_level, mob_count, target_hp):
        return {
            "cache_schema": 2, "forever_paid_runtime_sha256": "f" * 64,
            "native_binary_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
            "actor_level": actor_level, "mob_count": mob_count,
            "target_hp": target_hp, "rng_mode": "balanced", "iterations": 1,
            "recovery_policy": "decisions", "health_threshold": 1.0,
            "mana_threshold": 1.0, "require_native_health_damage": False,
        }

    monkeypatch.setattr(scorer, "_exact_paid_cache_identity", identity)
    original_write_bytes = Path.write_bytes

    def fail_shared_receipt(self, data):
        if self.parent == shared and self.name.endswith(".native.json"):
            raise PermissionError("shared cache temporarily read-only")
        return original_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", fail_shared_receipt)

    def native(engine, source, **kwargs):
        calls.append(kwargs["target_count"])
        return _receipt("a" * 64)

    def evaluate(label):
        return compare_prepared_candidates(
            binary=binary, prepared_paths={label: prepared}, actor_level=30,
            mob_count=3, target_hp=1200., run_native=native,
            artifact_dir=local, paid_cache_dir=shared)["candidates"][0]

    first = evaluate("first")
    assert first["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert not first["reused_exact_native_paid_receipt"]
    assert calls == [3]
    raw = local / "first.native.json"
    metadata = local / "first.native.cache.json"
    assert first["native_raw_receipt_file"] == str(raw)
    assert metadata.exists()
    assert json.loads(metadata.read_text())["native_raw_receipt_sha256"] == (
        hashlib.sha256(raw.read_bytes()).hexdigest())

    # Same paid scenario, new optimizer label; the shared cache is still
    # unwritable, but its failure must not erase local paid evidence.
    again = evaluate("renamed")
    assert calls == [3]
    assert again["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert again["reused_exact_native_paid_receipt"]
    assert again["native_raw_receipt_file"] == str(raw)
    assert again["elapsed_seconds"] == first["elapsed_seconds"]
    assert not (local / "renamed.native.json").exists()


def test_shared_cache_init_failure_keeps_local_paid_ack(tmp_path, monkeypatch):
    """An unusable optional shared cache must not prevent real local paid scoring."""
    from tools import wf_warlock_native_candidate_scoring as scorer

    binary = tmp_path / "engine"
    binary.write_bytes(b"selected-rust-engine")
    prepared = tmp_path / "prepared.json"
    prepared.write_text(json.dumps(_prepared("a" * 64)))
    local = tmp_path / "local"
    # A regular file cannot be turned into a shared-cache directory. This
    # exercises a real mkdir failure before the first native evaluation.
    shared = tmp_path / "shared"
    shared.write_text("unavailable shared cache")
    calls = []

    def identity(engine, *, actor_level, mob_count, target_hp):
        return {
            "cache_schema": 2, "forever_paid_runtime_sha256": "f" * 64,
            "native_binary_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
            "actor_level": actor_level, "mob_count": mob_count,
            "target_hp": target_hp, "rng_mode": "balanced", "iterations": 1,
            "recovery_policy": "decisions", "health_threshold": 1.0,
            "mana_threshold": 1.0, "require_native_health_damage": False,
        }

    monkeypatch.setattr(scorer, "_exact_paid_cache_identity", identity)

    def native(engine, source, **kwargs):
        calls.append(kwargs)
        return _receipt("a" * 64)

    def evaluate(label):
        return compare_prepared_candidates(
            binary=binary, prepared_paths={label: prepared},
            actor_level=30, mob_count=3, target_hp=1200.,
            run_native=native, artifact_dir=local,
            paid_cache_dir=shared)["candidates"][0]

    first = evaluate("original")
    assert first["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert first["elapsed_seconds"] == 20.
    assert first["reused_exact_native_paid_receipt"] is False
    assert len(calls) == 1
    assert calls[0]["target_count"] == 3
    assert calls[0]["rng_mode"] == "balanced"
    assert calls[0]["health_threshold"] == calls[0]["mana_threshold"] == 1.0
    original = local / "original.native.json"
    metadata = local / "original.native.cache.json"
    assert original.exists() and metadata.exists()
    assert json.loads(metadata.read_text())["native_raw_receipt_sha256"] == (
        hashlib.sha256(original.read_bytes()).hexdigest())

    # A renamed candidate reuses the same exact paid ACK locally, despite the
    # still-invalid shared location; neither path should invent a free refill.
    again = evaluate("renamed")
    assert len(calls) == 1
    assert again["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert again["reused_exact_native_paid_receipt"] is True
    assert again["elapsed_seconds"] == first["elapsed_seconds"]
    assert again["terminal_health"] == again["terminal_max_health"] == 1000.
    assert again["terminal_mana"] == again["terminal_max_mana"] == 1500.
    assert again["native_raw_receipt_file"] == str(original)
    assert shared.read_text() == "unavailable shared cache"


def test_corrupt_prepared_candidate_does_not_abort_later_native_payment(tmp_path):
    """One incomplete native prepare artifact must not erase other candidates."""
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{truncated native JSON")
    wrong_shape = tmp_path / "wrong-shape.json"
    wrong_shape.write_text(json.dumps({"player": ["not an actor"]}))
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_prepared("v" * 64)))
    calls = []

    def native(binary, prepared, **kwargs):
        calls.append((prepared.stem, kwargs["target_count"]))
        return _receipt("v" * 64)

    result = compare_prepared_candidates(
        binary=Path("rust"), prepared_paths={
            "malformed": malformed, "wrong_shape": wrong_shape,
            "valid": valid},
        actor_level=30, mob_count=3, target_hp=1200.,
        run_native=native, artifact_dir=tmp_path / "receipts")
    assert calls == [("valid", 3)]
    assert [row["status"] for row in result["candidates"]] == [
        "INVALID_NATIVE_PREPARED_PAYLOAD",
        "INVALID_NATIVE_PREPARED_PAYLOAD",
        "MEASURED_NATIVE_FULLY_RECOVERED",
    ]
    assert result["comparable_candidates"] == 1
    assert result["winner_candidate_id"] is None
    assert result["candidates"][2]["terminal_health"] == 1000.
    assert result["candidates"][2]["terminal_mana"] == 1500.


def test_nonobject_native_receipt_refuses_only_its_candidate(tmp_path):
    """Malformed native IPC must never become an ACK or hide a paid successor."""
    paths = {}
    for cid in ("invalid", "valid"):
        path = tmp_path / f"{cid}.json"
        path.write_text(json.dumps(_prepared(cid[0] * 64)))
        paths[cid] = path
    calls = []

    def native(binary, prepared, **kwargs):
        calls.append(prepared.stem)
        if prepared.stem == "invalid":
            return ["not a source-native world ACK"]
        return _receipt("v" * 64)

    result = compare_prepared_candidates(
        binary=Path("rust"), prepared_paths=paths,
        actor_level=30, mob_count=3, target_hp=1200.,
        run_native=native, artifact_dir=tmp_path / "receipts")
    assert calls == ["invalid", "valid"]
    assert [row["status"] for row in result["candidates"]] == [
        "INVALID_NATIVE_RECEIPT_SHAPE",
        "MEASURED_NATIVE_FULLY_RECOVERED",
    ]
    assert result["candidates"][0]["elapsed_seconds"] is None
    assert result["candidates"][0]["acked_world_kills"] is None
    assert result["comparable_candidates"] == 1
    assert result["winner_candidate_id"] is None
    assert result["candidates"][1]["elapsed_seconds"] == 20.
    assert result["candidates"][1]["terminal_mana"] == 1500.
    assert score_native_chain([], _prepared("i" * 64), mob_count=3,
                              expected_target_hp=1200.) == (
        None, "INVALID_NATIVE_RECEIPT_SHAPE")


def test_wrong_native_prepared_actor_isolated_from_valid_paid_successor(tmp_path):
    """Never pay a foreign class/level, or let it abort other native candidates."""
    paths = {}
    for candidate_id in ("wrong_class", "wrong_level", "valid"):
        prepared = _prepared(candidate_id[0] * 64)
        if candidate_id == "wrong_class":
            prepared["player"]["class"] = "ClassRogue"
        elif candidate_id == "wrong_level":
            prepared["player"]["level"] = 40
        path = tmp_path / (candidate_id + ".json")
        path.write_text(json.dumps(prepared))
        paths[candidate_id] = path

    calls = []

    def native(binary, path, **kwargs):
        calls.append((path.stem, kwargs["target_count"], kwargs["rng_mode"]))
        return _receipt("v" * 64)

    result = compare_prepared_candidates(
        binary=Path("rust"), prepared_paths=paths, actor_level=30,
        mob_count=3, target_hp=1200., run_native=native,
        artifact_dir=tmp_path / "receipts")
    assert calls == [("valid", 3, "balanced")]
    assert [row["status"] for row in result["candidates"]] == [
        "NATIVE_PREPARED_ACTOR_LEVEL_OR_CLASS_MISMATCH",
        "NATIVE_PREPARED_ACTOR_LEVEL_OR_CLASS_MISMATCH",
        "MEASURED_NATIVE_FULLY_RECOVERED",
    ]
    assert result["candidates"][0]["prepared_actor_class"] == "ClassRogue"
    assert result["candidates"][1]["prepared_actor_level"] == 40
    assert all(row["elapsed_seconds"] is None
               for row in result["candidates"][:2])
    assert result["comparable_candidates"] == 1
    assert result["winner_candidate_id"] is None
    assert result["candidates"][2]["terminal_health"] == 1000.
    assert result["candidates"][2]["terminal_mana"] == 1500.
    assert not (tmp_path / "receipts" / "wrong_class.native.json").exists()
    assert not (tmp_path / "receipts" / "wrong_level.native.json").exists()


def test_native_prepared_rewrite_during_payment_is_unranked_without_losing_successor(
        tmp_path, monkeypatch):
    """A native call may reopen a rewritten input: never misattribute its ACK."""
    from tools import wf_warlock_native_candidate_scoring as scorer

    binary = tmp_path / "engine"
    binary.write_bytes(b"source-native-engine")
    paths = {}
    for candidate_id, source_sha in (("unstable", "a" * 64),
                                     ("valid", "v" * 64)):
        path = tmp_path / f"{candidate_id}.json"
        path.write_text(json.dumps(_prepared(source_sha)))
        paths[candidate_id] = path

    def identity(engine, *, actor_level, mob_count, target_hp):
        return {
            "cache_schema": 2, "forever_paid_runtime_sha256": "f" * 64,
            "native_binary_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
            "actor_level": actor_level, "mob_count": mob_count,
            "target_hp": target_hp, "rng_mode": "balanced", "iterations": 1,
            "recovery_policy": "decisions", "health_threshold": 1.0,
            "mana_threshold": 1.0, "require_native_health_damage": False,
        }

    monkeypatch.setattr(scorer, "_exact_paid_cache_identity", identity)
    calls = []

    def native(engine, path, **kwargs):
        calls.append((path.stem, kwargs["target_count"], kwargs["rng_mode"]))
        if path.stem == "unstable":
            # Source input was valid when inspected, but changed before the
            # native result returned. The original paid ACK must be retained
            # without earning a score or a reusable cache identity.
            path.write_text(json.dumps(_prepared("b" * 64)))
            return _receipt("a" * 64)
        return _receipt("v" * 64)

    artifacts = tmp_path / "receipts"
    result = compare_prepared_candidates(
        binary=binary, prepared_paths=paths, actor_level=30,
        mob_count=3, target_hp=1200., run_native=native,
        artifact_dir=artifacts)
    assert calls == [("unstable", 3, "balanced"), ("valid", 3, "balanced")]
    assert [row["status"] for row in result["candidates"]] == [
        "NATIVE_PREPARED_INPUT_CHANGED",
        "MEASURED_NATIVE_FULLY_RECOVERED",
    ]
    assert result["candidates"][0]["elapsed_seconds"] is None
    assert result["comparable_candidates"] == 1
    assert result["winner_candidate_id"] is None
    assert result["candidates"][1]["elapsed_seconds"] == 20.
    assert result["candidates"][1]["terminal_health"] == 1000.
    assert result["candidates"][1]["terminal_mana"] == 1500.
    assert (artifacts / "unstable.native.json").exists()
    assert not (artifacts / "unstable.native.cache.json").exists()
    assert (artifacts / "valid.native.cache.json").exists()
