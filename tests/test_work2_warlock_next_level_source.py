import copy
import json
import subprocess

import pytest

from tools import wf_warlock_next_level_source as next_level


def source_file(tmp_path):
    source = {
        "encounter": {"targets": [{"level": 20, "stats": [0] * 40}]},
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "talentsString": "0-0-011",
            "rotation": {"priorityList": []},
        }]}]},
    }
    path = tmp_path / "l20.json"
    path.write_text(json.dumps(source))
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"selected native executable for test transport")
    return path, binary


def native_options():
    return {
        "level": 21, "source_revision": "selected-native-test",
        "talents": {
            "status": "ok", "points_available": 3,
            "trees": [
                {"talents": [{"index": 0, "field_name": "affliction_option",
                              "max_rank": 2}]},
                {"talents": [{"index": 0, "field_name": "demonology_option",
                              "max_rank": 2}]},
                {"talents": [
                    {"index": 0, "field_name": "dest_first", "max_rank": 1},
                    {"index": 1, "field_name": "dest_second", "max_rank": 4},
                    {"index": 2, "field_name": "dest_third", "max_rank": 4},
                ]},
            ],
        },
    }


def test_adjacent_source_uses_native_options_and_prepares_selected_actor(tmp_path, monkeypatch):
    source, binary = source_file(tmp_path)
    seen = []
    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        if cmd[1] == "options":
            assert cmd[-2:] == ["--level", "21"]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(native_options()))
        assert cmd[1] == "prepare" and cmd[cmd.index("--actor-level") + 1] == "21"
        request = json.loads(open(cmd[cmd.index("--request") + 1]).read())
        assert request["encounter"]["targets"][0]["level"] == 21
        assert request["raid"]["parties"][0]["players"][0]["level"] == 21
        assert request["raid"]["parties"][0]["players"][0]["talentsString"] == "0-0-021"
        with open(cmd[cmd.index("--outfile") + 1], "w") as f:
            json.dump({"player": {"level": 21, "class": "ClassWarlock"}}, f)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    out = tmp_path / "result"
    receipt = next_level.propose(binary=binary, source=source, out=out)
    assert len(seen) == 2
    assert receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert receipt["from_level"] == 20 and receipt["to_level"] == 21
    assert receipt["candidate_talents"] == "0-0-021"
    assert receipt["source_talents"] == "0-0-011"
    assert json.loads((out / "source_request.json").read_text())[
        "raid"]["parties"][0]["players"][0]["talentsString"] == "0-0-021"
    assert receipt["native_options_source_revision"] == "selected-native-test"
    assert receipt["selected_source_sha256"] == next_level.sha256(out / "source_request.json")


def test_native_refusal_is_preserved_without_false_candidate(tmp_path, monkeypatch):
    source, binary = source_file(tmp_path)
    def fake_run(cmd, **kwargs):
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(native_options()))
        return subprocess.CompletedProcess(cmd, 1, stderr="native PREPARE_UNSUPPORTED")
    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    out = tmp_path / "result"
    with pytest.raises(RuntimeError, match="refused all"):
        next_level.propose(binary=binary, source=source, out=out)
    receipt = json.loads((out / "proposal.json").read_text())
    assert receipt["status"] == "NATIVE_PREPARE_REFUSED_ALL_PROPOSALS"
    assert receipt["native_refusals"]
    assert "PREPARE_UNSUPPORTED" in receipt["native_refusals"][0]["reason"]
    assert not (out / "source_request.json").exists()


def test_native_options_budget_and_source_level_must_match(tmp_path, monkeypatch):
    source, binary = source_file(tmp_path)
    data = native_options()
    data["talents"]["points_available"] = 2
    monkeypatch.setattr(next_level.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(data)))
    with pytest.raises(ValueError, match="native options cannot advance"):
        next_level.propose(binary=binary, source=source, out=tmp_path / "result")
    with pytest.raises(ValueError, match="adjacent level"):
        next_level.propose(binary=binary, source=source, out=tmp_path / "other",
                           from_level=20, to_level=22)


