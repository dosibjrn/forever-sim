"""Forever-owned source forwarding and native-receipt tests, not talent rule audits."""
import copy
import json
import subprocess
from pathlib import Path

from tools import wf_warlock_full_family_shortlist as families
from tools import wf_warlock_next_level_source as source


def _setup(tmp_path):
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"test native executor")
    original = {
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "level": 46,
            "race": "RaceTroll", "talentsString": "0-0-211",
            "equipment": {"items": [{"id": 111}, {"id": 222}]},
            "rotation": {"priorityList": [{"action": "example-source-apl"}]},
            "pet": "PetFelhunter",
        }]}]},
        "encounter": {"targets": [{"level": 46, "stats": [0] * 40}],
                      "duration": 30},
        "simOptions": {"randomSeed": "1234"},
    }
    path = tmp_path / "source.json"
    path.write_text(json.dumps(original))
    route = tmp_path / "route.json"
    route.write_text(json.dumps({
        "class": "warlock", "measured_levels": [46],
        "observations": [{
            "id": "real-paid-l46", "level": 46, "status": "measured_native_chain",
            "source_request_sha256": source.sha256(path),
            "engine_binary_sha256": source.sha256(binary),
            "native_world_ack": True, "paid_native_recovery": True,
            "targets_requested": 100, "targets_killed": 100,
            "native_actor": {"class": "ClassWarlock", "level": 46},
        }],
    }))
    return path, binary, route, original


def _options():
    return {
        "level": 47, "source_revision": "selected-mythicsim",
        "talents": {
            "status": "ok", "points_available": 3,
            "trees": [{"talents": [{"index": 0, "max_rank": 3,
                                   "field_name": f"native_tree_{i}"}]}
                      for i in range(3)],
        },
    }


def _fake_native(monkeypatch, *, refused_families=(), missing_outputs=False):
    seen = []
    def call(cmd, **kwargs):
        seen.append(cmd)
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_options()))
        if cmd[1] == "prepare":
            req = json.loads(Path(cmd[cmd.index("--request") + 1]).read_text())
            actor = req["raid"]["parties"][0]["players"][0]
            assert actor["level"] == req["encounter"]["targets"][0]["level"] == 47
            points = [sum(int(char) for char in part)
                      for part in actor["talentsString"].split("-")]
            if any(points[family] for family in refused_families):
                return subprocess.CompletedProcess(cmd, 2, stderr="native rejected family")
            if not missing_outputs:
                Path(cmd[cmd.index("--outfile") + 1]).write_text(
                    json.dumps({"player": {"class": "ClassWarlock", "level": 47}}))
            return subprocess.CompletedProcess(cmd, 0)
        assert cmd[1] == "sim"
        Path(cmd[cmd.index("--outfile") + 1]).write_text(json.dumps({
            "result": {"raidMetrics": {"parties": [{"players": [
                {"dps": {"avg": 71.2}},
            ]}]}}
        }))
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(families.subprocess, "run", call)
    return seen


