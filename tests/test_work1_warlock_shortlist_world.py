"""Work1: real native 100/100 build comparisons, not 30-second DPS winners.

Tests stub only the guide/native transport. All measured-world decisions are
computed from paid ACK/recovery actor receipts returned by that transport.
"""
import copy
import json
from pathlib import Path

import pytest

from tools import wf_warlock_shortlist_world as world


def _setup(tmp_path, trees=(0, 1, 2)):
    binary = tmp_path / "native"
    binary.write_bytes(b"selected native binary")
    base = {"raid": {"parties": [{"players": [{
        "class": "ClassWarlock", "level": 20, "talentsString": "0-0-011",
        "race": "RaceTroll", "equipment": {"items": [{"id": 101}]},
        "rotation": {"priorityList": []},
    }]}]}, "encounter": {"targets": [{
        "level": 20, "name": "same hostile source target",
        "stats": [0] * 34, "minBaseDamage": 20, "swingSpeed": 2,
    }]}, "simOptions": {"iterations": 8}}
    base["encounter"]["targets"][0]["stats"][32] = 700
    source = tmp_path / "source.json"
    source.write_text(json.dumps(base))
    predecessor_route = tmp_path / "predecessor.json"
    predecessor_route.write_text('{"class":"warlock"}')
    predecessor = {
        "level": 20, "observation_id": "real-paid-L20",
        "source_request_sha256": world.native_source.sha256(source),
        "engine_binary_sha256": world.native_source.sha256(binary),
        "successor_engine_binary_sha256": world.native_source.sha256(binary),
        "cross_engine_source_transition": False,
    }
    directory = tmp_path / "shortlist"
    attempts = directory / "candidate_attempts"
    attempts.mkdir(parents=True)
    rows = []
    for i, tree in enumerate(trees, 1):
        candidate = copy.deepcopy(base)
        candidate["raid"]["parties"][0]["players"][0]["level"] = 21
        candidate["raid"]["parties"][0]["players"][0]["talentsString"] = (
            ["1-0-011", "0-1-011", "0-0-111"][tree])
        candidate["encounter"]["targets"][0]["level"] = 21
        path = attempts / f"candidate_{i:02d}.json"
        path.write_text(json.dumps(candidate))
        rows.append({
            "tree_index": tree, "field_name": f"native talent {i}",
            "candidate_talents": candidate["raid"]["parties"][0]["players"][0]["talentsString"],
            "source_request": f"candidate_attempts/candidate_{i:02d}.json",
            "source_request_sha256": world.native_source.sha256(path),
            "screen_status": "NATIVE_SCREEN_PAID",
            "screen_dps_30s": 300 - 20 * i,
        })
    shortlist = directory / "native_paid_shortlist.json"
    shortlist.write_text(json.dumps({
        "kind": "adjacent_native_warlock_candidate",
        "status": "NATIVE_SCREENED_NOT_WORLD_PAID",
        "from_level": 20, "to_level": 21, "paid_predecessor": predecessor,
        "native_binary_sha256": world.native_source.sha256(binary),
        "original_source_sha256": world.native_source.sha256(source),
        "candidates": rows,
    }))
    args = dict(binary=binary, source=source, predecessor_route=predecessor_route,
                shortlist=shortlist, out=tmp_path / "comparison")
    return args, predecessor