def test_native_unsupported_actor_level_is_one_causal_refusal(tmp_path, monkeypatch):
    source, binary = source_file(tmp_path)
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(native_options()))
        refusal = {"prepared": False, "refusal": {
            "code": "actor_level_source",
            "reason": "no selected native level 21 base stats for RaceTroll ClassWarlock"}}
        return subprocess.CompletedProcess(cmd, 1, stderr=json.dumps(refusal))
    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    out = tmp_path / "refused"
    receipt = next_level.propose(binary=binary, source=source, out=out)
    assert len(calls) == 2
    assert receipt["attempted"] == 1
    assert receipt["status"] == "NATIVE_ACTOR_LEVEL_UNSUPPORTED"
    assert receipt["native_refusals"][0]["native_refusal_code"] == "actor_level_source"
    assert "no selected native level 21" in receipt["native_refusals"][0]["reason"]
    assert not (out / "source_request.json").exists()
    assert json.loads((out / "proposal.json").read_text()) == receipt

def test_banked_l21_point_does_not_stop_source_native_l22_proposal(tmp_path, monkeypatch):
    """Real L21 continuation kept the new point unspent after Rust refusals.

    The next level must still reach native prepare instead of a Python
    points-available == spent + 1 veto. No native legality is inferred.
    """
    source, binary = source_file(tmp_path)
    raw = json.loads(source.read_text())
    raw["encounter"]["targets"][0]["level"] = 21
    raw["raid"]["parties"][0]["players"][0]["level"] = 21
    source.write_text(json.dumps(raw))
    options = native_options()
    options["level"] = 22
    options["talents"]["points_available"] = 4  # two banked at L22, not one
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        if cmd[1] == "options":
            assert cmd[-2:] == ["--level", "22"]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(options))
        assert cmd[1] == "prepare"
        assert cmd[cmd.index("--actor-level") + 1] == "22"
        candidate = json.loads(open(cmd[cmd.index("--request") + 1]).read())
        assert candidate["raid"]["parties"][0]["players"][0]["talentsString"] == "0-0-021"
        assert candidate["encounter"]["targets"][0]["level"] == 22
        assert candidate["raid"]["parties"][0]["players"][0]["level"] == 22
        with open(cmd[cmd.index("--outfile") + 1], "w") as f:
            json.dump({"player": {"level": 22, "class": "ClassWarlock"}}, f)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    out = tmp_path / "native_l22"
    receipt = next_level.propose(
        binary=binary, source=source, out=out, from_level=21, to_level=22)
    assert len(seen) == 2
    assert receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert receipt["from_level"] == 21 and receipt["to_level"] == 22
    assert receipt["source_talents"] == "0-0-011"
    assert receipt["candidate_talents"] == "0-0-021"
    assert receipt["selected_source_sha256"] == next_level.sha256(out / "source_request.json")


def test_native_budget_with_no_available_point_remains_unproposed(tmp_path, monkeypatch):
    source, binary = source_file(tmp_path)
    options = native_options()
    options["talents"]["points_available"] = 2
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert cmd[1] == "options"  # never submit a point above native budget
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(options))

    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="native options cannot advance"):
        next_level.propose(binary=binary, source=source, out=tmp_path / "blocked")
    assert len(calls) == 1