def test_three_complete_native_prepared_families_retain_exact_source_except_level_talents(
        tmp_path, monkeypatch):
    src, binary, route, original = _setup(tmp_path)
    seen = _fake_native(monkeypatch)
    out = tmp_path / "all"
    receipt = families.build(binary=binary, source=src, predecessor_route=route,
                             out=out)
    assert receipt["status"] == "NATIVE_SCREENED_NOT_WORLD_PAID"
    assert receipt["candidate_families_prepared"] == [0, 1, 2]
    assert receipt["native_options_points_available"] == 3
    assert receipt["paid_predecessor"]["observation_id"] == "real-paid-l46"
    assert [row["candidate_talents"] for row in receipt["candidates"]] == [
        "3-0-0", "0-3-0", "0-0-3"]
    assert [row["screen_status"] for row in receipt["candidates"]] == [
        "NATIVE_SCREEN_PAID"] * 3
    assert [row["talent_points_by_tree"] for row in receipt["candidates"]] == [
        [3, 0, 0], [0, 3, 0], [0, 0, 3]]
    assert receipt["talent_respec_cost_measured"] is False
    assert receipt["world_winner"] is None and receipt["m1_recording_performed"] is False
    assert sum(cmd[1] == "sim" for cmd in seen) == 3  # only 30-second screens
    assert sum(cmd[1] == "prepare" for cmd in seen) == 12
    for row in receipt["candidates"]:
        actual = json.loads((out / row["source_request"]).read_text())
        expected = copy.deepcopy(original)
        expected["raid"]["parties"][0]["players"][0]["level"] = 47
        expected["raid"]["parties"][0]["players"][0]["talentsString"] = row["candidate_talents"]
        expected["encounter"]["targets"][0]["level"] = 47
        assert actual == expected
        assert row["source_request_sha256"] == source.sha256(out / row["source_request"])
    assert json.loads((out / "native_paid_shortlist.json").read_text()) == receipt


def test_refused_full_family_cannot_be_reported_as_cross_family_paid_candidate(
        tmp_path, monkeypatch):
    src, binary, route, _ = _setup(tmp_path)
    seen = _fake_native(monkeypatch, refused_families=(0, 1))
    result = families.build(binary=binary, source=src, predecessor_route=route,
                            out=tmp_path / "refused")
    assert result["status"] == "NATIVE_SHORTLIST_NO_DISTINCT_FAMILIES"
    assert result["candidate_families_prepared"] == [2]
    assert len(result["candidates"]) == 1
    assert result["family_progress"][0]["full_native_prepared"] is False
    assert result["family_progress"][1]["full_native_prepared"] is False
    assert any("native rejected family" in row["reason"]
               for row in result["native_refusals"])
    assert sum(cmd[1] == "sim" for cmd in seen) == 1


def test_success_exit_with_no_native_output_does_not_reuse_stale_prepare(
        tmp_path, monkeypatch):
    src, binary, route, _ = _setup(tmp_path)
    seen = _fake_native(monkeypatch, missing_outputs=True)
    out = tmp_path / "stale"
    attempt = out / "candidate_attempts"
    attempt.mkdir(parents=True)
    (attempt / "family_0_probe_001.prepared.json").write_text(
        json.dumps({"player": {"class": "ClassWarlock", "level": 47}}))
    result = families.build(binary=binary, source=src, predecessor_route=route,
                            out=out, max_native_probes_per_family=3)
    assert result["status"] == "NATIVE_SHORTLIST_NO_DISTINCT_FAMILIES"
    assert result["candidates"] == []
    assert not (attempt / "family_0_probe_001.prepared.json").exists()
    assert sum(cmd[1] == "sim" for cmd in seen) == 0
    assert any(row["reason"] == "NATIVE_PREPARED_ACTOR_MISSING"
               for row in result["native_refusals"])


def test_paid_provenance_refused_before_querying_native_options(tmp_path, monkeypatch):
    src, binary, route, _ = _setup(tmp_path)
    report = json.loads(route.read_text())
    report["observations"][0]["targets_killed"] = 99
    route.write_text(json.dumps(report))
    seen = _fake_native(monkeypatch)
    import pytest
    with pytest.raises(ValueError, match="matching completed paid native predecessor"):
        families.build(binary=binary, source=src, predecessor_route=route,
                       out=tmp_path / "unpaid")
    assert seen == []


def test_workflow_uses_existing_opt_in_paid_comparator_after_full_native_family_screen():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
                / "native-paid-route-regressions.yml").read_text()
    assert "wf_warlock_full_family_shortlist.py" in workflow
    assert "wf_warlock_shortlist_world.py" in workflow
    assert "github.event.action == 'labeled'" in workflow
    assert "github.event.label.name == 'work1-native-world'" in workflow
    assert "actions/upload-artifact@v4" in workflow
