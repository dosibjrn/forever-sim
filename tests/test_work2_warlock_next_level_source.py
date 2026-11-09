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
