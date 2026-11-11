"""Changed-code regressions for Work2's persistent native API transport.

Fake Rust responses cover Forever forwarding only; they are NOT paid native
M0.4 results. Native world mechanics and original ACKs are owned by Rust.
"""
import hashlib
import json
from pathlib import Path

import pytest

from src.v2.native_range_optimizer import optimize
from tools import wf_warlock_native_persistent_optimizer as api


class FakeProcess:
    pass


class FakeSession:
    instances = []

    def __init__(self, binary):
        self.process = FakeProcess()
        self.calls = []
        self.closed = False
        self.__class__.instances.append(self)

    def request(self, payload):
        self.calls.append(payload)
        if payload["op"] == "options":
            level = payload["level"]
            return {
                "level": level,
                "talents": {
                    "status": "ok", "points_available": level - 9,
                    "trees": [{"talents": [
                        {"index": n, "max_rank": 5} for n in range(15)
                    ]} for _ in range(3)],
                },
            }
        assert payload["op"] == "prepare"
        source = payload["request"]
        level = payload["actor_level"]
        assert source["raid"]["parties"][0]["players"][0]["level"] == level
        assert source["encounter"]["targets"][0]["level"] == level
        native_digest = hashlib.sha256(
            json.dumps(source, sort_keys=True).encode()).hexdigest()
        return {
            "request_sha256": native_digest,
            "player": {"level": level, "class": "ClassWarlock",
                       "stats": {"Health": 100, "Mana": 100}},
        }

    def close(self):
        self.closed = True


def paid_world(binary, prepared_path, **kwargs):
    assert prepared_path is None
    assert kwargs["api_process"] is FakeSession.instances[-1].process
    assert kwargs["recovery_policy"] == "decisions"
    assert kwargs["health_threshold"] == kwargs["mana_threshold"] == 1.0
    assert kwargs["rng_mode"] == "balanced"
    prepared = kwargs["prepared_payload"]
    mobs = kwargs["target_count"]
    kills = [{"index": n, "native_kill_ns": (n + 1) * 10**9,
              "actor_health": 80.0} for n in range(mobs)]
    last = mobs * 10**9
    return {
        "source_sha256": prepared["request_sha256"],
        "world_target_hp": kwargs["mob_health"],
        "world_targets_killed": mobs, "continuous_native_actor": True,
        "actual_2d_ack": True,
        "native_recovery_clock_accounted": True,
        "native_recovery_mode": "decisions_food_water",
        "paid_recovery": True, "native_windows": kills,
        "native_actor_mana_after_world_kills": [30.0] * mobs,
        "native_health_damage": {"observed": True, "damage_taken": 0.0,
                                 "damage_events": 0},
        "world_elapsed_seconds": float(mobs),
        "native_terminal_recovery": {
            "paid": True, "native_clock_accounted": True,
            "start_clock_ns": last, "end_clock_ns": last + 2 * 10**9,
            "health_before": 80.0, "mana_before": 30.0,
            "health_after": 100.0, "mana_after": 100.0,
            "max_health": 100.0, "max_mana": 100.0,
        },
    }


def make_evaluator(tmp_path, monkeypatch, world=paid_world):
    FakeSession.instances.clear()
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"exact pinned native test binary")
    fixture = Path("fixtures/warlock-l20-native-paid-30s.request.json")
    monkeypatch.setattr(api, "_exact_paid_cache_identity", lambda *a, **k: None)
    return api.PersistentNativeEvaluator(
        binary, fixture, tmp_path / "paid", session_factory=FakeSession,
        run_world=world)