def _fake_native(monkeypatch, predecessor, *, times=(900, 750, None),
                 changed_scenario=False):
    paid = []

    def predecessor_check(**kwargs):
        assert kwargs["from_level"] == 20
        return predecessor

    monkeypatch.setattr(world.native_source, "verified_paid_predecessor",
                        predecessor_check)

    def native_guide(argv):
        assert "--execute-native" in argv
        source = Path(argv[argv.index("--source") + 1])
        folder = Path(argv[argv.index("--out") + 1])
        binary = Path(argv[argv.index("--binary") + 1])
        trial = argv[argv.index("--trial") + 1]
        index = int(folder.name.split("_")[1])
        paid.append(index)
        elapsed = times[index - 1]
        stage = folder / "native_l21"
        executed = stage / "best_apl"
        executed.mkdir(parents=True, exist_ok=True)
        executed_source = executed / "source_request.json"
        executed_source.write_bytes(source.read_bytes())
        digest = world.native_source.sha256(executed_source)
        success = elapsed is not None
        damage = 50 if changed_scenario and index == 2 else 20
        attempt = {
            "variant": "best_apl", "actor_level": 21,
            "status": ("COMPLETED_100_REAL_NATIVE_GSIM_KILLS" if success
                       else "INCOMPLETE_OR_NATIVE_REFUSAL"),
            "target_count_requested": 100,
            "killed": 100 if success else 41,
            "original_source_sha256": world.native_source.sha256(source),
            "source_request_sha256": digest,
            "hostile_player_tank_requested": True,
            "native_binary_sha256": world.native_source.sha256(binary),
            "native_actor_continuity_receipt_complete": success,
            "native_2d_paid_objective_eligible": success,
            "native_recovery_clock_accounted": success,
            "world_target_hp_matches_request": success,
            "paid_recovery": success,
            "native_enemy_attack_prepared": True,
            "seconds_per_mob": elapsed / 100 if success else None,
            "mob_hp_native_scenario": 700,
            "scenario_min_base_damage": damage,
            "scenario_swing_speed": 2,
            "scenario_target_name": "same hostile source target",
            "recovery_request": {"recovery_policy": "decisions",
                                 "health_threshold": 0.7, "mana_threshold": 0.25},
            "native_actor": {"class": "ClassWarlock", "level": 21},
            "final_hp": 490, "final_mana": 710,
        }
        summary = stage / "summary.json"
        summary.write_text(json.dumps({
            "kind": "real_100_target_source_native_world_attempts",
            "target_count_requested": 100, "actor_level": 21,
            "native_binary_sha256": world.native_source.sha256(binary),
            "original_source_sha256": world.native_source.sha256(source),
            "native_recovery_requested": attempt["recovery_request"],
            "hostile_player_tank_requested": True,
            "results": [attempt],
        }))
        observations = []
        if success:
            observations.append({
                "trial": trial, "level": 21,
                "id": trial + "-best_apl",
                "status": "measured_native_chain",
                "source_request_sha256": digest,
                "engine_binary_sha256": world.native_source.sha256(binary),
                "targets_requested": 100, "targets_killed": 100,
                "paid_native_recovery": True, "native_world_ack": True,
                "receipt_path": str(summary.resolve()),
                "elapsed_seconds_for_observed_chain": elapsed,
            })
        (folder / "route.json").write_text(json.dumps({"observations": observations}))
        return 0 if success else 2

    monkeypatch.setattr(world.guide, "main", native_guide)
    return paid


def test_comparison_pays_genuine_hostile_worlds_and_ignores_short_dps(
        tmp_path, monkeypatch):
    args, predecessor = _setup(tmp_path)
    paid = _fake_native(monkeypatch, predecessor)
    result = world.run(**args, max_new_trials=3)
    assert paid == [1, 2, 3]
    assert result["status"] == "MEASURED_SAME_BUILD_FAMILY_100"
    assert result["world_winner"]["candidate_index"] == 2
    assert result["world_winner"]["elapsed_seconds"] == 750
    assert result["candidates"][2]["targets_killed"] == 41
    assert result["candidates"][2]["status"] == "INCOMPLETE_OR_NATIVE_REFUSAL"
    assert result["candidates"][0]["native_screen_dps_30s"] > (
        result["candidates"][1]["native_screen_dps_30s"])
    assert result["stat_weights_measured"] is False
    assert result["m1_recording_performed"] is False
    assert json.loads((args["out"] / "comparison.json").read_text()) == result


def test_paid_resume_reuses_exact_native_receipts_and_only_pays_missing(
        tmp_path, monkeypatch):
    args, predecessor = _setup(tmp_path)
    paid = _fake_native(monkeypatch, predecessor)
    first = world.run(**args, max_new_trials=1)
    assert paid == [1]
    assert first["pending_candidate_indexes"] == [2, 3]
    assert first["world_winner"] is None
    second = world.run(**args, max_new_trials=1)
    assert paid == [1, 2]
    assert second["new_native_100_trials"] == 1
    assert second["reused_native_100_trials"] == 1
    assert second["world_winner"] is None  # third finalist has not run
    third = world.run(**args, max_new_trials=1)
    assert paid == [1, 2, 3]
    assert third["new_native_100_trials"] == 1
    assert third["reused_native_100_trials"] == 2
    assert third["world_winner"]["candidate_index"] == 2
    fourth = world.run(**args, max_new_trials=0)
    assert paid == [1, 2, 3]
    assert fourth["new_native_100_trials"] == 0
    assert fourth["reused_native_100_trials"] == 3


