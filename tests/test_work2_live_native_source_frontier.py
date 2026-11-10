"""Work2 live source frontier / scorer transport tests (no Rust gameplay oracle)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from tools.wf_warlock_native_source_frontier import produce_frontier


def _root_source(tmp_path: Path):
    seed = tmp_path / "L20.source.json"
    seed.write_text(json.dumps({
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "level": 20, "talentsString": "11-0-0",
        }]}]},
        "encounter": {"targets": [{"level": 20}]},
    }))
    binary = tmp_path / "selected-native"
    binary.write_bytes(b"mock selected Rust executable identity")
    return seed, binary


def _request(level=20, parent=None, budget=3):
    return {
        "level": level, "parent": parent, "budget": budget, "mob_count": 3,
        "rng_mode": "balanced", "iterations": 1, "recover_to_full": True,
    }


def test_live_root_asks_native_options_and_prepares_distinct_proposals(tmp_path):
    seed, binary = _root_source(tmp_path)
    calls = []

    def native(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "options":
            assert cmd[-1] == "20"
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
                "level": 20, "talents": {"status": "ok", "trees": [
                    {"talents": [{"index": 0, "max_rank": 5},
                                 {"index": 1, "max_rank": 5}]},
                    {"talents": []}, {"talents": []},
                ]},
            }))
        source = Path(cmd[cmd.index("--request") + 1])
        prepared = Path(cmd[cmd.index("--outfile") + 1])
        original = json.loads(source.read_text())
        assert original["raid"]["parties"][0]["players"][0]["level"] == 20
        prepared.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": 20,
                       "stats": {"Health": 100, "Mana": 200}},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    found = produce_frontier(_request(), binary=binary, seed_source=seed,
                             out=tmp_path / "prepared", runner=native)
    assert len(found["entries"]) == 3
    assert len(calls) == 4  # One source-options call, three real native prepares
    assert found["refusals"] == []
    proposals = [json.loads(Path(r["source_request"]).read_text())
                 ["raid"]["parties"][0]["players"][0]["talentsString"]
                 for r in found["entries"]]
    assert len(set(proposals)) == 3
    assert all(Path(r["prepared"]).exists() for r in found["entries"])


def test_native_prepare_refusals_preserve_budget_and_original_reason(tmp_path):
    seed, binary = _root_source(tmp_path)

    def native(cmd, **kwargs):
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
                "level": 20, "talents": {"status": "ok", "trees": [
                    {"talents": [{"index": 0, "max_rank": 5},
                                 {"index": 1, "max_rank": 5}]},
                    {"talents": []}, {"talents": []},
                ]},
            }))
        if "source_001" in cmd[cmd.index("--request") + 1]:
            return subprocess.CompletedProcess(
                cmd, 2, stderr="native talent prepare refused")
        source = Path(cmd[cmd.index("--request") + 1])
        prepared = Path(cmd[cmd.index("--outfile") + 1])
        prepared.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": 20},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    result = produce_frontier(_request(budget=3), binary=binary, seed_source=seed,
                              out=tmp_path / "prepared", runner=native)
    assert len(result["entries"]) == 2
    assert len(result["refusals"]) == 1
    assert "native talent prepare refused" in result["refusals"][0]["native_refusal"]


def test_future_level_requires_real_continuation_without_native_calls(tmp_path):
    result = produce_frontier(
        _request(level=30, parent={"level": 20, "source_request_sha256": "a" * 64}),
        binary=tmp_path / "missing", seed_source=tmp_path / "missing",
        out=tmp_path / "unused", runner=lambda *a, **k: 1 / 0,
    )
    assert result["entries"] == []
    assert result["refusals"][0]["status"] == "NATIVE_CONTINUITY_NOT_ATTESTED"


def test_live_frontier_is_called_in_same_range_optimizer_request(tmp_path, monkeypatch):
    from tools import wf_warlock_native_range_optimize as cli
    from tools import wf_warlock_native_range_scored_adapter as adapter
    def receipt(level, mobs, label, seconds):
        source = (f"{level:02x}{ord(label):02x}" + "a" * 60)
        return {
            "status": "measured_native_world", "level": level,
            "mob_count": mobs, "targets_killed": mobs,
            "rng_mode": "balanced", "iterations": 1,
            "native_prepared": True, "native_world_ack": True,
            "native_full_recovery_paid": True, "recover_to_full": True,
            "terminal_hp": 100.0, "terminal_max_hp": 100.0,
            "terminal_mana": 200.0, "terminal_max_mana": 200.0,
            "elapsed_seconds": seconds, "terminal_recovery_seconds": 1.0,
            "source_request_sha256": source,
            "engine_binary_sha256": "b" * 64, "talents": label,
        }

    binary = tmp_path / "selected-native"
    binary.write_bytes(b"mock native")
    calls = []

    def native_producer(cmd, *, input, capture_output, text, timeout, check):
        request = json.loads(input)
        calls.append((cmd, request))
        if request["level"] == 20:
            payload = {"entries": [{"id": "a", "level": 20},
                                   {"id": "b", "level": 20}]}
        else:
            payload = {"entries": [], "refusals": [{
                "status": "NATIVE_CONTINUITY_NOT_ATTESTED",
                "native_refusal": "no native source continuation ACK",
            }]}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload))

    def scorer(request, *, manifest, binary, target_hp, scorer_command, artifact_dir):
        payload = json.loads(manifest.read_text())
        assert artifact_dir.is_dir() and binary.is_file()
        assert scorer_command == ["work1-scorer"]
        if request["parent"] is None:
            assert len(payload["entries"]) == 2
            return [receipt(20, 3, "A", 9.0), receipt(20, 3, "B", 5.0)]
        assert payload["refusals"][0]["status"] == "NATIVE_CONTINUITY_NOT_ATTESTED"
        return [{"status": "NATIVE_CONTINUITY_NOT_ATTESTED",
                 "native_prepared": False,
                 "native_refusal": "no native source continuation ACK"}]

    monkeypatch.setattr(cli.subprocess, "run", native_producer)
    monkeypatch.setattr(adapter, "evaluate_request", scorer)
    out = tmp_path / "range.json"
    code = cli.main([
        "--start-level", "20", "--end-level", "60", "--level-stride", "10",
        "--mob-count", "3", "--budget", "20", "--beam-width", "2",
        "--native-frontier-command", "native-source-frontier --pinned",
        "--native-binary", str(binary), "--native-target-hp", "400",
        "--native-scorer-command", "work1-scorer",
        "--native-receipts-dir", str(tmp_path / "retained"),
        "--out", str(out),
    ])
    report = json.loads(out.read_text())
    assert code == 2  # Proven L20 root, but no invented L30..L60 ancestry
    assert report["sampled_levels_requested"] == [20, 30, 40, 50, 60]
    assert report["sampled_levels_completed"] == [20]
    assert len(report["ranked_alternatives"]) == 2
    assert [request["level"] for _, request in calls] == [20, 30, 30]
    assert all(request["mob_count"] == 3 and request["iterations"] == 1
               and request["recover_to_full"] for _, request in calls)


def test_manifest_native_frontier_refusal_is_not_scored(tmp_path):
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"entries": [], "refusals": [{
        "status": "NATIVE_OPTIONS_REFUSED",
        "candidate_id": "affliction",
        "native_refusal": "source-native actor unsupported",
    }]}))
    rows = evaluate_request(
        _request(budget=1), manifest=manifest,
        binary=tmp_path / "unneeded", target_hp=400,
        scorer_command=["work1-scorer"], artifact_dir=tmp_path / "receipts",
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "NATIVE_OPTIONS_REFUSED"
    assert rows[0]["native_prepared"] is False
    assert rows[0]["native_refusal"] == "source-native actor unsupported"
