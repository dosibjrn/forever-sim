"""Work2 live source frontier / scorer transport tests (no Rust gameplay oracle)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

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
        # The production Rust prepare CLI has no --actor-level flag. The
        # request's actor level is already present in the native source JSON.
        assert cmd == [
            str(binary.resolve()), "prepare", "--request", str(source.resolve()),
            "--outfile", str(prepared.resolve()),
        ]
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



def test_tight_native_budget_reaches_other_talent_trees_before_seed_tweaks(tmp_path):
    """Paid proposals must compete across source-listed trees, not just Affliction."""
    seed, binary = _root_source(tmp_path)
    options = {"level": 20, "talents": {"status": "ok", "trees": [
        {"talents": [{"index": 0, "max_rank": 5},
                     {"index": 1, "max_rank": 5}]},
        {"talents": [{"index": 0, "max_rank": 5}]},
        {"talents": [{"index": 0, "max_rank": 5}]},
    ]}}
    prepared_talents = []

    def native(cmd, **kwargs):
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(options))
        source = Path(cmd[cmd.index("--request") + 1])
        destination = Path(cmd[cmd.index("--outfile") + 1])
        payload = json.loads(source.read_text())
        prepared_talents.append(
            payload["raid"]["parties"][0]["players"][0]["talentsString"]
        )
        destination.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": 20},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    result = produce_frontier(
        _request(budget=3), binary=binary, seed_source=seed,
        out=tmp_path / "native", runner=native,
    )
    assert len(result["entries"]) == 3
    assert result["refusals"] == []
    assert prepared_talents == ["11-0-0", "00-2-0", "00-0-2"]
    # The source is authoritative even though Forever constructed trial
    # variants: no candidate is measured unless Rust actually prepares it.
    assert all(Path(entry["prepared"]).is_file() for entry in result["entries"])


def test_small_budget_proposes_materially_different_full_tree_families(tmp_path):
    """Rust, not Forever, decides if multi-rank family reallocations are valid."""
    seed, binary = _root_source(tmp_path)
    source = json.loads(seed.read_text())
    source["raid"]["parties"][0]["players"][0]["talentsString"] = "551-0-0"
    seed.write_text(json.dumps(source))
    options = {"level": 20, "talents": {"status": "ok", "trees": [
        {"talents": [{"index": i, "max_rank": 5} for i in range(3)]}
        for _ in range(3)
    ]}}
    proposals = []

    def native(cmd, **kwargs):
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(options))
        source_path = Path(cmd[cmd.index("--request") + 1])
        prepared_path = Path(cmd[cmd.index("--outfile") + 1])
        talents = json.loads(source_path.read_text())["raid"]["parties"][0]["players"][0]["talentsString"]
        proposals.append(talents)
        if talents == "000-551-0":
            return subprocess.CompletedProcess(
                cmd, 2, stderr="native rejected alternate tree")
        prepared_path.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": 20},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    result = produce_frontier(
        _request(budget=3), binary=binary, seed_source=seed,
        out=tmp_path / "native", runner=native,
    )
    # All 11 talent points move across trees: one-rank tweaks cannot yield
    # either distinct family. Rejected native prepares still cost one attempt.
    assert proposals == ["551-0-0", "000-551-0", "000-0-551"]
    assert [sum(int(rank) for part in proposal.split("-") for rank in part)
            for proposal in proposals] == [11, 11, 11]
    assert len(result["entries"]) == 2
    assert len(result["refusals"]) == 1
    assert result["refusals"][0]["status"] == "NATIVE_PREPARE_REFUSED"
    assert "native rejected alternate tree" in result["refusals"][0]["native_refusal"]


def test_cross_tree_native_refusal_is_not_replaced_by_unpaid_candidate(tmp_path):
    seed, binary = _root_source(tmp_path)
    prepared_talents = []

    def native(cmd, **kwargs):
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
                "level": 20, "talents": {"status": "ok", "trees": [
                    {"talents": [{"index": 0, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                ]},
            }))
        source = Path(cmd[cmd.index("--request") + 1])
        destination = Path(cmd[cmd.index("--outfile") + 1])
        talents = json.loads(source.read_text())["raid"]["parties"][0]["players"][0]["talentsString"]
        prepared_talents.append(talents)
        if talents == "00-2-0":
            return subprocess.CompletedProcess(cmd, 2, stderr="native source refusal")
        destination.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": 20},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    result = produce_frontier(
        _request(budget=3), binary=binary, seed_source=seed,
        out=tmp_path / "native", runner=native,
    )
    assert prepared_talents == ["11-0-0", "00-2-0", "00-0-2"]
    assert len(result["entries"]) == 2
    assert len(result["refusals"]) == 1
    assert result["refusals"][0]["status"] == "NATIVE_PREPARE_REFUSED"
    assert "native source refusal" in result["refusals"][0]["native_refusal"]


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
        "--mode", "continuing",
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


def test_native_prepared_apl_fallbacks_compete_after_tree_families(tmp_path):
    """A bounded live request reaches Rust-registered APLs, not options guesses."""
    seed, binary = _root_source(tmp_path)
    source = json.loads(seed.read_text())
    source["raid"]["parties"][0]["players"][0]["rotation"] = {
        "priorityList": [{"action": {"castSpell": {"spellId": {"spellId": 101}}}}]
    }
    seed.write_text(json.dumps(source))
    attempts = []

    def native(cmd, **kwargs):
        if cmd[1] == "options":
            # Family alternatives are source-defined; the generic spell-family
            # list is deliberately NOT used as a learned/executable APL list.
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
                "level": 20, "spells": [{"spell_id": 999}],
                "talents": {"status": "ok", "trees": [
                    {"talents": [{"index": 0, "max_rank": 5},
                                 {"index": 1, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                ]},
            }))
        source_path = Path(cmd[cmd.index("--request") + 1])
        prepared_path = Path(cmd[cmd.index("--outfile") + 1])
        player = json.loads(source_path.read_text())["raid"]["parties"][0]["players"][0]
        fallback_id = player["rotation"]["priorityList"][-1]["action"]["castSpell"]["spellId"]["spellId"]
        attempts.append((player["talentsString"], fallback_id))
        if fallback_id == 102:
            return subprocess.CompletedProcess(cmd, 2, stderr="native APL refused")
        prepared_path.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": 20, "spells": [
                {"action_id": {"spell_id": 101}, "flags": ["SpellFlagAPL"]},
                {"action_id": {"spell_id": 102}, "flags": ["SpellFlagAPL"]},
                {"action_id": {"spell_id": 103}, "flags": ["SpellFlagAPL"]},
                {"action_id": {"spell_id": 104}, "flags": []},
            ]},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    result = produce_frontier(
        _request(budget=5), binary=binary, seed_source=seed,
        out=tmp_path / "native", runner=native,
    )
    assert attempts == [
        ("11-0-0", 101), ("00-2-0", 101), ("00-0-2", 101),
        ("11-0-0", 102), ("11-0-0", 103),
    ]
    assert len(result["entries"]) == 4
    assert len(result["refusals"]) == 1
    assert result["refusals"][0]["candidate_id"] == "source_003"
    assert "native APL refused" in result["refusals"][0]["native_refusal"]
    assert all(action != 999 and action != 104 for _, action in attempts)
    assert Path(result["entries"][-1]["source_request"]).is_file()


def test_prepared_frontier_cannot_hide_overspent_native_attempts(tmp_path):
    """Already-prepared attempts and native refusals both consume the budget."""
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request

    manifest = tmp_path / "manifest.json"
    for prepared_count, refused_count in ((3, 0), (2, 1)):
        manifest.write_text(json.dumps({
            "entries": [
                {"id": f"candidate_{index}", "level": 20,
                 "parent_source_sha256": None}
                for index in range(prepared_count)
            ],
            "refusals": [
                {"status": "NATIVE_PREPARE_REFUSED", "candidate_id": "rejected"}
                for _ in range(refused_count)
            ],
        }))
        with pytest.raises(ValueError, match="NATIVE_FRONTIER_EXCEEDS_CANDIDATE_BUDGET"):
            evaluate_request(
                _request(budget=2), manifest=manifest,
                binary=tmp_path / "unneeded-native", target_hp=400,
                scorer_command=["work1-scorer"], artifact_dir=tmp_path / "receipts",
            )


def test_reusable_manifest_budget_counts_only_matching_level_and_parent(tmp_path):
    """An unrelated already-prepared level is not a paid attempt in this call."""
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "entries": [
            {"id": "future", "level": 30, "parent_source_sha256": None},
            {"id": "root_a", "level": 20, "parent_source_sha256": None},
            {"id": "root_b", "level": 20, "parent_source_sha256": None},
        ],
        "refusals": [],
    }))
    # Both requested entries lack native source files; preserve their
    # refusals without paying or rejecting the valid per-request budget.
    rows = evaluate_request(
        _request(budget=2), manifest=manifest,
        binary=tmp_path / "unneeded-native", target_hp=400,
        scorer_command=["work1-scorer"], artifact_dir=tmp_path / "receipts",
    )
    assert len(rows) == 2
    assert {row["candidate_id"] for row in rows} == {"root_a", "root_b"}
    assert all(row["status"].startswith("NATIVE_PREPARED_OR_CONTINUITY_REFUSAL")
               for row in rows)


def _scored_parent(tmp_path: Path):
    """Exact paid-source evidence supplied to Work2, not Warcraft gameplay."""
    seed, binary = _root_source(tmp_path)
    sha = hashlib.sha256(seed.read_bytes()).hexdigest()
    prepared = tmp_path / "L20.prepared.json"
    prepared.write_text(json.dumps({
        "request_sha256": sha,
        "player": {"class": "ClassWarlock", "level": 20},
    }))
    raw = tmp_path / "L20.native.json"
    raw.write_text(json.dumps({
        "source_sha256": sha, "actual_2d_ack": True,
        "world_targets_killed": 3,
        "native_terminal_recovery": {
            "paid": True, "native_clock_accounted": True,
            "max_health": 100, "max_mana": 200,
            "health_after": 100, "mana_after": 200,
        },
    }))
    return seed, binary, {
        "level": 20, "mob_count": 3, "source_request_sha256": sha,
        "engine_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "source_request_file": str(seed),
        "prepared_file": str(prepared),
        "native_raw_receipt_file": str(raw),
    }


def test_paid_parent_advances_through_every_native_prepared_sparse_level(tmp_path):
    seed, binary, parent = _scored_parent(tmp_path)
    prepared_levels = []
    proposed_talents = []

    def native(cmd, **kwargs):
        if cmd[1] == "options":
            assert cmd[-1] == "30"
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
                "level": 30, "talents": {"status": "ok", "trees": [
                    {"talents": [{"index": 0, "max_rank": 5},
                                 {"index": 1, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                ]},
            }))
        source = Path(cmd[cmd.index("--request") + 1])
        prepared = Path(cmd[cmd.index("--outfile") + 1])
        request = json.loads(source.read_text())
        actor = request["raid"]["parties"][0]["players"][0]
        level = actor["level"]
        assert request["encounter"]["targets"][0]["level"] == level
        prepared_levels.append(level)
        if level == 30:
            proposed_talents.append(actor["talentsString"])
            if actor["talentsString"] == "21-0-0":
                return subprocess.CompletedProcess(
                    cmd, 2, stderr="source native refused new rank")
        else:
            assert actor["talentsString"] == "11-0-0"  # No skipped-level respec
        prepared.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": level},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    result = produce_frontier(
        _request(level=30, parent=parent, budget=3), binary=binary,
        seed_source=seed, out=tmp_path / "native", runner=native)
    assert prepared_levels[:9] == list(range(21, 30))
    assert prepared_levels[9:] == [30, 30, 30]
    assert proposed_talents == ["11-0-0", "21-0-0", "12-0-0"]
    assert result["native_intermediate_prepares"] == 9
    assert len(result["entries"]) == 2
    assert len(result["refusals"]) == 1
    assert "source native refused new rank" in result["refusals"][0]["native_refusal"]
    for entry in result["entries"]:
        assert entry["parent_source_sha256"] == parent["source_request_sha256"]
        lineage = json.loads(Path(entry["native_continuity_receipt"]).read_text())
        assert lineage["native_continuity_from_level"] == 20
        assert lineage["native_intermediate_levels_verified"] is True
        assert lineage["native_parent_raw_receipt_sha256"] == hashlib.sha256(
            Path(parent["native_raw_receipt_file"]).read_bytes()).hexdigest()
        assert [step["level"] for step in lineage["infill"]] == list(range(21, 30))
        assert all(Path(step["prepared"]).exists() for step in lineage["infill"])


def test_sparse_native_prepare_refusal_stops_at_actual_failed_level(tmp_path):
    seed, binary, parent = _scored_parent(tmp_path)
    visited = []

    def native(cmd, **kwargs):
        assert cmd[1] == "prepare"  # Never ask for target options after broken infill
        source = Path(cmd[cmd.index("--request") + 1])
        level = json.loads(source.read_text())["raid"]["parties"][0]["players"][0]["level"]
        visited.append(level)
        if level == 23:
            return subprocess.CompletedProcess(cmd, 2, stderr="Rust refused L23 actor")
        prepared = Path(cmd[cmd.index("--outfile") + 1])
        prepared.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": level},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    result = produce_frontier(
        _request(level=30, parent=parent), binary=binary,
        seed_source=seed, out=tmp_path / "native", runner=native)
    assert visited == [21, 22, 23]
    assert result["entries"] == []
    assert result["refusals"][0]["status"] == "NATIVE_CONTINUITY_NOT_ATTESTED"
    assert "Rust refused L23 actor" in result["refusals"][0]["native_refusal"]


def test_source_parent_mismatch_never_asks_native_for_an_edge(tmp_path):
    seed, binary, parent = _scored_parent(tmp_path)
    parent["engine_binary_sha256"] = "f" * 64
    result = produce_frontier(
        _request(level=30, parent=parent), binary=binary,
        seed_source=seed, out=tmp_path / "native",
        runner=lambda *args, **kwargs: 1 / 0)
    assert result["entries"] == []
    assert "engine" in result["refusals"][0]["native_refusal"]
    assert result["refusals"][0]["native_prepared"] is False


def test_scored_child_rechecks_rust_infill_before_any_native_payment(tmp_path):
    from tools.wf_warlock_native_range_scored_adapter import evaluate_request

    seed, binary, parent = _scored_parent(tmp_path)

    def prepare_native(cmd, **kwargs):
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
                "level": 30, "talents": {"status": "ok", "trees": [
                    {"talents": [{"index": 0, "max_rank": 5}]},
                    {"talents": []}, {"talents": []},
                ]},
            }))
        source = Path(cmd[cmd.index("--request") + 1])
        payload = json.loads(source.read_text())
        level = payload["raid"]["parties"][0]["players"][0]["level"]
        prepared = Path(cmd[cmd.index("--outfile") + 1])
        prepared.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": level},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    found = produce_frontier(
        _request(level=30, parent=parent, budget=2),
        binary=binary, seed_source=seed, out=tmp_path / "native",
        runner=prepare_native)
    assert len(found["entries"]) == 2
    manifest = tmp_path / "native-manifest.json"
    manifest.write_text(json.dumps(found))
    score_calls = []

    def scorer(cmd, **kwargs):
        score_calls.append(cmd)
        output = Path(cmd[cmd.index("--out") + 1])
        rows = []
        for arg in [cmd[index + 1] for index, name in enumerate(cmd[:-1])
                    if name == "--prepared"]:
            cid, prepared_file = arg.split("=", 1)
            prepared_path = Path(prepared_file)
            prepared = json.loads(prepared_path.read_text())
            src = prepared["request_sha256"]
            rows.append({
                "candidate_id": cid, "prepared_sha256": hashlib.sha256(
                    prepared_path.read_bytes()).hexdigest(),
                "source_sha256": src, "mob_count": 3,
                "rng_mode": "balanced", "iterations": 1,
                "status": "MEASURED_NATIVE_FULLY_RECOVERED",
                "elapsed_seconds": 10.0,
            })
            (output / f"{cid}.native.json").write_text(json.dumps({
                "source_sha256": src, "actual_2d_ack": True,
                "world_targets_killed": 3,
                "native_terminal_recovery": {
                    "paid": True, "native_clock_accounted": True,
                    "start_clock_ns": 8_000_000_000,
                    "end_clock_ns": 10_000_000_000,
                    "max_health": 100, "max_mana": 200,
                    "health_after": 100, "mana_after": 200,
                },
            }))
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
            "candidates": rows,
        }))

    request = _request(level=30, parent=parent, budget=2)
    rows = evaluate_request(
        request, manifest=manifest, binary=binary, target_hp=400,
        scorer_command=["work1-native-scorer"],
        artifact_dir=tmp_path / "paid", run_command=scorer)
    assert len(score_calls) == 1
    assert len(rows) == 2
    assert all(row["native_continuity_ack"] is True
               and row["native_intermediate_levels_verified"] is True
               and row["terminal_recovery_seconds"] == 2.0 for row in rows)

    lineage = json.loads(Path(found["entries"][0]["native_continuity_receipt"]).read_text())
    prepared_infill = Path(lineage["infill"][3]["prepared"])
    prepared_infill.write_text(prepared_infill.read_text() + "tampered")
    score_calls.clear()
    rejected = evaluate_request(
        request, manifest=manifest, binary=binary, target_hp=400,
        scorer_command=["work1-native-scorer"],
        artifact_dir=tmp_path / "unpaid", run_command=scorer)
    assert score_calls == []
    assert len(rejected) == 2
    assert all("NATIVE_SOURCE_CHAIN_FILE_IDENTITY_MISMATCH" in row["status"]
               for row in rejected)


def test_independent_l30_uses_native_level_points_and_preserves_scaled_apl_root(tmp_path):
    """L20 seed points must not cap independently sampled higher-level builds.

    This checks native request forwarding/proposal diversity, not talent legality:
    every proposed full-budget build is judged again by Rust prepare.
    """
    seed, binary = _root_source(tmp_path)
    seed_payload = json.loads(seed.read_text())
    seed_payload["raid"]["parties"][0]["players"][0]["rotation"] = {
        "priorityList": [{"action": {"castSpell": {"spellId": {"spellId": 101}}}}]
    }
    seed.write_text(json.dumps(seed_payload))
    proposed = []
    options = {"level": 30, "talents": {
        "status": "ok", "points_available": 21,
        "trees": [{"talents": [{"index": i, "max_rank": 5}
                               for i in range(5)]} for _ in range(3)],
    }}

    def native(cmd, **kwargs):
        if cmd[1] == "options":
            assert cmd[-1] == "30"
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(options))
        source_path = Path(cmd[cmd.index("--request") + 1])
        prepared_path = Path(cmd[cmd.index("--outfile") + 1])
        player = json.loads(source_path.read_text())["raid"]["parties"][0]["players"][0]
        assert player["level"] == 30
        spell = player["rotation"]["priorityList"][-1]["action"]["castSpell"]["spellId"]["spellId"]
        proposed.append((player["talentsString"], spell))
        prepared_path.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": 30, "spells": [
                {"action_id": {"spell_id": n}, "flags": ["SpellFlagAPL"]}
                for n in (101, 102, 103)
            ]},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    result = produce_frontier(
        {**_request(level=30, budget=7), "search_mode": "independent"},
        binary=binary, seed_source=seed, out=tmp_path / "native", runner=native,
    )
    assert len(result["entries"]) == 7
    assert result["refusals"] == []
    assert proposed == [
        ("55551-0-0", 101),
        ("00-55551-0", 101),
        ("00-0-55551", 101),
        ("55551-0-0", 102),
        ("55551-0-0", 103),
        ("45551-1-0", 101),
        ("45551-0-1", 101),
    ]
    # Both the first three families and later native-sourced rank transfers
    # must spend the L30 option budget; only Rust prepare judges legality.
    assert all(sum(int(c) for tree in talents.split("-") for c in tree) == 21
               for talents, _ in proposed)
    assert all(entry["parent_source_sha256"] is None for entry in result["entries"])


def test_unscaled_seed_is_preserved_when_native_points_not_advertised(tmp_path):
    """Missing source options cannot be replaced with an inferred level formula."""
    seed, binary = _root_source(tmp_path)
    proposed = []

    def native(cmd, **kwargs):
        if cmd[1] == "options":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
                "level": 30, "talents": {"status": "ok", "trees": [
                    {"talents": [{"index": 0, "max_rank": 5},
                                 {"index": 1, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                    {"talents": [{"index": 0, "max_rank": 5}]},
                ]},
            }))
        source = Path(cmd[cmd.index("--request") + 1])
        player = json.loads(source.read_text())["raid"]["parties"][0]["players"][0]
        proposed.append(player["talentsString"])
        prepared = Path(cmd[cmd.index("--outfile") + 1])
        prepared.write_text(json.dumps({
            "request_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "player": {"class": "ClassWarlock", "level": 30},
        }))
        return subprocess.CompletedProcess(cmd, 0)

    result = produce_frontier(
        {**_request(level=30, budget=3), "search_mode": "independent"},
        binary=binary, seed_source=seed, out=tmp_path / "native", runner=native,
    )
    assert len(result["entries"]) == 3
    assert proposed == ["11-0-0", "00-2-0", "00-0-2"]
