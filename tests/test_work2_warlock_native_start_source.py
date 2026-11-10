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
        # The native prepare CLI reads level from the source request.
        # Forwarding --actor-level is rejected by the selected Rust engine.
        assert "--actor-level" not in cmd
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


def _accept_native_prepare(cmd, **kwargs):
    # Native is the only judge of request legality and prepared actor identity.
    request_path = cmd[cmd.index("--request") + 1]
    assert "--actor-level" not in cmd
    import hashlib
    with open(cmd[-1], "w") as output:
        json.dump({"request_sha256": hashlib.sha256(
            open(request_path, "rb").read()).hexdigest(),
            "player": {"class": "ClassWarlock", "race": "RaceTroll",
                       "level": 20, "stats": {
                           "Health": 1000.0, "Mana": 1200.0}}}, output)
    return subprocess.CompletedProcess(cmd, 0)


def test_paid_source_selects_later_recovered_native_candidate(tmp_path, monkeypatch):
    from tools import wf_warlock_native_candidate_scoring as scorer
    source, binary = _fixture(tmp_path)
    monkeypatch.setattr(start.subprocess, "run", _accept_native_prepare)
    seen = []

    def native_paid(*, binary, prepared_paths, actor_level, mob_count,
                    target_hp, artifact_dir):
        seen.append((list(prepared_paths), actor_level, mob_count,
                     target_hp, artifact_dir))
        assert set(("full", "empty", "without_slot_01")).issubset(prepared_paths)
        assert all(path.is_file() for path in prepared_paths.values())
        return {"comparable_candidates": 2, "candidates": [
            {"candidate_id": "full", "status": "MEASURED_NATIVE_FULLY_RECOVERED",
             "elapsed_seconds": 29.0},
            {"candidate_id": "without_slot_01",
             "status": "MEASURED_NATIVE_FULLY_RECOVERED",
             "elapsed_seconds": 18.0},
            {"candidate_id": "empty", "status": "NATIVE_REFUSAL",
             "elapsed_seconds": None}]}

    monkeypatch.setattr(scorer, "compare_prepared_candidates", native_paid)
    out = tmp_path / "scored"
    receipt = start.select_prepared_source(
        binary=binary, source=source, out=out, mob_count=3,
        target_hp=900.0, max_scored_candidates=4)
    assert len(seen) == 1
    assert seen[0][1:4] == (20, 3, 900.0)
    assert receipt["status"] == "NATIVE_PAID_BOUNDED_COMPARISON"
    assert receipt["selected_candidate_id"] == "without_slot_01"
    assert receipt["kept_equipment_slots"] == [0, 2]
    assert receipt["rng_mode"] == "balanced"
    assert receipt["recover_to_full"] is True
    assert receipt["iterations"] == 1
    assert [entry["candidate"] for entry in receipt["native_accepted"]][:2] == [
        "full", "empty"]
    selected = json.loads((out / "source_request.json").read_text())
    assert [row["id"] for row in selected["raid"]["parties"][0][
        "players"][0]["equipment"]["items"]] == [101, 0, 303]


def test_paid_source_refuses_to_publish_unrecovered_preparable_actor(
        tmp_path, monkeypatch):
    from tools import wf_warlock_native_candidate_scoring as scorer
    source, binary = _fixture(tmp_path)
    monkeypatch.setattr(start.subprocess, "run", _accept_native_prepare)

    def native_unrecovered(*, prepared_paths, **kwargs):
        return {"comparable_candidates": 0, "candidates": [
            {"candidate_id": tag,
             "status": "NATIVE_TERMINAL_FULL_RECOVERY_NOT_RECORDED",
             "elapsed_seconds": None} for tag in prepared_paths]}

    monkeypatch.setattr(scorer, "compare_prepared_candidates",
                        native_unrecovered)
    out = tmp_path / "unrecovered"
    receipt = start.select_prepared_source(
        binary=binary, source=source, out=out, mob_count=3, target_hp=900.0)
    assert receipt["status"] == "NATIVE_PAID_NO_FULLY_RECOVERED_CANDIDATE"
    assert receipt["selected_candidate_id"] is None
    assert not (out / "source_request.json").exists()
    assert receipt["proposals_prepared"] >= 2
    assert json.loads((out / "proposal.json").read_text()) == receipt


def test_paid_mode_rejects_free_reset_and_one_mob_configuration(tmp_path):
    import pytest
    source, binary = _fixture(tmp_path)
    for mobs, hp in ((1, 1000.0), (3, None), (3, 0.0), (101, 1000.0)):
        with pytest.raises(ValueError):
            start.select_prepared_source(
                binary=binary, source=source, out=tmp_path / "bad",
                mob_count=mobs, target_hp=hp)
    with pytest.raises(ValueError):
        start.select_prepared_source(
            binary=binary, source=source, out=tmp_path / "bad",
            target_hp=1000.0)
