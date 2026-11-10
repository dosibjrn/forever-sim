import copy
import json
import subprocess

import pytest

from tools import wf_warlock_l40_alternative as alt


def paid_fixture(tmp_path):
    source = tmp_path / "paid_l40.json"
    request = {
        "encounter": {"targets": [{"level": 40, "stats": [0] * 40}]},
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "race": "RaceTroll", "level": 40,
            "talentsString": "0-0-12",
            "equipment": {"items": [{"id": 123}]},
            "rotation": {"priorityList": [{"action": {"wait": {"duration": "1s"}}}]},
            "warlockOptions": {"summon": "Succubus"},
        }]}]},
    }
    source.write_text(json.dumps(request))
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"the exact selected native binary")
    row = {
        "id": "original-paid-l40",
        "level": 40,
        "status": "measured_native_chain",
        "source_request_sha256": alt.digest(source),
        "engine_binary_sha256": alt.digest(binary),
        "native_world_ack": True,
        "paid_native_recovery": True,
        "targets_requested": 100,
        "targets_killed": 100,
        "native_actor": {"class": "ClassWarlock", "level": 40},
        "scenario": "Hostile retained actor native L40 same mob",
        "recovery_policy": {"recovery_policy": "decisions", "health_threshold": 0.7,
                            "mana_threshold": 0.25},
        "elapsed_seconds_for_observed_chain": 900.0,
    }
    route = tmp_path / "paid_l40_route.json"
    route.write_text(json.dumps({
        "class": "warlock", "measured_levels": [40], "observations": [row],
    }))
    return source, binary, route, row


def native_options():
    return {"level": 40, "talents": {"status": "ok", "trees": [
        {"talents": [{"index": 0, "max_rank": 5}]},
        {"talents": [{"index": 0, "max_rank": 5}]},
        {"talents": [{"index": 0, "max_rank": 5},
                     {"index": 1, "max_rank": 5}]},
    ]}}


def run_native(tmp_path, monkeypatch):
    source, binary, route, row = paid_fixture(tmp_path)
    calls = []

    def fake(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "options":
            assert cmd[-2:] == ["--level", "40"]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(native_options()))
        assert cmd[1] == "prepare"
        assert cmd[cmd.index("--actor-level") + 1] == "40"
        candidate = json.loads(open(cmd[cmd.index("--request") + 1]).read())
        expected = json.loads(source.read_text())
        candidate_actor = alt.actor_of(candidate)
        expected_actor = alt.actor_of(expected)
        assert candidate_actor["talentsString"] != expected_actor["talentsString"]
        candidate_actor.pop("talentsString")
        expected_actor.pop("talentsString")
        assert candidate == expected  # source actor/gear/APL/encounter remain identical
        with open(cmd[cmd.index("--outfile") + 1], "w") as stream:
            json.dump({"player": {"class": "ClassWarlock", "level": 40}}, stream)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(alt.subprocess, "run", fake)
    out = tmp_path / "proposal"
    proposed = alt.propose(binary=binary, source=source,
                           baseline_route=route, out=out)
    return source, binary, route, row, out, proposed, calls


def test_proposes_distinct_native_prepared_l40_talent_without_changing_scenario(tmp_path, monkeypatch):
    source, binary, route, row, out, proposed, calls = run_native(tmp_path, monkeypatch)
    assert len(calls) == 2
    assert proposed["status"] == "NATIVE_PREPARED_NOT_YET_PAID"
    assert proposed["baseline_source_sha256"] == alt.digest(source)
    assert proposed["selected_source_sha256"] == alt.digest(out / "source_request.json")
    assert proposed["native_binary_sha256"] == alt.digest(binary)
    assert proposed["source_talents"] == "0-0-12"
    assert proposed["challenger_talents"] != "0-0-12"
    assert (out / "candidate_attempts/candidate_001.prepared.json").is_file()


def test_paid_comparison_requires_matching_receipts_and_does_not_claim_dual_spec(tmp_path, monkeypatch):
    source, binary, route, row, out, proposed, _ = run_native(tmp_path, monkeypatch)
    candidate = out / "source_request.json"
    changed = copy.deepcopy(row)
    changed.update(id="new-paid-l40", source_request_sha256=alt.digest(candidate),
                   elapsed_seconds_for_observed_chain=850.0)
    challenger_route = tmp_path / "challenger_route.json"
    challenger_route.write_text(json.dumps({"observations": [changed]}))
    comparison = alt.compare(
        baseline_route=route, baseline_source=source,
        challenger_route=challenger_route, challenger_source=candidate,
        proposal=out / "proposal.json", out=tmp_path / "comparison.json")
    assert comparison["status"] == "PAID_COMPARABLE_100_100"
    assert comparison["standalone_l40_seconds_saved"] == 50.0
    assert comparison["dual_spec_10_60_gain_measured"] is False
    assert comparison["no_purchase_default"] is True
    assert comparison["full_10_60_native_replay_executed"] is False

    changed["recovery_policy"]["health_threshold"] = 0.6
    challenger_route.write_text(json.dumps({"observations": [changed]}))
    with pytest.raises(ValueError, match="not comparable"):
        alt.compare(baseline_route=route, baseline_source=source,
                    challenger_route=challenger_route, challenger_source=candidate,
                    proposal=out / "proposal.json", out=tmp_path / "comparison.json")


def test_rejected_native_candidates_are_preserved_not_promoted(tmp_path, monkeypatch):
    source, binary, route, row = paid_fixture(tmp_path)
    calls = []
    def reject(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(native_options()))
        return subprocess.CompletedProcess(cmd, 1, stderr="native unsupported alternative")
    monkeypatch.setattr(alt.subprocess, "run", reject)
    out = tmp_path / "all_refused"
    with pytest.raises(RuntimeError, match="refused all"):
        alt.propose(binary=binary, source=source, baseline_route=route,
                    out=out, max_proposals=2)
    receipt = json.loads((out / "proposal.json").read_text())
    assert receipt["status"] == "NATIVE_PREPARE_REFUSED_ALL_PROPOSALS"
    assert len(receipt["native_refusals"]) == 2
    assert not (out / "source_request.json").exists()
    assert len(calls) == 3


def test_tampered_original_paid_actor_is_refused_before_native_options(tmp_path, monkeypatch):
    source, binary, route, _ = paid_fixture(tmp_path)
    raw = json.loads(source.read_text())
    alt.actor_of(raw)["level"] = 39
    source.write_text(json.dumps(raw))
    monkeypatch.setattr(alt.subprocess, "run",
                        lambda *a, **k: pytest.fail("must not invoke native"))
    with pytest.raises(ValueError, match="matching completed paid native predecessor"):
        alt.propose(binary=binary, source=source, baseline_route=route,
                    out=tmp_path / "out")


def test_comparison_cannot_promote_partial_paid_chain(tmp_path, monkeypatch):
    source, binary, route, row, out, proposed, _ = run_native(tmp_path, monkeypatch)
    candidate = out / "source_request.json"
    changed = copy.deepcopy(row)
    changed.update(id="partial", source_request_sha256=alt.digest(candidate),
                   targets_killed=99)
    challenger_route = tmp_path / "partial.json"
    challenger_route.write_text(json.dumps({"observations": [changed]}))
    with pytest.raises(ValueError, match="exact-source paid"):
        alt.compare(baseline_route=route, baseline_source=source,
                    challenger_route=challenger_route, challenger_source=candidate,
                    proposal=out / "proposal.json", out=tmp_path / "comparison.json")