def test_l22_banked_talents_use_native_prepared_gear_subset(tmp_path, monkeypatch):
    source, binary = source_file(tmp_path)
    original = json.loads(source.read_text())
    original["encounter"]["targets"][0]["level"] = 21
    original["raid"]["parties"][0]["players"][0]["equipment"] = {
        "items": [{"id": 101}, {"id": 202}],
    }
    source.write_text(json.dumps(original))
    options = native_options()
    options["level"] = 22
    options["talents"]["points_available"] = 4
    requests = []

    def fake_run(cmd, **kwargs):
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(options))
        request = json.loads(open(cmd[cmd.index("--request") + 1]).read())
        requests.append(request)
        actor = request["raid"]["parties"][0]["players"][0]
        assert cmd[cmd.index("--actor-level") + 1] == "22"
        assert request["encounter"]["targets"][0]["level"] == 22
        items = actor["equipment"]["items"]
        if actor["talentsString"] != "0-0-011" or any(
                item.get("id") == 202 for item in items):
            return subprocess.CompletedProcess(cmd, 1, stderr=json.dumps({
                "refusal": {"code": "level", "reason": "native source refused loadout"}}))
        assert actor["level"] == 22
        with open(cmd[cmd.index("--outfile") + 1], "w") as f:
            json.dump({"player": {"level": 22, "class": "ClassWarlock"}}, f)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    out = tmp_path / "l22"
    receipt = next_level.propose(
        binary=binary, source=source, out=out,
        from_level=21, to_level=22, max_proposals=2)
    assert receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert receipt["selection"] == "native_prepared_carry_forward_with_item_probes"
    assert receipt["talent_points_newly_spent"] == 0
    assert receipt["candidate_talents"] == "0-0-011"
    assert receipt["native_gear_kept"] == [{"slot": 0, "id": 101}]
    assert receipt["native_gear_refusals"][0]["id"] == 202
    assert len(receipt["native_refusals_before_selection"]) == 2
    selected = json.loads((out / "source_request.json").read_text())
    assert selected["raid"]["parties"][0]["players"][0]["equipment"]["items"] == [
        {"id": 101}, {"id": 0}]
    assert requests[-1] == selected
    assert receipt["selected_source_sha256"] == next_level.sha256(out / "source_request.json")


def paid_predecessor(tmp_path):
    source, binary = source_file(tmp_path)
    original = json.loads(source.read_text())
    original["encounter"]["targets"][0]["level"] = 23
    original["raid"]["parties"][0]["players"][0]["level"] = 23
    source.write_text(json.dumps(original))
    report = {
        "class": "warlock",
        "measured_levels": [20, 21, 22, 23],
        "observations": [{
            "id": "paid-l23",
            "level": 23,
            "status": "measured_native_chain",
            "source_request_sha256": next_level.sha256(source),
            "engine_binary_sha256": next_level.sha256(binary),
            "native_world_ack": True,
            "paid_native_recovery": True,
            "targets_requested": 100,
            "targets_killed": 100,
            "native_actor": {"class": "ClassWarlock", "level": 23},
        }],
    }
    route = tmp_path / "route.json"
    route.write_text(json.dumps(report))
    return source, binary, route, report


def test_l24_proposal_uses_exact_paid_l23_predecessor(tmp_path, monkeypatch):
    source, binary, route, _ = paid_predecessor(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "options":
            options = native_options()
            options["level"] = 24
            options["talents"]["points_available"] = 15
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(options))
        assert cmd[1] == "prepare"
        assert cmd[cmd.index("--actor-level") + 1] == "24"
        request = json.loads(open(cmd[cmd.index("--request") + 1]).read())
        assert request["encounter"]["targets"][0]["level"] == 24
        assert request["raid"]["parties"][0]["players"][0]["level"] == 24
        with open(cmd[cmd.index("--outfile") + 1], "w") as prepared:
            json.dump({"player": {"level": 24, "class": "ClassWarlock"}}, prepared)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    receipt = next_level.propose(binary=binary, source=source,
                                  out=tmp_path / "l24", from_level=23,
                                  to_level=24, predecessor_route=route)
    assert receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert receipt["from_level"] == 23 and receipt["to_level"] == 24
    assert [cmd[1] for cmd in calls] == ["options", "prepare"]
    assert next_level.verified_paid_predecessor(
        route=route, source=source, binary=binary,
        from_level=23)["observation_id"] == "paid-l23"


def test_l24_rejects_unpaid_stale_or_wrong_source_before_native_calls(tmp_path, monkeypatch):
    source, binary, route, report = paid_predecessor(tmp_path)
    calls = []
    monkeypatch.setattr(next_level.subprocess, "run",
                        lambda *args, **kw: calls.append(args) or None)

    report["observations"][0]["targets_killed"] = 99
    route.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="matching completed paid native predecessor"):
        next_level.propose(binary=binary, source=source, out=tmp_path / "partial",
                           from_level=23, to_level=24, predecessor_route=route)

    report["observations"][0]["targets_killed"] = 100
    report["measured_levels"] = [20, 21, 22]
    route.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="does not include the paid source level"):
        next_level.propose(binary=binary, source=source, out=tmp_path / "stale",
                           from_level=23, to_level=24, predecessor_route=route)

    report["measured_levels"] = [20, 21, 22, 23]
    route.write_text(json.dumps(report))
    original = json.loads(source.read_text())
    original["raid"]["parties"][0]["players"][0]["talentsString"] = "0-0-012"
    source.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="matching completed paid native predecessor"):
        next_level.propose(binary=binary, source=source, out=tmp_path / "unpaid",
                           from_level=23, to_level=24, predecessor_route=route)
    assert calls == []


