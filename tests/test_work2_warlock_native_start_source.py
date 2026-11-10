import json
import subprocess

from tools import wf_warlock_native_start_source as start


def _fixture(tmp_path, *, ids=(101, 202, 303)):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "race": "RaceTroll",
            "talentsString": "0-0-0550001000000000",
            "equipment": {"items": [{"id": x} for x in ids]},
        }]}]},
        "encounter": {"targets": [{"level": 20}]},
    }))
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"native executable identity")
    return source, binary


def test_preserves_full_source_when_native_accepts(tmp_path, monkeypatch):
    source, binary = _fixture(tmp_path)
    seen = []

    def native(cmd, **kwargs):
        request = json.loads(open(cmd[cmd.index("--request") + 1]).read())
        seen.append(request["raid"]["parties"][0]["players"][0]["equipment"]["items"])
        assert cmd[1] == "prepare" and cmd[-2] == "--outfile"
        assert cmd[cmd.index("--actor-level") + 1] == "20"
        with open(cmd[-1], "w") as f:
            json.dump({"player": {"class": "ClassWarlock",
                                  "race": "RaceTroll", "level": 20}}, f)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(start.subprocess, "run", native)
    out = tmp_path / "selected"
    receipt = start.select_prepared_source(binary=binary, source=source, out=out)
    assert seen == [[{"id": 101}, {"id": 202}, {"id": 303}]]
    assert receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert receipt["kept_equipment_slots"] == [0, 1, 2]
    assert receipt["proposals_refused"] == 0
    assert receipt["selected_source_sha256"] == start._sha256(out / "source_request.json")


def test_rejected_rating_gear_is_not_diagnosed_by_python(tmp_path, monkeypatch):
    source, binary = _fixture(tmp_path)
    seen = []

    def native(cmd, **kwargs):
        request = json.loads(open(cmd[cmd.index("--request") + 1]).read())
        items = request["raid"]["parties"][0]["players"][0]["equipment"]["items"]
        seen.append([i["id"] for i in items])
        if any(i["id"] == 202 for i in items):
            return subprocess.CompletedProcess(cmd, 2, stderr=json.dumps({
                "refusal": {"code": "level", "reason": "rating conversion source absent"}}))
        with open(cmd[-1], "w") as f:
            json.dump({"player": {"class": "ClassWarlock",
                                  "race": "RaceTroll", "level": 20}}, f)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(start.subprocess, "run", native)
    out = tmp_path / "selected"
    receipt = start.select_prepared_source(binary=binary, source=source, out=out)
    assert seen == [[101, 202, 303], [0, 0, 0],
                    [101, 0, 0], [101, 202, 0], [101, 0, 303]]
    assert receipt["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert receipt["kept_equipment_slots"] == [0, 2]
    assert len(receipt["native_refusals"]) == 2
    assert "rating conversion" in receipt["native_refusals"][0]["reason"]
    selected = json.loads((out / "source_request.json").read_text())
    assert [i["id"] for i in selected["raid"]["parties"][0]["players"][0]
            ["equipment"]["items"]] == [101, 0, 303]
    assert receipt["selected_source_sha256"] == start._sha256(out / "source_request.json")


def test_native_empty_loadout_refusal_does_not_fabricate_prepared_actor(tmp_path, monkeypatch):
    source, binary = _fixture(tmp_path)
    seen = []

    def native(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stderr="NATIVE_ACTOR_LEVEL_UNSUPPORTED")

    monkeypatch.setattr(start.subprocess, "run", native)
    out = tmp_path / "rejected"
    receipt = start.select_prepared_source(binary=binary, source=source, out=out)
    assert len(seen) == 2  # full then empty; no pointless item probes
    assert receipt["status"] == "NATIVE_PREPARE_REFUSED_ALL_SOURCES"
    assert receipt["kept_equipment_slots"] == []
    assert len(receipt["native_refusals"]) == 2
    assert not (out / "source_request.json").exists()
    assert json.loads((out / "proposal.json").read_text()) == receipt


def test_native_prepared_actor_level_mismatch_rejected(tmp_path, monkeypatch):
    source, binary = _fixture(tmp_path, ids=())
    def native(cmd, **kwargs):
        with open(cmd[-1], "w") as f:
            json.dump({"player": {"class": "ClassWarlock",
                                  "race": "RaceTroll", "level": 60}}, f)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(start.subprocess, "run", native)
    out = tmp_path / "wrong"
    receipt = start.select_prepared_source(binary=binary, source=source, out=out)
    assert receipt["status"] == "NATIVE_PREPARE_REFUSED_ALL_SOURCES"
    assert not (out / "source_request.json").exists()
