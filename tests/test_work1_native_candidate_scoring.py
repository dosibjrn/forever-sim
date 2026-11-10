"""Forever-owned competitive native scoring; no mechanics or world replay in tests."""
import copy
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
               and kw["recovery_policy"] == "decisions" for _, kw in calls)
    assert len(list((tmp_path / "receipts").glob("*.native.json"))) == 3


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