def test_native_options_refusal_is_published_without_prepared_candidate(tmp_path, monkeypatch):
    source, binary = source_file(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert cmd[1] == "options"
        return subprocess.CompletedProcess(
            cmd, 2, stderr=json.dumps({
                "refusal": {"code": "source_level_unavailable",
                            "reason": "native L25 options unavailable"}}))

    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    out = tmp_path / "refused_options"
    with pytest.raises(RuntimeError, match="NATIVE_OPTIONS_REFUSAL"):
        next_level.propose(binary=binary, source=source, out=out)
    receipt = json.loads((out / "proposal.json").read_text())
    assert len(calls) == 1
    assert receipt["status"] == "NATIVE_OPTIONS_REFUSED"
    assert receipt["attempted"] == 0
    assert receipt["native_refusals"][0]["stage"] == "options"
    assert receipt["native_refusals"][0]["native_refusal_code"] == "source_level_unavailable"
    assert receipt["original_source_sha256"] == next_level.sha256(source)
    assert receipt["native_binary_sha256"] == next_level.sha256(binary)
    assert not (out / "source_request.json").exists()


def test_paid_l20_predecessor_inside_l20_l28_report_requires_same_binary(tmp_path, monkeypatch):
    """Historical later levels cannot veto a real L20 source, nor authorize another binary."""
    source, binary = source_file(tmp_path)
    observed = {
        "id": "paid-l20", "level": 20, "status": "measured_native_chain",
        "source_request_sha256": next_level.sha256(source),
        "engine_binary_sha256": next_level.sha256(binary),
        "targets_requested": 100, "targets_killed": 100,
        "native_world_ack": True, "paid_native_recovery": True,
        "native_actor": {"class": "ClassWarlock", "level": 20},
    }
    route = tmp_path / "historical.json"
    route.write_text(json.dumps({
        "class": "warlock", "measured_levels": list(range(20, 29)),
        "observations": [observed, {
            **observed, "id": "old-l21", "level": 21,
            "engine_binary_sha256": "f" * 64,
            "native_actor": {"class": "ClassWarlock", "level": 21},
        }],
    }))
    seen = []
    def native(cmd, **kwargs):
        seen.append(cmd[1])
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(native_options()))
        request = json.loads(open(cmd[cmd.index("--request") + 1]).read())
        assert request["encounter"]["targets"][0]["level"] == 21
        with open(cmd[cmd.index("--outfile") + 1], "w") as output:
            json.dump({"player": {"class": "ClassWarlock", "level": 21}}, output)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(next_level.subprocess, "run", native)
    receipt = next_level.propose(
        binary=binary, source=source, out=tmp_path / "accepted",
        predecessor_route=route)
    assert receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert seen == ["options", "prepare"]

    observed["engine_binary_sha256"] = "0" * 64
    route.write_text(json.dumps({
        "class": "warlock", "measured_levels": list(range(20, 29)),
        "observations": [observed],
    }))
    seen.clear()
    with pytest.raises(ValueError, match="matching completed paid native predecessor"):
        next_level.propose(
            binary=binary, source=source, out=tmp_path / "refused",
            predecessor_route=route)
    assert not seen