def test_one_session_scores_all_three_samples_with_actual_paid_clock_contract(
        tmp_path, monkeypatch):
    native = make_evaluator(tmp_path, monkeypatch)
    try:
        result = optimize(20, 60, 20, 2, 60, evaluate=native,
                          beam_width=3, mode="compatible")
    finally:
        native.close()
    assert result["sampled_levels_requested"] == [20, 40, 60]
    assert result["sampled_levels_compatible"] == [20, 40, 60]
    assert result["ranked_alternatives"]
    assert result["ranked_alternatives"][0]["sampled_cumulative_seconds"] == 12
    calls = FakeSession.instances[0].calls
    assert [row["level"] for row in calls if row["op"] == "options"] == [20, 40, 60]
    assert any(row["actor_level"] == 40 for row in calls if row["op"] == "prepare")
    l40_paid_talents = {row["talents"] for row in
                        result["independent_level_rankings"]["40"]}
    l60_proposals = [row["request"]["raid"]["parties"][0]["players"][0]["talentsString"]
                     for row in calls if row["op"] == "prepare"
                     and row["actor_level"] == 60]
    assert l60_proposals and l60_proposals[0] in l40_paid_talents
    assert all(row["receipt"]["native_raw_receipt_sha256"]
               for row in result["independent_level_rankings"]["20"])
    assert native.session.closed


def test_unpaid_terminal_resources_refused_and_never_ranked(tmp_path, monkeypatch):
    def unpaid(*args, **kwargs):
        receipt = paid_world(*args, **kwargs)
        receipt["native_terminal_recovery"]["mana_after"] = 99.0
        return receipt

    native = make_evaluator(tmp_path, monkeypatch, unpaid)
    try:
        rows = native(level=20, parent=None, mob_count=2, budget=3,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert rows and all(row["status"] == "NATIVE_API_CANDIDATE_REFUSED"
                        for row in rows)
    assert all("NATIVE_TERMINAL_BOTH_RESOURCES_NOT_FULL" in row["native_refusal"]
               for row in rows)
    assert not list((tmp_path / "paid").glob("*.native.json"))


def test_native_prepare_refusal_remains_a_candidate_attempt(tmp_path, monkeypatch):
    class RefusingSession(FakeSession):
        def request(self, payload):
            if payload["op"] == "prepare":
                raise ValueError("native talent prerequisites refused")
            return super().request(payload)

    native = make_evaluator(tmp_path, monkeypatch)
    native.close()
    native = api.PersistentNativeEvaluator(
        native.binary, Path("fixtures/warlock-l20-native-paid-30s.request.json"),
        tmp_path / "other", session_factory=RefusingSession,
        run_world=lambda *a, **k: pytest.fail("paid world must not execute"))
    try:
        rows = native(level=20, parent=None, mob_count=2, budget=2,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert len(rows) == 2
    assert all(row["status"] == "NATIVE_API_CANDIDATE_REFUSED" for row in rows)
    assert all("native talent prerequisites refused" in row["native_refusal"]
               for row in rows)

def test_paid_candidates_receive_level_scaled_lethal_timeout_and_native_gear_option(
        tmp_path, monkeypatch):
    native = make_evaluator(tmp_path, monkeypatch)
    try:
        rows = native(level=40, parent=None, mob_count=2, budget=2,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert len(rows) == 2
    requests = [request for request in FakeSession.instances[0].calls
                if request["op"] == "prepare"]
    assert len(requests) == 2
    assert all(request["request"]["encounter"]["duration"] >= 180
               for request in requests)
    first = requests[0]["request"]["raid"]["parties"][0]["players"][0]
    second = requests[1]["request"]["raid"]["parties"][0]["players"][0]
    assert first["talentsString"] == second["talentsString"]
    assert any(item.get("id", 0) != 0 for item in first["equipment"]["items"])
    assert all(item.get("id", 0) == 0 for item in second["equipment"]["items"])
    assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
               for row in rows)

def test_forward_talent_proposals_preserve_earlier_paid_ancestry_without_respec():
    from tools.wf_warlock_native_persistent_optimizer import _forward_native_talent_hints
    trees = [{"talents": [{"index": idx, "max_rank": 5}
                           for idx in range(15)]} for _ in range(3)]
    earlier = "25522323133-0000-00"
    variants = list(_forward_native_talent_hints([
        {"talents": earlier, "from_level": 40},
    ], level=60, points_available=51, trees=trees))
    assert variants and variants[0] == earlier
    assert len(variants) > 1
    for later in variants[1:]:
        old = [[int(char) for char in piece] for piece in earlier.split("-")]
        new = [[int(char) for char in piece] for piece in later.split("-")]
        assert all(all(a <= b for a, b in zip(
            left + [0] * (len(right) - len(left)), right))
            for left, right in zip(old, new))
        assert sum(sum(p) for p in new) == 51