def test_rejects_changed_paid_binary_or_source_without_replaying(
        tmp_path, monkeypatch):
    args, predecessor = _setup(tmp_path, trees=(0, 1))
    paid = _fake_native(monkeypatch, predecessor, times=(900, 750))
    world.run(**args, max_new_trials=2)
    summary = next(args["out"].glob("candidate_01_*/native_l21/summary.json"))
    payload = json.loads(summary.read_text())
    payload["native_binary_sha256"] = "f" * 64
    summary.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="cached native world"):
        world.run(**args, max_new_trials=0)
    assert paid == [1, 2]


def test_refuses_incomparable_hostile_scenarios_despite_two_100_kills(
        tmp_path, monkeypatch):
    args, predecessor = _setup(tmp_path, trees=(0, 1))
    _fake_native(monkeypatch, predecessor, times=(900, 750), changed_scenario=True)
    result = world.run(**args, max_new_trials=2)
    assert result["status"] == "INCOMPARABLE_NATIVE_SCENARIOS"
    assert result["world_winner"] is None
    assert all(row["status"] == "MEASURED_NATIVE_100" for row in result["candidates"])


def test_rejects_tampered_shortlist_before_any_native_payment(
        tmp_path, monkeypatch):
    args, predecessor = _setup(tmp_path, trees=(0, 1))
    paid = _fake_native(monkeypatch, predecessor, times=(900, 750))
    row_file = args["shortlist"].parent / "candidate_attempts" / "candidate_02.json"
    edited = json.loads(row_file.read_text())
    edited["encounter"]["targets"][0]["minBaseDamage"] = 1
    row_file.write_text(json.dumps(edited))
    with pytest.raises(ValueError, match="candidate bytes"):
        world.run(**args, max_new_trials=2)
    assert paid == []


@pytest.mark.parametrize("field, altered", [
    ("original_source_sha256", "f" * 64),
    ("native_binary_sha256", "f" * 64),
    ("actor_level", 40),
    ("hostile_player_tank_requested", False),
    ("recovery_request", {"recovery_policy": "decisions",
                          "health_threshold": 0.9, "mana_threshold": 0.25}),
])
def test_cached_attempt_must_match_exact_paid_candidate_even_on_refusal(
        tmp_path, monkeypatch, field, altered):
    args, predecessor = _setup(tmp_path, trees=(0, 1))
    paid = _fake_native(monkeypatch, predecessor, times=(900, None))
    world.run(**args, max_new_trials=2)
    summary = next(args["out"].glob("candidate_02_*/native_l21/summary.json"))
    payload = json.loads(summary.read_text())
    payload["results"][0][field] = altered
    summary.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="cached native attempt differs"):
        world.run(**args, max_new_trials=0)
    assert paid == [1, 2]  # genuine refused native trials are never replayed


def test_bounded_native_finalists_spread_across_prepared_trees(
        tmp_path, monkeypatch):
    """A successful later tree cannot be crowded out by early same-tree rows."""
    args, predecessor = _setup(tmp_path)
    proposal = json.loads(args["shortlist"].read_text())
    original_first = proposal["candidates"][0]
    extra = []
    for number, points in ((4, 2), (5, 3)):
        variant = json.loads(
            (args["shortlist"].parent / original_first["source_request"]).read_text())
        variant["raid"]["parties"][0]["players"][0]["talentsString"] = (
            f"{points}-0-011")
        path = args["shortlist"].parent / "candidate_attempts" / (
            f"candidate_{number:02d}.json")
        path.write_text(json.dumps(variant))
        row = copy.deepcopy(original_first)
        row["source_request"] = f"candidate_attempts/candidate_{number:02d}.json"
        row["source_request_sha256"] = world.native_source.sha256(path)
        row["candidate_talents"] = variant["raid"]["parties"][0]["players"][0]["talentsString"]
        extra.append(row)
    # Before this production fix, the first three prepared requests all came
    # from tree 0. The bounded paid budget never measured Demo/Destruction.
    proposal["candidates"] = [
        proposal["candidates"][0], *extra,
        proposal["candidates"][1], proposal["candidates"][2],
    ]
    args["shortlist"].write_text(json.dumps(proposal))
    selected = world._candidate_sources(
        proposal, args["shortlist"].parent, json.loads(args["source"].read_text()), 3)
    assert [row["tree_index"] for row, _ in selected] == [0, 1, 2]

    paid = _fake_native(monkeypatch, predecessor, times=(900, 750, 1000))
    result = world.run(**args, max_candidates=3, max_new_trials=3)
    assert paid == [1, 2, 3]
    assert [row["tree_index"] for row in result["candidates"]] == [0, 1, 2]
    assert result["status"] == "MEASURED_SAME_BUILD_FAMILY_100"
    assert result["world_winner"]["tree_index"] == 1
    assert result["world_winner"]["elapsed_seconds"] == 750