def test_native_source_level_refusal_stops_after_one_preparation(tmp_path, monkeypatch):
    """Exact paid L41 native refusal is independent of candidate gear/talents."""
    source, binary = source_file(tmp_path)
    original = json.loads(source.read_text())
    original["encounter"]["targets"][0]["level"] = 40
    original["raid"]["parties"][0]["players"][0]["level"] = 40
    source.write_text(json.dumps(original))
    options = native_options()
    options["level"] = 41
    options["talents"]["points_available"] = 32
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[1])
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(options))
        return subprocess.CompletedProcess(cmd, 2, stderr=json.dumps({
            "prepared": False,
            "refusal": {"code": "level", "reason": (
                "player level 41 is unsupported: no source-backed native preparation "
                "for RaceTroll ClassWarlock (supported: Troll Warlock L10-L40)"
            )},
        }))

    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    receipt = next_level.propose(binary=binary, source=source,
                                 out=tmp_path / "l41", from_level=40, to_level=41)
    assert calls == ["options", "prepare"]
    assert receipt["status"] == "NATIVE_ACTOR_LEVEL_UNSUPPORTED"
    assert receipt["attempted"] == 1
    assert receipt["native_refusals"][0]["native_refusal_code"] == "level"
    assert "player level 41 is unsupported" in receipt["native_refusals"][0]["reason"]
    assert not (tmp_path / "l41/source_request.json").exists()


def test_non_source_native_level_refusal_does_not_veto_other_talents(tmp_path, monkeypatch):
    """A generic native code=level can be candidate-specific; keep exploring."""
    source, binary = source_file(tmp_path)
    options = native_options()
    attempts = []

    def fake_run(cmd, **kwargs):
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(options))
        attempts.append(cmd)
        if len(attempts) == 1:
            return subprocess.CompletedProcess(cmd, 2, stderr=json.dumps({
                "refusal": {"code": "level", "reason": "candidate item level too high"},
            }))
        with open(cmd[cmd.index("--outfile") + 1], "w") as out:
            json.dump({"player": {"level": 21, "class": "ClassWarlock"}}, out)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    receipt = next_level.propose(binary=binary, source=source,
                                 out=tmp_path / "retained")
    assert len(attempts) == 2
    assert receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert receipt["native_refusals_before_selection"][0]["native_refusal_code"] == "level"


def test_l41_cross_engine_requires_explicit_paid_l40_binary_provenance(tmp_path, monkeypatch):
    """A source-native upgrade must not silently relabel old L40 combat as new-engine evidence."""
    source, old_binary, route, report = paid_predecessor(tmp_path)
    new_binary = tmp_path / "upgraded-native-engine"
    new_binary.write_bytes(b"distinct selected Rust executable for L41")
    old_sha = next_level.sha256(old_binary)
    new_sha = next_level.sha256(new_binary)
    assert old_sha != new_sha
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[1])
        if cmd[1] == "options":
            options = native_options()
            options["level"] = 24
            options["talents"]["points_available"] = 15
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(options))
        with open(cmd[cmd.index("--outfile") + 1], "w") as result:
            json.dump({"player": {"level": 24, "class": "ClassWarlock"}}, result)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(next_level.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="matching completed paid native predecessor"):
        next_level.propose(
            binary=new_binary, source=source, predecessor_route=route,
            out=tmp_path / "same-only", from_level=23, to_level=24)
    with pytest.raises(ValueError, match="exact paid route"):
        next_level.propose(
            binary=new_binary, source=source, out=tmp_path / "missing-route",
            from_level=23, to_level=24, predecessor_binary_sha256=old_sha)
    with pytest.raises(ValueError, match="64 lowercase hex"):
        next_level.propose(
            binary=new_binary, source=source, predecessor_route=route,
            out=tmp_path / "bad-digest", from_level=23, to_level=24,
            predecessor_binary_sha256="not-a-sha")
    assert calls == []

    receipt = next_level.propose(
        binary=new_binary, source=source, predecessor_route=route,
        out=tmp_path / "cross-engine", from_level=23, to_level=24,
        predecessor_binary_sha256=old_sha)
    assert calls == ["options", "prepare"]
    assert receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert receipt["paid_predecessor"]["observation_id"] == "paid-l23"
    assert receipt["paid_predecessor"]["engine_binary_sha256"] == old_sha
    assert receipt["paid_predecessor"]["successor_engine_binary_sha256"] == new_sha
    assert receipt["paid_predecessor"]["cross_engine_source_transition"] is True
    assert receipt["native_binary_sha256"] == new_sha

    report["observations"][0]["targets_killed"] = 99
    route.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="matching completed paid native predecessor"):
        next_level.propose(
            binary=new_binary, source=source, predecessor_route=route,
            out=tmp_path / "unpaid", from_level=23, to_level=24,
            predecessor_binary_sha256=old_sha)
    assert calls == ["options", "prepare"]