def test_native_cross_tree_workflow_opt_in_and_evidence_preservation():
    """Only explicit label/dispatch may spend native 100-mob world compute."""
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
                / "native-paid-route-regressions.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "github.event.action == 'labeled'" in workflow
    assert "github.event.label.name == 'work1-native-world'" in workflow
    assert "wf_warlock_next_level_source.py" in workflow
    assert "wf_warlock_shortlist_world.py" in workflow
    assert "wf_warlock_paid_artifact.py" in workflow
    assert "actions/upload-artifact@v4" in workflow


@pytest.mark.parametrize("times, ties", [
    ((777.7, 777.7, 777.7), [1, 2, 3]),
    ((800.0, 800.0, 950.0), [1, 2]),
])
def test_equal_paid_native_world_elapsed_has_no_invented_talent_winner(
        tmp_path, monkeypatch, times, ties):
    args, predecessor = _setup(tmp_path)
    paid = _fake_native(monkeypatch, predecessor, times=times)
    result = world.run(**args, max_new_trials=3, max_candidates=3)
    assert paid == [1, 2, 3]
    assert result["status"] == "MEASURED_SAME_BUILD_FAMILY_TIE_100"
    assert result["tied_best_candidate_indexes"] == ties
    assert result["world_winner"] is None
    assert result["pending_candidate_indexes"] == []
    assert all(row["status"] == "MEASURED_NATIVE_100"
               for row in result["candidates"])



def test_paid_l47_one_rank_choices_are_all_destruction_heavy():
    """Cross-tree new-point labels do not establish Affli/Demo/Destro builds."""
    variants = (
        "1-0-2555355132000000",  # new Affliction point
        "0-1-2555355132000000",  # new Demonology point
        "0-0-2555355133000000",  # new Destruction point
    )
    invested = [world._talent_points_by_tree(talents) for talents in variants]
    assert [world._dominant_talent_tree(points) for points in invested] == [2, 2, 2]
    assert invested[0][0] == 1 and invested[0][2] > 20
    assert invested[1][1] == 1 and invested[1][2] > 20
    assert invested[2][2] > invested[0][2]


def test_paid_rank_tree_is_not_misreported_as_distinct_build_family(
        tmp_path, monkeypatch):
    args, predecessor = _setup(tmp_path)
    paid = _fake_native(monkeypatch, predecessor, times=(777.7, 777.7, 777.7))
    result = world.run(**args, max_new_trials=3)
    assert paid == [1, 2, 3]
    assert result["status"] == "MEASURED_SAME_BUILD_FAMILY_TIE_100"
    assert result["distinct_build_families_compared"] is False
    assert result["source_talent_points_by_tree"] == [0, 0, 2]
    assert result["source_dominant_talent_tree_index"] == 2
    assert result["measured_dominant_talent_tree_indexes"] == [2]
    assert [candidate["tree_index"] for candidate in result["candidates"]] == [0, 1, 2]
    assert [candidate["dominant_talent_tree_index"]
            for candidate in result["candidates"]] == [2, 2, 2]
    assert result["world_winner"] is None
    assert result["new_native_100_trials"] == 3


def test_genuinely_different_dominant_build_families_keep_cross_tree_status(
        tmp_path, monkeypatch):
    args, predecessor = _setup(tmp_path)
    proposal = json.loads(args["shortlist"].read_text())
    for row, talents in zip(proposal["candidates"],
                            ("333-0-011", "0-333-011", "0-0-333")):
        candidate_path = args["shortlist"].parent / row["source_request"]
        candidate = json.loads(candidate_path.read_text())
        candidate["raid"]["parties"][0]["players"][0]["talentsString"] = talents
        candidate_path.write_text(json.dumps(candidate))
        row["candidate_talents"] = talents
        row["source_request_sha256"] = world.native_source.sha256(candidate_path)
    args["shortlist"].write_text(json.dumps(proposal))
    paid = _fake_native(monkeypatch, predecessor, times=(900, 750, 1000))
    result = world.run(**args, max_new_trials=3)
    assert paid == [1, 2, 3]
    assert result["distinct_build_families_compared"] is True
    assert result["measured_dominant_talent_tree_indexes"] == [0, 1, 2]
    assert result["status"] == "MEASURED_CROSS_TREE_100"
    assert result["world_winner"]["candidate_index"] == 2
