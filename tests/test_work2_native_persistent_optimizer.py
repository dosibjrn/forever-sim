"""Changed-code regressions for Work2's persistent native API transport.

Fake Rust responses cover Forever forwarding only; they are NOT paid native
M0.4 results. Native world mechanics and original ACKs are owned by Rust.
"""
import copy
import hashlib
import io
import json
from pathlib import Path

import pytest

from src.v2.native_range_optimizer import optimize
from tools import wf_warlock_native_persistent_optimizer as api


def rust_wire_request(frame, payload):
    """Drive the actual NativeApiSession.request parser with one Rust NDJSON frame."""
    class WireProcess:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(json.dumps(frame) + "\n")

        def poll(self):
            return None

    session = api.NativeApiSession.__new__(api.NativeApiSession)
    session.process = WireProcess()
    try:
        return session.request(payload)
    finally:
        assert json.loads(session.process.stdin.getvalue()) == payload


def test_native_api_session_preserves_rust_wire_refusal_and_legacy_fallback():
    request = {"op": "advance", "from_level": 20, "to_level": 21}
    frame = {
        "ok": False,
        "error": "native level transition unavailable",
        "refusal": {
            "code": "native_level_transition_unsupported",
            "reason": "post-combat actor and XP are not retained",
        },
    }
    with pytest.raises(api.NativeApiRefusal) as failure:
        rust_wire_request(frame, request)
    assert failure.value.code == "native_level_transition_unsupported"
    assert failure.value.reason == "post-combat actor and XP are not retained"

    # The previously pinned engine only provided an error string.
    with pytest.raises(api.NativeApiRefusal) as legacy:
        rust_wire_request({"ok": False, "error": "old engine refusal"}, request)
    assert legacy.value.code is None
    assert legacy.value.reason == "old engine refusal"


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



def test_same_session_identical_paid_world_reused_without_git_identity(
        tmp_path, monkeypatch):
    """Unverifiable cross-run cache never justifies repeating this session's ACK."""
    paid_calls = []

    def counted_world(binary, prepared_path, **kwargs):
        paid_calls.append(kwargs["mob_health"])
        return paid_world(binary, prepared_path, **kwargs)

    # This fixture explicitly disables the Git-backed reusable disk identity.
    native = make_evaluator(tmp_path, monkeypatch, world=counted_world)

    def sample():
        return native(level=20, parent=None, mob_count=2, budget=2,
                      rng_mode="balanced", iterations=1, recover_to_full=True)

    try:
        first = sample()
        assert len(first) == 2
        assert len(paid_calls) == 2
        assert all(not row["reused_exact_native_paid_receipt"] for row in first)
        again = sample()
        assert len(paid_calls) == 2
        assert all(row["reused_exact_native_paid_receipt"] for row in again)
        assert [row["native_raw_receipt_sha256"] for row in again] == [
            row["native_raw_receipt_sha256"] for row in first]
        # The same native actor against a different hostile HP is NOT a hit.
        native.target_hp = float(api.representative_hp(20)) + 1
        changed_world = sample()
        assert len(changed_world) == 2
        assert len(paid_calls) == 4
        assert all(not row["reused_exact_native_paid_receipt"]
                   for row in changed_world)
    finally:
        native.close()


def test_session_paid_memo_refuses_modified_raw_receipt(tmp_path, monkeypatch):
    paid_calls = []

    def counted_world(binary, prepared_path, **kwargs):
        paid_calls.append(True)
        return paid_world(binary, prepared_path, **kwargs)

    native = make_evaluator(tmp_path, monkeypatch, world=counted_world)
    try:
        request = dict(level=20, parent=None, mob_count=2, budget=1,
                       rng_mode="balanced", iterations=1,
                       recover_to_full=True)
        first = native(**request)
        assert len(paid_calls) == 1
        original = Path(first[0]["native_raw_receipt_file"])
        original.write_text("{}\\n")
        second = native(**request)
        assert len(paid_calls) == 2
        assert second[0]["reused_exact_native_paid_receipt"] is False
        assert Path(second[0]["native_raw_receipt_file"]) != original
        assert Path(second[0]["native_raw_receipt_file"]).is_file()
    finally:
        native.close()


def test_exact_paid_cache_identity_is_session_scoped_and_level_specific(
        tmp_path, monkeypatch):
    """One binary/Git identity read serves every paid candidate and level.

    Exact prepared source + scenario fields still have separate cache keys,
    and a second clean session can reuse those paid receipts without a new
    native world execution. No combat or source legality is mocked as PASS.
    """
    FakeSession.instances.clear()
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"exact pinned native test binary")
    fixture = Path("fixtures/warlock-l20-native-paid-30s.request.json")
    paid_dir = tmp_path / "paid"
    calls = []

    def identity(path, *, actor_level, mob_count, target_hp):
        calls.append((actor_level, mob_count, target_hp))
        return {
            "cache_schema": 1, "forever_commit": "f" * 40,
            "native_binary_sha256": api._file_digest(path),
            "actor_level": actor_level, "mob_count": mob_count,
            "target_hp": target_hp, "rng_mode": "balanced",
            "iterations": 1, "recovery_policy": "decisions",
        }

    monkeypatch.setattr(api, "_exact_paid_cache_identity", identity)

    def sampled(native, level):
        return native(level=level, parent=None, mob_count=2, budget=2,
                      rng_mode="balanced", iterations=1, recover_to_full=True)

    first = api.PersistentNativeEvaluator(
        binary, fixture, paid_dir, session_factory=FakeSession,
        run_world=paid_world)
    try:
        paid20 = sampled(first, 20)
        paid40 = sampled(first, 40)
    finally:
        first.close()
    assert len(calls) == 1
    assert calls[0] == (20, 2, float(api.representative_hp(20)))
    assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
               and row["reused_exact_native_paid_receipt"] is False
               for row in paid20 + paid40)
    stored = [json.loads(path.read_text())
              for path in paid_dir.glob("*.native.cache.json")]
    assert len(stored) == len(paid20) + len(paid40)
    assert {meta["actor_level"] for meta in stored} == {20, 40}
    assert {meta["target_hp"] for meta in stored} == {
        float(api.representative_hp(20)), float(api.representative_hp(40))}
    assert {meta["native_binary_sha256"] for meta in stored} == {
        api._file_digest(binary)}

    second = api.PersistentNativeEvaluator(
        binary, fixture, paid_dir, session_factory=FakeSession,
        run_world=lambda *a, **k: pytest.fail("matching paid cache must reuse original"))
    try:
        replay20 = sampled(second, 20)
        replay40 = sampled(second, 40)
    finally:
        second.close()
    assert len(calls) == 2  # one clean identity acquisition per session
    assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
               and row["reused_exact_native_paid_receipt"] is True
               for row in replay20 + replay40)


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
    original_paths = [Path(row["native_unverified_receipt_file"]) for row in rows]
    assert len(original_paths) == 3
    assert len(set(original_paths)) == 3
    for row, original in zip(rows, original_paths):
        assert original.is_file()
        assert hashlib.sha256(original.read_bytes()).hexdigest() == (
            row["native_unverified_receipt_sha256"])
        assert json.loads(original.read_text())["native_terminal_recovery"][
            "mana_after"] == 99.0
    assert not list((tmp_path / "paid").glob("*.native.json"))
    assert not list((tmp_path / "paid").glob("*.native.cache.json"))


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
    # No native item options were advertised by FakeSession: all legacy
    # equipment is stripped before the *first* native prepare, regardless
    # of the talent-family proposal. Rust remains responsible for legality.
    assert all(item.get("id", 0) == 0 for item in first["equipment"]["items"])
    assert all(item.get("id", 0) == 0 for item in second["equipment"]["items"])
    assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
               for row in rows)


def test_native_prepared_apl_proposals_are_scored_before_more_talent_families(
        tmp_path, monkeypatch):
    def prepared_actions(source, prepared):
        for action_id in (70001, 70002):
            proposal = copy.deepcopy(source)
            priorities = proposal["raid"]["parties"][0]["players"][0][
                "rotation"]["priorityList"]
            priorities[-1] = {"action": {"castSpell": {
                "spellId": {"spellId": action_id}}}}
            yield proposal

    monkeypatch.setattr(api, "_native_apl_variants", prepared_actions)
    native = make_evaluator(tmp_path, monkeypatch)
    try:
        rows = native(level=60, parent=None, mob_count=2, budget=3,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert len(rows) == 3
    requests = [call["request"] for call in FakeSession.instances[0].calls
                if call["op"] == "prepare"]
    assert len(requests) == 3
    def last_spell(request):
        player = request["raid"]["parties"][0]["players"][0]
        return player["rotation"]["priorityList"][-1][
            "action"]["castSpell"]["spellId"]["spellId"]
    assert [last_spell(request) for request in requests] == [
        1088, 70001, 70002]
    assert all(all(item.get("id", 0) == 0 for item in request[
        "raid"]["parties"][0]["players"][0]["equipment"]["items"])
               for request in requests)

def test_bounded_native_search_pays_alternative_talent_before_apl_burst(
        tmp_path, monkeypatch):
    """Gear/pet/rotation variation must not consume every small paid slot.

    Synthetic Rust options and receipts test candidate order only. Each
    alternative still goes through native prepare and actual-world execution.
    """
    def source_items(source, options):
        for item_id in (0, 8001, 8002):
            proposal = copy.deepcopy(source)
            proposal["raid"]["parties"][0]["players"][0][
                "equipment"]["items"][0] = {"id": item_id}
            yield proposal

    def source_pets(source, options):
        proposal = copy.deepcopy(source)
        proposal["raid"]["parties"][0]["players"][0].setdefault(
            "warlock", {}).setdefault("options", {}).setdefault(
            "classOptions", {})["summon"] = "Voidwalker"
        yield proposal

    def source_apls(source, prepared, options):
        for spell_id in (70001, 70002, 70003):
            proposal = copy.deepcopy(source)
            proposal["raid"]["parties"][0]["players"][0][
                "rotation"]["priorityList"][-1] = {
                    "action": {"castSpell": {"spellId": {"spellId": spell_id}}}}
            yield proposal

    monkeypatch.setattr(api, "_source_item_alternatives", source_items)
    monkeypatch.setattr(api, "_source_pet_alternatives", source_pets)
    monkeypatch.setattr(api, "_level_aware_apl_variants", source_apls)
    native = make_evaluator(tmp_path, monkeypatch)
    try:
        rows = native(level=20, parent=None, mob_count=2, budget=4,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert [row["proposal_axis"] for row in rows] == [
        "talent", "gear", "pet", "talent"]
    assert len({row["talents"] for row in rows}) >= 2
    assert all(row["native_full_recovery_paid"] for row in rows)


def test_generic_native_search_pays_rest_and_refuses_unverified_rolling(
        tmp_path, monkeypatch):
    """Ordinary scored search explores policies, never scores fake overlap.

    The synthetic world deliberately has no native rolling target-ID/ACK
    evidence. Such a proposal must be retained as a refusal, not a winner.
    """
    called = []

    def world(binary, prepared_path, **kwargs):
        called.append((kwargs["health_threshold"],
                       kwargs["mana_threshold"], kwargs.get("world_apl")))
        # The transport stub is source-independent; allow the changed
        # threshold through to the evaluator but keep its full-paid receipt.
        sanitized = dict(kwargs, health_threshold=1.0, mana_threshold=1.0)
        return paid_world(binary, prepared_path, **sanitized)

    native = make_evaluator(tmp_path, monkeypatch, world=world)
    native.explore_world_policies = True
    try:
        rows = native(level=20, parent=None, mob_count=2, budget=5,
                      rng_mode="balanced", iterations=1,
                      recover_to_full=True)
    finally:
        native.close()

    rest = [r for r in rows if r["proposal_axis"] == "world_rest_30pct"]
    rolling = [r for r in rows if r["proposal_axis"] == "world_rolling_50pct"]
    assert len(rest) == len(rolling) == 1
    assert rest[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert rest[0]["native_full_recovery_paid"] is True
    assert rest[0]["native_world_policy"]["rest_when_health_below"] == 0.3
    assert rolling[0]["status"] == "NATIVE_API_CANDIDATE_REFUSED"
    assert "RUST_WORLD_NATIVE_ROLLING_APL_NOT_PROVEN" in rolling[0]["native_refusal"]
    # Refused native worlds retain exact prepared source and engine identity.
    assert rolling[0]["source_request_sha256"] == rest[0]["source_request_sha256"]
    assert rolling[0]["engine_binary_sha256"] == rest[0]["engine_binary_sha256"]
    assert rolling[0]["native_prepared"] is True
    assert Path(rolling[0]["native_unverified_receipt_file"]).is_file()
    assert any(h == m == 0.3 and apl is None for h, m, apl in called)
    assert any(apl is not None for _, _, apl in called)


def test_single_adaptive_slot_pays_new_rolling_policy_before_rest(
        tmp_path, monkeypatch):
    """The only remaining paid slot can reach source-ACKed two-live rolling.

    A synthetic serial-shaped native world cannot earn a rolling score:
    its rejected original receipt is preserved. The original serial result
    remains distinct and no extra attempt is spent on the 30% rest policy.
    """
    calls = []

    def world(binary, prepared_path, **kwargs):
        calls.append(kwargs.get("world_apl"))
        return paid_world(binary, prepared_path, **kwargs)

    native = make_evaluator(tmp_path, monkeypatch, world=world)
    native.explore_world_policies = True
    request = dict(level=20, parent=None, mob_count=2, rng_mode="balanced",
                   iterations=1, recover_to_full=True)
    try:
        baseline = native(**request, budget=1)
        assert len(baseline) == 1
        assert baseline[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
        excluded = {
            (baseline[0]["source_request_sha256"],
             json.dumps(baseline[0]["native_world_policy"], sort_keys=True))
        }
        revisit = native(
            **request, budget=1, excluded_paid_source_policies=excluded)
    finally:
        native.close()

    assert len(revisit) == 1
    assert revisit[0]["proposal_axis"] == "world_rolling_50pct"
    assert revisit[0]["source_request_sha256"] == baseline[0]["source_request_sha256"]
    assert revisit[0]["status"] == "NATIVE_API_CANDIDATE_REFUSED"
    assert "RUST_WORLD_NATIVE_ROLLING_APL_NOT_PROVEN" in revisit[0]["native_refusal"]
    assert Path(revisit[0]["native_unverified_receipt_file"]).is_file()
    assert calls == [None, api.ROLLING_WORLD_APL_50]


def test_adaptive_revisit_pays_uncompared_native_rest_and_rolling_before_gear(
        tmp_path, monkeypatch):
    """An actual small range budget must reach unpaid policies on revisit.

    Fake Rust/2D transport proves scheduling and receipt refusal only, NOT
    real native rolling combat. First pass still reserves gear/pet/talent.
    """
    world_calls = []

    def items(source, options):
        for item_id in (0, 8001, 8002):
            candidate = copy.deepcopy(source)
            candidate["raid"]["parties"][0]["players"][0][
                "equipment"]["items"][0] = {"id": item_id}
            yield candidate

    def pets(source, options):
        candidate = copy.deepcopy(source)
        candidate["raid"]["parties"][0]["players"][0].setdefault(
            "warlock", {}).setdefault("options", {}).setdefault(
            "classOptions", {})["summon"] = "Voidwalker"
        yield candidate

    def world(binary, prepared_path, **kwargs):
        world_calls.append((kwargs["health_threshold"],
                            kwargs["mana_threshold"], kwargs.get("world_apl")))
        # Simulated ACK cannot certify native rolling overlap.
        return paid_world(binary, prepared_path, **dict(
            kwargs, health_threshold=1.0, mana_threshold=1.0))

    monkeypatch.setattr(api, "_source_item_alternatives", items)
    monkeypatch.setattr(api, "_source_pet_alternatives", pets)
    native = make_evaluator(tmp_path, monkeypatch, world=world)
    native.explore_world_policies = True
    request = dict(level=20, parent=None, mob_count=2, rng_mode="balanced",
                   iterations=1, recover_to_full=True)
    try:
        initial = native(**request, budget=4)
        assert [row["proposal_axis"] for row in initial] == [
            "talent", "gear", "pet", "talent"]
        excluded = {
            (row["source_request_sha256"],
             json.dumps(row["native_world_policy"], sort_keys=True))
            for row in initial
            if row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
        }
        follow_up = native(
            **request, budget=2, excluded_paid_source_policies=excluded)
    finally:
        native.close()

    assert [row["proposal_axis"] for row in follow_up] == [
        "world_rest_30pct", "world_rolling_50pct"]
    assert follow_up[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert follow_up[0]["native_world_policy"]["rest_when_health_below"] == 0.3
    assert follow_up[0]["source_request_sha256"] == initial[0]["source_request_sha256"]
    assert follow_up[1]["status"] == "NATIVE_API_CANDIDATE_REFUSED"
    assert "RUST_WORLD_NATIVE_ROLLING_APL_NOT_PROVEN" in follow_up[1]["native_refusal"]
    assert follow_up[1]["source_request_sha256"] == initial[0]["source_request_sha256"]
    assert follow_up[1]["engine_binary_sha256"] == initial[0]["engine_binary_sha256"]
    assert Path(follow_up[1]["native_unverified_receipt_file"]).is_file()
    assert len(world_calls) == 6  # No bootstrap replay on the adaptive pass
    assert world_calls[-2][:2] == (0.3, 0.3)
    assert world_calls[-1][2] is not None



def test_adaptive_policy_challenges_complete_measured_gear_survivor(
        tmp_path, monkeypatch):
    """Paid rest/pull proposals retain observed gear/APL, not the seed.

    Fake native and 2D responses check Forever scheduling only. The rolling
    response deliberately lacks overlap ACK and must remain refused.
    """
    def items(source, options):
        for item_id in (0, 8001, 8002):
            proposal = copy.deepcopy(source)
            proposal["raid"]["parties"][0]["players"][0][
                "equipment"]["items"][0] = {"id": item_id}
            yield proposal

    world_requests = []

    def world(binary, prepared_path, **kwargs):
        world_requests.append((
            kwargs["prepared_payload"]["request_sha256"],
            kwargs["health_threshold"], kwargs.get("world_apl")))
        return paid_world(binary, prepared_path, **dict(
            kwargs, health_threshold=1.0, mana_threshold=1.0))

    monkeypatch.setattr(api, "_source_item_alternatives", items)
    native = make_evaluator(tmp_path, monkeypatch, world=world)
    native.explore_world_policies = True
    request = dict(level=20, parent=None, mob_count=2,
                   rng_mode="balanced", iterations=1, recover_to_full=True)
    try:
        initial = native(**request, budget=2)
        assert [row["proposal_axis"] for row in initial] == ["talent", "gear"]
        assert [row["gear"]["items"][0]["id"] for row in initial] == [
            8001, 8002]
        assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
                   for row in initial)
        # Adaptive coordinator ranks native-paid results and sends the best
        # measured source identity first; an unmeasured hint is ignored.
        selected = initial[1]
        excluded = {
            (row["source_request_sha256"],
             json.dumps(row["native_world_policy"], sort_keys=True))
            for row in initial
        }
        follow_up = native(
            **request, budget=2, excluded_paid_source_policies=excluded,
            candidate_hints=[
                {"from_level": 20, "talents": selected["talents"],
                 "source_request_sha256": "f" * 64},
                {"from_level": 20, "talents": selected["talents"],
                 "source_request_sha256": selected["source_request_sha256"]},
            ])
    finally:
        native.close()

    assert [row["proposal_axis"] for row in follow_up] == [
        "world_rest_30pct", "world_rolling_50pct"]
    assert all(row["source_request_sha256"] == selected["source_request_sha256"]
               for row in follow_up)
    assert follow_up[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert follow_up[0]["gear"] == selected["gear"]
    assert follow_up[0]["pet"] == selected["pet"]
    assert follow_up[0]["apl"] == selected["apl"]
    assert follow_up[1]["status"] == "NATIVE_API_CANDIDATE_REFUSED"
    assert "RUST_WORLD_NATIVE_ROLLING_APL_NOT_PROVEN" in (
        follow_up[1]["native_refusal"])
    # Two original serial payments and exactly two *new* native policy
    # attempts on the selected measured full build; no replay of paid worlds.
    assert len(world_requests) == 4
    assert [row[0] for row in world_requests[-2:]] == [
        selected["source_request_sha256"]] * 2
    assert world_requests[-2][1:] == (0.3, None)
    assert world_requests[-1][2] is not None



def test_adaptive_policy_skips_exhausted_measured_survivor(
        tmp_path, monkeypatch):
    """A second paid build gets policies when the faster one's were tried.

    Synthetic native worlds test bounded scheduling, not game performance.
    A refused rolling ACK still consumes its original attempt identity.
    """
    def items(source, options):
        for item_id in (0, 8001, 8002):
            proposal = copy.deepcopy(source)
            proposal["raid"]["parties"][0]["players"][0][
                "equipment"]["items"][0] = {"id": item_id}
            yield proposal

    requests = []

    def world(binary, prepared_path, **kwargs):
        requests.append((kwargs["prepared_payload"]["request_sha256"],
                         kwargs["health_threshold"], kwargs.get("world_apl")))
        return paid_world(binary, prepared_path, **dict(
            kwargs, health_threshold=1.0, mana_threshold=1.0))

    monkeypatch.setattr(api, "_source_item_alternatives", items)
    native = make_evaluator(tmp_path, monkeypatch, world=world)
    native.explore_world_policies = True
    request = dict(level=20, parent=None, mob_count=2, rng_mode="balanced",
                   iterations=1, recover_to_full=True)

    def exclude(rows):
        return {(row["source_request_sha256"],
                 json.dumps(row["native_world_policy"], sort_keys=True))
                for row in rows}

    try:
        first = native(**request, budget=2)
        assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
                   for row in first)
        hints = [
            {"from_level": 20, "talents": row["talents"],
             "source_request_sha256": row["source_request_sha256"]}
            for row in first
        ]
        first_policy = native(
            **request, budget=2, candidate_hints=hints,
            excluded_paid_source_policies=exclude(first))
        assert all(row["source_request_sha256"]
                   == first[0]["source_request_sha256"]
                   for row in first_policy)
        second_policy = native(
            **request, budget=2, candidate_hints=hints,
            excluded_paid_source_policies=(
                exclude(first) | exclude(first_policy)))
    finally:
        native.close()

    assert [row["proposal_axis"] for row in second_policy] == [
        "world_rest_30pct", "world_rolling_50pct"]
    assert all(row["source_request_sha256"] == first[1]["source_request_sha256"]
               for row in second_policy)
    assert second_policy[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert second_policy[1]["status"] == "NATIVE_API_CANDIDATE_REFUSED"
    assert len(requests) == 6
    assert [row[0] for row in requests[-2:]] == [
        first[1]["source_request_sha256"]] * 2


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


def test_schema1_paid_cache_is_reused_only_after_verified_world_identity(
        tmp_path, monkeypatch):
    """Stride-10 receipts remain reusable by stride 5 without false re-payment.

    Python fake sessions test transport only, not authentic M0.5 paid evidence.
    The legacy migration must retain raw bytes and strictly re-score ACK/HP/mana.
    """
    import subprocess
    from tools import wf_warlock_native_candidate_scoring as scorer

    FakeSession.instances.clear()
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"unchanged pinned Rust engine")
    fixture = Path("fixtures/warlock-l20-native-paid-30s.request.json")
    target = float(api.representative_hp(20))
    base = {
        "native_binary_sha256": api._file_digest(binary),
        "actor_level": 20, "mob_count": 2, "target_hp": target,
        "rng_mode": "balanced", "iterations": 1,
        "recovery_policy": "decisions",
        "health_threshold": 1.0, "mana_threshold": 1.0,
        "require_native_health_damage": False,
    }
    old_identity = dict(base, cache_schema=1, forever_commit="a" * 40)
    current_identity = dict(
        base, cache_schema=2, forever_paid_runtime_sha256="b" * 64)
    monkeypatch.setattr(
        api, "_exact_paid_cache_identity", lambda *args, **kwargs: old_identity)
    old = api.PersistentNativeEvaluator(
        binary, fixture, tmp_path / "paid",
        session_factory=FakeSession, run_world=paid_world)
    try:
        initial = old(level=20, parent=None, mob_count=2, budget=1,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        old.close()
    assert len(initial) == 1
    assert initial[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert initial[0]["reused_exact_native_paid_receipt"] is False
    metadata_paths = list((tmp_path / "paid").glob("*.native.cache.json"))
    assert len(metadata_paths) == 1
    metadata_bytes = metadata_paths[0].read_bytes()

    # The original and current versions must agree on *actual world code*,
    # not the entire Git commit or the upgraded cache helper implementation.
    changed_world = [False]
    def git(argv, *, cwd, capture_output, text, check, timeout):
        assert argv[:2] == ["git", "rev-parse"]
        assert len(argv) == 2 + len(scorer._LEGACY_PAID_WORLD_PATHS)
        first = "c" if changed_world[0] and argv[2].startswith("HEAD:") else "d"
        return subprocess.CompletedProcess(
            argv, 0, "\n".join([first * 40] *
                                  len(scorer._LEGACY_PAID_WORLD_PATHS)) + "\n")
    monkeypatch.setattr(scorer.subprocess, "run", git)
    monkeypatch.setattr(
        api, "_exact_paid_cache_identity", lambda *args, **kwargs: current_identity)
    assert scorer._verified_legacy_paid_cache(
        json.loads(metadata_bytes), dict(current_identity,
            source_sha256=initial[0]["source_request_sha256"],
            prepared_sha256=json.loads(metadata_bytes)["prepared_sha256"]))
    changed_world[0] = True
    assert not scorer._verified_legacy_paid_cache(
        json.loads(metadata_bytes), dict(current_identity,
            source_sha256=initial[0]["source_request_sha256"],
            prepared_sha256=json.loads(metadata_bytes)["prepared_sha256"]))
    changed_world[0] = False

    upgraded = api.PersistentNativeEvaluator(
        binary, fixture, tmp_path / "paid", session_factory=FakeSession,
        run_world=lambda *args, **kwargs: pytest.fail(
            "original authentic fully-recovered cached mobs must not be replayed"))
    try:
        reused = upgraded(level=20, parent=None, mob_count=2, budget=1,
                          rng_mode="balanced", iterations=1,
                          recover_to_full=True)
    finally:
        upgraded.close()
    assert len(reused) == 1
    assert reused[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert reused[0]["reused_exact_native_paid_receipt"] is True
    assert metadata_paths[0].read_bytes() == metadata_bytes
    assert len(list((tmp_path / "paid").glob("*.native.cache.json"))) == 1

    # A mismatched Rust binary never bypasses the native world execution.
    changed_identity = dict(current_identity, native_binary_sha256="e" * 64)
    monkeypatch.setattr(
        api, "_exact_paid_cache_identity", lambda *args, **kwargs: changed_identity)
    changed = api.PersistentNativeEvaluator(
        binary, fixture, tmp_path / "paid", session_factory=FakeSession,
        run_world=paid_world)
    try:
        different = changed(level=20, parent=None, mob_count=2, budget=1,
                            rng_mode="balanced", iterations=1,
                            recover_to_full=True)
    finally:
        changed.close()
    assert len(different) == 1
    assert different[0]["reused_exact_native_paid_receipt"] is False

    # Synthetic cache-corruption regression: a historical schema-1 sidecar
    # cannot encode a World-APL dimension. Even when its original digest,
    # executable identity and current strict native elapsed/recovery score
    # match, an old source-reported non-serial policy is not a serial control.
    old_path = metadata_paths[0].with_name(
        metadata_paths[0].name.removesuffix(".native.cache.json")
        + ".native.json")
    old_receipt = json.loads(old_path.read_text())
    old_receipt["native_world_apl"] = {"pull_mode": "rolling"}
    old_path.write_text(json.dumps(old_receipt, sort_keys=True) + "\n")
    old_meta = json.loads(metadata_paths[0].read_text())
    old_meta["native_raw_receipt_sha256"] = api._file_digest(old_path)
    metadata_paths[0].write_text(json.dumps(old_meta, sort_keys=True) + "\n")
    assert scorer._verified_legacy_paid_cache(
        old_meta, dict(current_identity,
            source_sha256=initial[0]["source_request_sha256"],
            prepared_sha256=old_meta["prepared_sha256"]))

    original_native_calls = []
    def counted_serial_world(*args, **kwargs):
        original_native_calls.append(kwargs.get("world_apl"))
        return paid_world(*args, **kwargs)

    monkeypatch.setattr(
        api, "_exact_paid_cache_identity", lambda *args, **kwargs: current_identity)
    serial = api.PersistentNativeEvaluator(
        binary, fixture, tmp_path / "paid", session_factory=FakeSession,
        run_world=counted_serial_world)
    try:
        fresh = serial(level=20, parent=None, mob_count=2, budget=1,
                       rng_mode="balanced", iterations=1,
                       recover_to_full=True)
    finally:
        serial.close()
    assert original_native_calls == [None]
    assert fresh[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert fresh[0]["reused_exact_native_paid_receipt"] is False
    assert fresh[0]["native_world_apl"] is None


def test_orphaned_cache_metadata_preserves_new_paid_receipts(
        tmp_path, monkeypatch):
    """An orphaned cache sidecar must not discard freshly paid native bytes.

    Fake paid-world transport verifies storage integrity only, not gameplay.
    """
    FakeSession.instances.clear()
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"pinned native binary")
    fixture = Path("fixtures/warlock-l20-native-paid-30s.request.json")
    paid_dir = tmp_path / "paid"

    def identity(path, *, actor_level, mob_count, target_hp):
        return {
            "cache_schema": 2,
            "forever_paid_runtime_sha256": "a" * 64,
            "native_binary_sha256": api._file_digest(path),
            "actor_level": actor_level, "mob_count": mob_count,
            "target_hp": target_hp, "rng_mode": "balanced",
            "iterations": 1, "recovery_policy": "decisions",
            "health_threshold": 1.0, "mana_threshold": 1.0,
            "require_native_health_damage": False,
        }

    monkeypatch.setattr(api, "_exact_paid_cache_identity", identity)

    def paid_once():
        evaluator = api.PersistentNativeEvaluator(
            binary, fixture, paid_dir, session_factory=FakeSession,
            run_world=paid_world)
        try:
            result = evaluator(
                level=20, parent=None, mob_count=2, budget=1,
                rng_mode="balanced", iterations=1, recover_to_full=True)
            assert len(result) == 1
            assert result[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
            return result[0]
        finally:
            evaluator.close()

    original = paid_once()
    original_path = Path(original["native_raw_receipt_file"])
    metadata = list(paid_dir.glob("*.native.cache.json"))
    assert original_path.is_file() and len(metadata) == 1
    untouched_metadata = metadata[0].read_bytes()
    original_path.unlink()  # Simulate interrupted/corrupted artifact copy.

    replacement = paid_once()
    fallback = Path(replacement["native_raw_receipt_file"])
    assert replacement["reused_exact_native_paid_receipt"] is False
    assert fallback != original_path and fallback.is_file()
    assert hashlib.sha256(fallback.read_bytes()).hexdigest() == (
        replacement["native_raw_receipt_sha256"])
    assert metadata[0].read_bytes() == untouched_metadata

    previous_bytes = fallback.read_bytes()
    fallback_meta = fallback.with_name(
        fallback.name.removesuffix(".native.json") + ".native.cache.json")
    assert fallback_meta.is_file()
    assert json.loads(fallback_meta.read_text())["native_raw_receipt_sha256"] == (
        hashlib.sha256(previous_bytes).hexdigest())

    # The intact, separately authenticated fallback is now reusable across
    # sessions, without overwriting or trusting the orphaned primary sidecar.
    repeated = paid_once()
    assert repeated["reused_exact_native_paid_receipt"] is True
    assert Path(repeated["native_raw_receipt_file"]) == fallback
    assert fallback.read_bytes() == previous_bytes
    assert metadata[0].read_bytes() == untouched_metadata

    # The fallback's own receipt digest is mandatory: a modified raw ACK
    # causes a genuine new payment and yet another preserved fallback.
    fallback.write_bytes(previous_bytes + b"\n")
    fresh = paid_once()
    next_fallback = Path(fresh["native_raw_receipt_file"])
    assert fresh["reused_exact_native_paid_receipt"] is False
    assert next_fallback != fallback and next_fallback.is_file()
    assert next_fallback.read_bytes() == previous_bytes
    assert metadata[0].read_bytes() == untouched_metadata
    assert fallback.read_bytes() == previous_bytes + b"\n"
    assert paid_once()["reused_exact_native_paid_receipt"] is True

def test_native_same_session_probe_pays_new_world_and_retains_refusal(tmp_path, monkeypatch):
    """M0.6 must use a NEW world in one Rust session, not cached M0.5 samples."""
    class StatefulSession(FakeSession):
        def __init__(self, binary):
            super().__init__(binary)
            self.prepared = None
            self.last_paid = None

        def request(self, payload):
            if payload["op"] == "state":
                return {
                    "kind": "source_prepared_actor",
                    "actor_level": self.prepared["player"]["level"],
                    "source_sha256": self.prepared["request_sha256"],
                    "retained_combat_runtime": False,
                    "retained_xp": False, "level_transition_supported": False,
                    "last_paid_world": self.last_paid,
                }
            if payload["op"] == "advance":
                self.calls.append(payload)
                # Exercise the real NDJSON parser, not a hand-built exception.
                return rust_wire_request({
                    "ok": False,
                    "error": "native level transition unavailable",
                    "refusal": {
                        "code": "native_level_transition_unsupported",
                        "reason": "post-combat actor and XP are not retained",
                    },
                }, payload)
            result = super().request(payload)
            if payload["op"] == "prepare":
                self.prepared = result
                self.last_paid = None
            return result

    world_runs = []

    def run_world(*args, **kwargs):
        receipt = paid_world(*args, **kwargs)
        world_runs.append(receipt)
        state = FakeSession.instances[-1]
        state.last_paid = {
            "kind": "completed_independent_native_world",
            "source_sha256": kwargs["prepared_payload"]["request_sha256"],
            "actor_level": state.prepared["player"]["level"],
            "world_targets_killed": kwargs["target_count"],
            "post_combat_actor_retained": False,
            "xp_earned": None,
        }
        return receipt

    FakeSession.instances.clear()
    binary = tmp_path / "engine"
    binary.write_bytes(b"pinned native engine")
    monkeypatch.setattr(api, "_exact_paid_cache_identity", lambda *a, **k: {
        "cache_schema": 1, "forever_commit": "f" * 40,
        "native_binary_sha256": api._file_digest(binary),
        "actor_level": 20, "mob_count": 2, "target_hp": 100.0,
        "rng_mode": "balanced", "iterations": 1,
        "recovery_policy": "decisions",
    })
    native = api.PersistentNativeEvaluator(
        binary, Path("fixtures/warlock-l20-native-paid-30s.request.json"),
        tmp_path / "paid", session_factory=StatefulSession, run_world=run_world)
    try:
        # First paid screen produces a reusable cache entry, but an M0.6 probe
        # cannot use it as a post-combat state carried across the boundary.
        sampled = native(level=20, parent=None, mob_count=2, budget=1,
                         rng_mode="balanced", iterations=1, recover_to_full=True)
        assert sampled[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
        assert len(world_runs) == 1
        result = native.probe_native_level_transition(
            from_level=20, to_level=21, mob_count=2, candidate_budget=3)
    finally:
        native.close()
    assert len(world_runs) == 2
    assert result["status"] == "NATIVE_LEVEL_TRANSITION_UNSUPPORTED"
    assert result["continuous_leveling_proven"] is False
    assert result["historical_sample_used_as_continuity"] is False
    assert result["native_advance_refusal_code"] == "native_level_transition_unsupported"
    assert result["paid_first_world"]["reused_exact_native_paid_receipt"] is False
    assert result["native_state_after_world"]["last_paid_world"]["world_targets_killed"] == 2
    assert all(payload.get("actor_level") != 21
               for payload in FakeSession.instances[-1].calls
               if payload["op"] == "prepare")
    assert sum(p["op"] == "advance" for p in FakeSession.instances[-1].calls) == 1


def test_native_same_session_probe_rejects_unbound_world_state(tmp_path, monkeypatch):
    """A paid L20 receipt plus a stale/different Rust state is not continuity."""
    class UnboundSession(FakeSession):
        def request(self, payload):
            if payload["op"] == "state":
                return {"actor_level": 20, "source_sha256": "f" * 64,
                        "last_paid_world": None}
            if payload["op"] == "advance":
                pytest.fail("must not advance without matching paid state")
            return super().request(payload)

    FakeSession.instances.clear()
    binary = tmp_path / "engine"
    binary.write_bytes(b"pinned native engine")
    monkeypatch.setattr(api, "_exact_paid_cache_identity", lambda *a, **k: None)
    native = api.PersistentNativeEvaluator(
        binary, Path("fixtures/warlock-l20-native-paid-30s.request.json"),
        tmp_path / "paid", session_factory=UnboundSession, run_world=paid_world)
    try:
        result = native.probe_native_level_transition(
            from_level=20, to_level=21, mob_count=2, candidate_budget=2)
    finally:
        native.close()
    assert result["status"] == "NATIVE_PAID_STATE_NOT_RETAINED"
    assert result["continuous_leveling_proven"] is False
    assert "paid_first_world" in result


def test_native_continuity_cli_refusal_is_nonzero_and_never_a_sampled_guide(tmp_path):
    """One normal generic optimize entrypoint; explicit unsupported result."""
    from src.v2.native_range_optimizer import main

    class Probe:
        def probe_native_level_transition(self, **kwargs):
            assert kwargs == {"from_level": 20, "to_level": 21,
                              "mob_count": 2, "candidate_budget": 1}
            return {"status": "NATIVE_LEVEL_TRANSITION_UNSUPPORTED",
                    "continuous_leveling_proven": False}

    out = tmp_path / "m06.json"
    rc = main(["--class", "warlock", "--tree", "unconstrained",
               "--start-level", "20", "--end-level", "21",
               "--level-stride", "1", "--n-mobs", "2",
               "--recover-at-end", "true", "--rng", "balanced",
               "--backend", "rust", "--budget", "1",
               "--probe-native-continuity", "--out", str(out)],
              evaluate=Probe())
    assert rc == 2
    assert json.loads(out.read_text())["status"] == "NATIVE_LEVEL_TRANSITION_UNSUPPORTED"


def test_native_item_seed_discards_source_excluded_rating_gear():
    """A reported rating/excluded ID cannot keep poisoning native prepare."""
    source = json.loads(Path(
        "fixtures/warlock-l20-native-paid-30s.request.json").read_text())
    equipped = source["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    assert len(equipped) >= 2
    equipped[0] = {"id": 9001}
    equipped[1] = {"id": 8002}
    options = {"items": [
        {"item_id": 9001, "eligibility": "combat_rating_excluded",
         "native": {"slot": "head"}},
        {"item_id": 8002, "eligibility": "native_eligible",
         "native": {"slot": "neck"}},
        {"item_id": 8001, "eligibility": "native_eligible",
         "native": {"slot": "head"}},
    ]}
    proposals = list(api._source_item_alternatives(source, options))
    actors = [proposal["raid"]["parties"][0]["players"][0] for proposal in proposals]
    assert actors[0]["equipment"]["items"][0] == {"id": 0}
    assert actors[0]["equipment"]["items"][1] == {"id": 8002}
    assert actors[1]["equipment"]["items"][0] == {"id": 8001}
    assert all(9001 not in [row.get("id") for row in actor["equipment"]["items"]]
               for actor in actors)


@pytest.mark.parametrize("level", [20, 40])
def test_native_source_axes_compete_across_l20_l40(level, tmp_path, monkeypatch):
    """Actual producer attempts gear, pet and registered ranks on each level.

    This fake transport exercises proposal breadth and paid-score forwarding;
    it is not evidence that the real Rust actor accepts or kills these builds.
    """
    class NativeAxisSession(FakeSession):
        def request(self, payload):
            if payload["op"] == "options":
                result = super().request(payload)
                learned_rank = 80004 if payload["level"] == 40 else 80003
                result.update({
                    "schema_version": 1,
                    "summons": ["NoSummon", "Imp", "Voidwalker"],
                    "items": [
                        {"item_id": 8001, "eligibility": "native_eligible",
                         "native": {"item_id": 8001, "slot": "head",
                                    "name": "Test source hat A"}},
                        {"item_id": 8002, "eligibility": "native_eligible",
                         "native": {"item_id": 8002, "slot": "head",
                                    "name": "Test source hat B"}},
                    ],
                    "spells": [
                        {"spell_id": 1088, "name": "Shadow Bolt", "rank": "Rank 2"},
                        {"spell_id": learned_rank, "name": "Shadow Bolt",
                         "rank": "Rank 6" if payload["level"] == 40 else "Rank 4"},
                    ],
                })
                return result
            result = super().request(payload)
            learned_rank = 80004 if payload["actor_level"] == 40 else 80003
            result["player"]["spells"] = [{
                "flags": ["SpellFlagAPL"],
                "action_id": {"spell_id": learned_rank},
            }]
            return result

    FakeSession.instances.clear()
    binary = tmp_path / "engine"
    binary.write_bytes(b"native-axis-test")
    monkeypatch.setattr(api, "_exact_paid_cache_identity",
                        lambda *args, **kwargs: None)
    paid = []
    def counted_world(*args, **kwargs):
        paid.append(kwargs["prepared_payload"]["request_sha256"])
        return paid_world(*args, **kwargs)
    native = api.PersistentNativeEvaluator(
        binary, Path("fixtures/warlock-l20-native-paid-30s.request.json"),
        tmp_path / "paid", session_factory=NativeAxisSession,
        run_world=counted_world)
    try:
        rows = native(level=level, parent=None, mob_count=2, budget=10,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()

    prepared = [payload["request"] for payload in NativeAxisSession.instances[-1].calls
                if payload["op"] == "prepare"]
    def actor(source):
        return source["raid"]["parties"][0]["players"][0]
    gear_ids = {actor(request)["equipment"]["items"][0].get("id")
                for request in prepared}
    summons = {actor(request).get("warlock", {}).get("options", {})
               .get("classOptions", {}).get("summon") for request in prepared}
    pet_preparations = [request for request in prepared if actor(request).get(
        "warlock", {}).get("options", {}).get("classOptions", {}).get(
            "summon") in {"Imp", "Voidwalker"}]
    # Native-advertised equipment is the reference for pet comparisons,
    # not the legacy fixture after unsupported items have been zeroed out.
    assert actor(prepared[0])["equipment"]["items"][0]["id"] == 8001
    assert pet_preparations and all(
        actor(request)["equipment"]["items"][0]["id"] == 8001
        for request in pet_preparations)
    requested_spells = {priority["action"]["castSpell"]["spellId"]["spellId"]
                        for request in prepared
                        for priority in actor(request)["rotation"]["priorityList"]
                        if "castSpell" in priority.get("action", {})}
    assert {8001, 8002} <= gear_ids
    assert {"Imp", "Voidwalker"} & summons
    assert (80004 if level == 40 else 80003) in requested_spells
    assert (80003 if level == 40 else 80004) not in requested_spells
    assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED" for row in rows)
    assert len(paid) == len(rows) == 10
    assert {"gear", "pet", "apl"} <= {row["proposal_axis"] for row in rows}
    assert all(row["native_named_build"]["ordered_apl_spells"]
               and row["native_raw_receipt_sha256"]
               for row in rows)
    assert any(any(item["name"] == "Test source hat B"
                   for item in row["native_named_build"]["equipped_item_names_ids"])
               for row in rows)


def test_unadvertised_source_pet_and_item_axes_remain_explicitly_unpaid(
        tmp_path, monkeypatch):
    """No synthetic pet/item options become pretend executable alternatives."""
    native = make_evaluator(tmp_path, monkeypatch)
    try:
        rows = native(level=20, parent=None, mob_count=2, budget=3,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert rows
    assert not any(row.get("proposal_axis") in ("gear", "pet") for row in rows)


def test_human_readable_top_three_cli_retains_exact_paid_receipts(
        tmp_path, monkeypatch):
    from src.v2.native_range_optimizer import main
    native = make_evaluator(tmp_path, monkeypatch)
    shortlist = tmp_path / "paid-shortlist.md"
    result = tmp_path / "native.json"
    try:
        status = main([
            "--class", "warlock", "--tree", "unconstrained",
            "--start-level", "20", "--end-level", "20",
            "--level-stride", "1", "--n-mobs", "2",
            "--recover-at-end", "true", "--rng", "balanced",
            "--backend", "rust", "--budget", "6",
            "--shortlist-out", str(shortlist), "--out", str(result),
        ], evaluate=native)
    finally:
        native.close()
    assert status == 0
    report = shortlist.read_text()
    paid = json.loads(result.read_text())
    assert paid["ranked_alternatives"]
    assert "## Level 20" in report
    assert "### #1" in report and "### #2" in report and "### #3" in report
    assert "Source protobuf SHA256" in report
    assert "Native paid qualified" in report
    # Candidate-axis proposal counts are not the number of distinct *paid*
    # gear, pet, APL and talent values. Never call one value optimized.
    assert "Distinct verified native-paid choices" in report
    assert "gear sets=1; pet values=1;" in report
    assert "One observed paid value, not optimized" in report
    assert "NoSummon / unspecified" in report
    assert "NOT a global optimum" in report
    assert paid["independent_level_rankings"]["20"][0][
        "receipt"]["source_request_sha256"] in report


def test_paid_world_failure_preserves_prepare_phase_and_axis(tmp_path, monkeypatch):
    def unpaid(*args, **kwargs):
        result = paid_world(*args, **kwargs)
        result["native_terminal_recovery"]["mana_after"] = 80.0
        return result
    native = make_evaluator(tmp_path, monkeypatch, world=unpaid)
    try:
        rows = native(level=20, parent=None, mob_count=2, budget=2,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert rows and all(row["native_prepared"] is True
                        and row["status"] == "NATIVE_API_CANDIDATE_REFUSED"
                        and row["proposal_axis"] in ("talent", "apl") for row in rows)
    assert all("NATIVE_TERMINAL_BOTH_RESOURCES_NOT_FULL" in row["native_refusal"]
               for row in rows)
    assert all(len(row["source_request_sha256"]) == 64
               and len(row["engine_binary_sha256"]) == 64 for row in rows)


@pytest.mark.parametrize("level", [20, 40])
def test_refused_legacy_apl_bootstraps_registered_ranks_without_paid_blank_world(
        level, tmp_path, monkeypatch):
    """A native registered spell can be paid even if every legacy APL refuses.

    The initial legacy-APL refusal is real transport evidence; no blank APL is
    evaluated or treated as a successful gameplay candidate.
    """
    class RejectOldRank(FakeSession):
        def request(self, payload):
            if payload["op"] == "options":
                options = super().request(payload)
                options["spells"] = [
                    {"spell_id": 93011 if level == 20 else 94011,
                     "name": "Registered Corruption", "rank": "Rank 1"},
                    {"spell_id": 93012 if level == 20 else 94012,
                     "name": "Registered Shadow Bolt", "rank": "Rank 2"},
                ]
                return options
            if payload["op"] != "prepare":
                return super().request(payload)
            source = payload["request"]
            priorities = source["raid"]["parties"][0]["players"][0][
                "rotation"]["priorityList"]
            ids = [
                action["action"]["castSpell"]["spellId"]["spellId"]
                for action in priorities if "castSpell" in action.get("action", {})
            ]
            if any(spell in (1014, 442226, 6222, 1088) for spell in ids):
                self.calls.append(payload)
                raise api.NativeApiRefusal({
                    "code": "native_unregistered_spell",
                    "reason": "source-native actor refuses inherited spell rank",
                })
            prepared = super().request(payload)
            prepared["player"]["spells"] = [
                {"flags": ["SpellFlagAPL"],
                 "action_id": {"spell_id": 93011 if level == 20 else 94011},
                 "dot": {"native": True}},
                {"flags": ["SpellFlagAPL"],
                 "action_id": {"spell_id": 93012 if level == 20 else 94012},
                 "damage_effect": {"native": True}},
            ]
            return prepared

    FakeSession.instances.clear()
    binary = tmp_path / "engine"
    binary.write_bytes(b"native-level-rank-bootstrap")
    monkeypatch.setattr(api, "_exact_paid_cache_identity",
                        lambda *args, **kwargs: None)
    world_paid = []
    def counted(*args, **kwargs):
        world_paid.append(kwargs["prepared_payload"]["request_sha256"])
        return paid_world(*args, **kwargs)
    native = api.PersistentNativeEvaluator(
        binary, Path("fixtures/warlock-l20-native-paid-30s.request.json"),
        tmp_path / "paid", session_factory=RejectOldRank,
        run_world=counted)
    try:
        rows = native(level=level, parent=None, mob_count=2, budget=5,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert rows[0]["native_refusal_code"] == "native_unregistered_spell"
    assert rows[0]["native_prepared"] is False
    paid = [row for row in rows
            if row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"]
    assert paid and all(row["proposal_axis"] == "native_apl_bootstrap"
                        for row in paid)
    assert len(world_paid) == len(paid)
    assert all(row["native_full_recovery_paid"] is True for row in paid)
    session = RejectOldRank.instances[-1]
    blank = [call for call in session.calls if call["op"] == "prepare"
             and not call["request"]["raid"]["parties"][0]["players"][0][
                 "rotation"]["priorityList"]]
    assert len(blank) == 1
    paid_spells = {
        action["action"]["castSpell"]["spellId"]["spellId"]
        for call in session.calls if call["op"] == "prepare"
        for action in call["request"]["raid"]["parties"][0]["players"][0][
            "rotation"]["priorityList"]
        if call["request"]["raid"]["parties"][0]["players"][0][
            "rotation"]["priorityList"] and
        "castSpell" in action.get("action", {})
        and action["action"]["castSpell"]["spellId"]["spellId"] not in (
            1014, 442226, 6222, 1088)
    }
    expected = {93011, 93012} if level == 20 else {94011, 94012}
    assert paid_spells <= expected and paid_spells
    assert any("Registered Corruption" == spell["name"]
               for row in paid for spell in row[
                   "native_named_build"]["ordered_apl_spells"])


def test_native_apl_bootstrap_refusal_is_explicit_not_a_paid_candidate(
        tmp_path, monkeypatch):
    class RefusingEveryPrepare(FakeSession):
        def request(self, payload):
            if payload["op"] == "prepare":
                self.calls.append(payload)
                raise api.NativeApiRefusal({
                    "code": "native_actor_unavailable",
                    "reason": "native source actor unavailable",
                })
            return super().request(payload)

    native = make_evaluator(tmp_path, monkeypatch)
    native.close()
    native = api.PersistentNativeEvaluator(
        native.binary, Path("fixtures/warlock-l20-native-paid-30s.request.json"),
        tmp_path / "failed", session_factory=RefusingEveryPrepare,
        run_world=lambda *a, **k: pytest.fail("not paid without native prepare"))
    try:
        rows = native(level=20, parent=None, mob_count=2, budget=3,
                      rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert len(rows) == 3
    assert all(row["status"] == "NATIVE_API_CANDIDATE_REFUSED"
               and row["native_refusal_code"] == "native_actor_unavailable"
               for row in rows)
    assert any(row["proposal_axis"] == "native_apl_bootstrap" for row in rows)
    assert not list((tmp_path / "failed").glob("*.native.json"))


def test_native_paid_world_ndjson_refusal_keeps_rust_code_and_no_fake_kills():
    """Real Rust wire shape survives the gsim ACK bridge without a paid PASS."""
    from live_two_world_pulls import NativeWorldChainFailure, run as native_world

    class RefusingApiProcess:
        pid = 32101
        def __init__(self, frame):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(json.dumps(frame) + "\n")
        def poll(self):
            return None

    frame = {
        "ok": False, "error": "prepared input rejected",
        "refusal": {
            "code": "native_world_refused",
            "reason": "prepared input rejected: Warlock spell 11668 is not registered",
        },
    }
    process = RefusingApiProcess(frame)
    with pytest.raises(NativeWorldChainFailure) as failure:
        native_world(
            Path("no-standalone-process"), None, mob_health=100,
            target_count=2, rng_mode="balanced",
            recovery_policy="decisions", health_threshold=1.0,
            mana_threshold=1.0, api_process=process,
            prepared_payload={"request_sha256": "a" * 64})
    assert failure.value.code == "native_world_refused"
    assert failure.value.killed == 0
    assert failure.value.native_damage_events == 0
    assert "spell 11668 is not registered" in failure.value.reason
    # Preserve the established five-part failure tuple for old callers.
    assert len(failure.value.args[0]) == 5
    assert json.loads(process.stdin.getvalue()) == {
        "op": "evaluate", "targets": 2, "rng_mode": "balanced",
        "recover_at_end": True}

    legacy = RefusingApiProcess({"ok": False, "error": "legacy refusal"})
    with pytest.raises(NativeWorldChainFailure) as old:
        native_world(
            Path("no-standalone-process"), None, mob_health=100,
            target_count=2, rng_mode="balanced",
            recovery_policy="decisions", health_threshold=1.0,
            mana_threshold=1.0, api_process=legacy,
            prepared_payload={"request_sha256": "b" * 64})
    assert old.value.code is None
    assert old.value.reason == "legacy refusal"


def test_world_apl_30pct_evaluate_frame_requires_native_applied_threshold_echo():
    """Match Rust #53 nested schema and require native receipt before scoring."""
    from live_two_world_pulls import (
        _persistent_api_evaluate_request, _verify_native_recovery_thresholds,
    )

    baseline = _persistent_api_evaluate_request(
        targets=2, rng_mode="balanced", health_threshold=1.0,
        mana_threshold=1.0)
    assert baseline == {
        "op": "evaluate", "targets": 2, "rng_mode": "balanced",
        "recover_at_end": True,
    }
    thirty = _persistent_api_evaluate_request(
        targets=2, rng_mode="balanced", health_threshold=0.3,
        mana_threshold=0.3)
    assert thirty == dict(
        baseline, between_pulls={
            "health_fraction": 0.3, "mana_fraction": 0.3,
        })
    assert "health_threshold" not in thirty
    assert "mana_threshold" not in thirty
    with pytest.raises(AssertionError, match="THRESHOLDS_NOT_APPLIED"):
        _verify_native_recovery_thresholds(
            {"thresholds": {"health_fraction": 1.0, "mana_fraction": 1.0}},
            health_threshold=0.3, mana_threshold=0.3)
    with pytest.raises(AssertionError, match="THRESHOLDS_NOT_APPLIED"):
        _verify_native_recovery_thresholds(
            {}, health_threshold=0.3, mana_threshold=0.3)
    _verify_native_recovery_thresholds(
        {"thresholds": {"health_fraction": 0.3, "mana_fraction": 0.3}},
        health_threshold=0.3, mana_threshold=0.3)


def test_world_apl_30pct_competes_but_unacknowledged_native_policy_never_ranks(
        tmp_path, monkeypatch):
    """One serial paid competitor; Rust's unacknowledged 30% policy is refused."""
    calls = []
    def current_rust(binary, prepared_path, **kwargs):
        thresholds = (kwargs["health_threshold"], kwargs["mana_threshold"])
        calls.append(thresholds)
        if thresholds == (0.3, 0.3):
            raise AssertionError(
                "RUST_WORLD_NATIVE_RECOVERY_THRESHOLDS_NOT_APPLIED:"
                " requested=(0.3,0.3) observed=1.0/1.0")
        return paid_world(binary, prepared_path, **kwargs)

    native = make_evaluator(tmp_path, monkeypatch, current_rust)
    native.compare_world_rest_30 = True
    try:
        rows = native(
            level=20, parent=None, mob_count=2, budget=2,
            rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert calls == [(1.0, 1.0), (0.3, 0.3)]
    assert [r["status"] for r in rows] == [
        "MEASURED_NATIVE_FULLY_RECOVERED", "NATIVE_API_CANDIDATE_REFUSED"]
    assert rows[0]["native_world_policy"]["rest_when_health_below"] == 1.0
    assert rows[1]["proposal_axis"] == "world_rest_30pct"
    assert rows[1]["native_world_policy"]["rest_when_mana_below"] == 0.3
    assert "THRESHOLDS_NOT_APPLIED" in rows[1]["native_refusal"]
    assert len(list((tmp_path / "paid").glob("*.native.json"))) == 1


def test_native_rest_policies_have_distinct_session_and_disk_cache_identities(
        tmp_path, monkeypatch):
    """30% cannot reuse historical paid 100%-rest evidence, even for same source."""
    calls = []
    def paid_policy(binary, prepared_path, **kwargs):
        thresholds = (kwargs["health_threshold"], kwargs["mana_threshold"])
        calls.append(thresholds)
        original = dict(kwargs, health_threshold=1.0, mana_threshold=1.0)
        return paid_world(binary, prepared_path, **original)

    native = make_evaluator(tmp_path, monkeypatch, paid_policy)
    try:
        source = native._source(20, None)
        prepared = native.session.request({
            "op": "prepare", "actor_level": 20, "request": source})
        params = dict(level=20, mobs=2, target_hp=100.0)
        baseline = native._paid(source, prepared, cid="baseline", **params)
        changed = native._paid(
            source, prepared, cid="changed", health_threshold=0.3,
            mana_threshold=0.3, **params)
        changed_again = native._paid(
            source, prepared, cid="again", health_threshold=0.3,
            mana_threshold=0.3, **params)
    finally:
        native.close()
    assert calls == [(1.0, 1.0), (0.3, 0.3)]
    assert baseline[2] is False and changed[2] is False
    assert changed_again[2] is True
    assert baseline[3] != changed[3] == changed_again[3]


def test_rolling_native_world_apl_request_is_forwarded_and_ack_checked():
    """Real source/world identities and death ACKs, not a policy echo, unlock rolling."""
    from live_two_world_pulls import (
        _persistent_api_evaluate_request, _verify_native_rolling_world_apl,
    )
    policy = copy.deepcopy(api.ROLLING_WORLD_APL_50)
    request = _persistent_api_evaluate_request(
        targets=2, rng_mode="balanced", health_threshold=1.0,
        mana_threshold=1.0, world_apl=policy)
    assert request == {
        "op": "evaluate", "targets": 2, "rng_mode": "balanced",
        "recover_at_end": True, "world_apl": policy,
    }
    kills = [
        {"target_id": "m1", "ack_sha256": "a" * 64},
        {"target_id": "m0", "ack_sha256": "b" * 64},
    ]
    # New required source fields are deliberately not optional. No legacy
    # serial policy echo can bypass this stronger source-ACKed comparison.
    evidence = {
        "source_switch": {
            "prior_world_target_id": "m1", "to_native_target_index": 1,
        },
        "old_target_dot_ticks": 1,
        "first_b_hit_while_a_live": True,
        "first_world_id": "m1",
        "second_world_id": "m0",
    }
    with pytest.raises(AssertionError, match="ROLLING_APL_NOT_PROVEN"):
        _verify_native_rolling_world_apl(
            {}, requested=policy, kills=kills, **evidence)
    with pytest.raises(AssertionError, match="ROLLING_APL_NOT_PROVEN"):
        _verify_native_rolling_world_apl({
            "applied_world_apl": policy,
            "world_overlap": {"source_apl_selected_b": True,
                              "max_concurrent_alive_targets": 1},
        }, requested=policy, kills=kills, **evidence)
    observed = {
        "source_apl_selected_b": True,
        "both_world_targets_lethal_ack": True,
        "native_world_target_indices": [0, 1],
        "world_target_ids": ["m1", "m0"],
        "combined_native_fight_window": True,
    }
    expected = {
        **observed,
        "native_target_to_world_id": {"0": "m1", "1": "m0"},
        "max_concurrent_alive_targets": 2,
        "simultaneously_alive_world_target_ids": ["m1", "m0"],
        "old_target_dot_ticks_after_switch_acked": 1,
        "first_b_source_hit_while_old_a_alive": True,
    }
    assert _verify_native_rolling_world_apl({
        "applied_world_apl": policy, "world_overlap": observed,
    }, requested=policy, kills=kills, **evidence) == expected
    with pytest.raises(AssertionError, match="ROLLING_APL_NOT_PROVEN"):
        _verify_native_rolling_world_apl({
            "applied_world_apl": policy, "world_overlap": observed,
        }, requested=policy, kills=kills,
            **{**evidence, "first_b_hit_while_a_live": False})
    with pytest.raises(AssertionError, match="ROLLING_APL_NOT_PROVEN"):
        _verify_native_rolling_world_apl({
            "applied_world_apl": policy, "world_overlap": observed,
        }, requested=policy, kills=[
            {"target_id": "m1", "ack_sha256": "c" * 64},
            {"target_id": "m0", "ack_sha256": "c" * 64},
        ], **evidence)


def test_rolling_world_apl_unacknowledged_serial_receipt_is_unranked(
        tmp_path, monkeypatch):
    """Request the rolling axis without ever crediting old serial results."""
    observed = []
    def fake_native_world(binary, prepared_path, **kwargs):
        observed.append(kwargs.get("world_apl"))
        return paid_world(binary, prepared_path, **kwargs)

    native = make_evaluator(tmp_path, monkeypatch, fake_native_world)
    native.compare_world_rolling_50 = True
    try:
        rows = native(
            level=20, parent=None, mob_count=2, budget=2,
            rng_mode="balanced", iterations=1, recover_to_full=True)
        # Even if the native policy was ignored, preserve the original
        # response and refuse the same policy again instead of laundering it
        # through a successful serial paid-cache hit.
        repeated = native(
            level=20, parent=None, mob_count=2, budget=2,
            rng_mode="balanced", iterations=1, recover_to_full=True)
    finally:
        native.close()
    assert observed == [None, api.ROLLING_WORLD_APL_50,
                        api.ROLLING_WORLD_APL_50]
    assert [row["status"] for row in rows] == [
        "MEASURED_NATIVE_FULLY_RECOVERED", "NATIVE_API_CANDIDATE_REFUSED",
    ]
    assert rows[1]["proposal_axis"] == "world_rolling_50pct"
    assert rows[1]["native_world_policy"]["world_apl"] == (
        api.ROLLING_WORLD_APL_50)
    assert "ROLLING_APL_NOT_PROVEN" in rows[1]["native_refusal"]
    first_path = Path(rows[1]["native_unverified_receipt_file"])
    second_path = Path(repeated[1]["native_unverified_receipt_file"])
    assert first_path.is_file() and second_path.is_file()
    assert first_path != second_path
    assert json.loads(first_path.read_text())["actual_2d_ack"] is True
    assert hashlib.sha256(first_path.read_bytes()).hexdigest() == (
        rows[1]["native_unverified_receipt_sha256"])
    assert hashlib.sha256(second_path.read_bytes()).hexdigest() == (
        repeated[1]["native_unverified_receipt_sha256"])
    assert len(list((tmp_path / "paid").glob("*.native.unverified.json"))) == 2
    assert len(list((tmp_path / "paid").glob("*.native.json"))) == 1


def test_source_echoed_rolling_policy_never_shares_serial_native_paid_cache(
        tmp_path, monkeypatch):
    """Synthetic native telemetry tests cache identity, NOT real overlap."""
    calls = []
    def synthetic_native_world(binary, prepared_path, **kwargs):
        policy = kwargs.get("world_apl")
        calls.append(copy.deepcopy(policy))
        receipt = paid_world(binary, prepared_path, **kwargs)
        if policy is not None:
            receipt["native_world_apl"] = copy.deepcopy(policy)
            receipt["native_world_overlap_verified"] = True
            receipt["native_world_overlap"] = {
                "combined_native_fight_window": True,
                "source_apl_selected_b": True,
                "both_world_targets_lethal_ack": True,
                "max_concurrent_alive_targets": 2,
                "simultaneously_alive_world_target_ids": ["m1", "m0"],
                "native_target_to_world_id": {"0": "m1", "1": "m0"},
                "old_target_dot_ticks_after_switch_acked": 1,
                "first_b_source_hit_while_old_a_alive": True,
            }
            # A genuine joint Fight has ONE terminal Fight window/mana
            # observation, while both world hostiles have separate ACKs.
            # Keep this synthetic contract fixture consistent with the real
            # paid #1091 receipt; it is NOT itself overlap gameplay evidence.
            last = receipt["native_windows"][-1].copy()
            last["index"] = 0
            receipt["native_windows"] = [last]
            receipt["native_actor_mana_after_joint_overlap_fight"] = (
                receipt.pop("native_actor_mana_after_world_kills")[-1])
            receipt["native_joint_window_end_ns"] = last["native_kill_ns"]
            receipt["world_kills"] = [
                {"target_id": "m1", "ack_sha256": "a" * 64,
                 "world_kill_clock_ns": 1_000_000_000},
                {"target_id": "m0", "ack_sha256": "b" * 64,
                 "world_kill_clock_ns": last["native_kill_ns"]},
            ]
            receipt["world_kill_order"] = ["m1", "m0"]
        return receipt

    native = make_evaluator(tmp_path, monkeypatch, synthetic_native_world)
    try:
        source = native._source(20, None)
        prepared = native.session.request({
            "op": "prepare", "actor_level": 20, "request": source})
        params = dict(level=20, mobs=2, target_hp=100.0)
        serial = native._paid(source, prepared, cid="serial", **params)
        rolling = native._paid(
            source, prepared, cid="rolling",
            world_apl=copy.deepcopy(api.ROLLING_WORLD_APL_50), **params)
        repeat = native._paid(
            source, prepared, cid="rolling-repeat",
            world_apl=copy.deepcopy(api.ROLLING_WORLD_APL_50), **params)
    finally:
        native.close()
    assert calls == [None, api.ROLLING_WORLD_APL_50]
    assert serial[2] is False and rolling[2] is False and repeat[2] is True
    assert serial[3] != rolling[3] == repeat[3]


def test_adaptive_exclusion_skips_exact_paid_source_and_rest_policy(
        tmp_path, monkeypatch):
    world_calls = []

    def observed_world(binary, prepared_path, **kwargs):
        world_calls.append(kwargs["prepared_payload"]["request_sha256"])
        return paid_world(binary, prepared_path, **kwargs)

    native = make_evaluator(tmp_path, monkeypatch, world=observed_world)
    request = dict(level=20, parent=None, mob_count=2, budget=1,
                   rng_mode="balanced", iterations=1, recover_to_full=True)
    try:
        original = native(**request)[0]
        old_key = (
            original["source_request_sha256"],
            json.dumps(original["native_world_policy"], sort_keys=True),
        )
        next_rows = native(
            **request, excluded_paid_source_policies={old_key})
        assert len(next_rows) == 1
        assert next_rows[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
        assert (next_rows[0]["source_request_sha256"],
                json.dumps(next_rows[0]["native_world_policy"],
                           sort_keys=True)) != old_key
        assert len(world_calls) == 2  # no paid replay of the first build
        assert next_rows[0]["reused_exact_native_paid_receipt"] is False
    finally:
        native.close()


def test_normalized_native_source_and_policy_count_once_per_invocation(
        tmp_path, monkeypatch):
    """A Rust-canonical request identity is one contender, not many JSON rows.

    This deliberately simulates multiple raw candidate proposals normalizing
    to one prepared Rust request. It exercises Forever budget/receipt handling,
    not the correctness of native preparation or combat mechanics.
    """
    class CanonicalSession(FakeSession):
        def request(self, payload):
            response = super().request(payload)
            if payload["op"] == "prepare":
                response["request_sha256"] = "d" * 64
            return response

    world_calls = []
    def counted_world(binary, prepared_path, **kwargs):
        world_calls.append(kwargs["prepared_payload"]["request_sha256"])
        return paid_world(binary, prepared_path, **kwargs)

    FakeSession.instances.clear()
    binary = tmp_path / "engine"
    binary.write_bytes(b"native-normalization-test")
    monkeypatch.setattr(api, "_exact_paid_cache_identity",
                        lambda *args, **kwargs: None)
    native = api.PersistentNativeEvaluator(
        binary, Path("fixtures/warlock-l20-native-paid-30s.request.json"),
        tmp_path / "paid", session_factory=CanonicalSession,
        run_world=counted_world)
    try:
        rows = native(level=20, parent=None, mob_count=2, budget=3,
                      rng_mode="balanced", iterations=1,
                      recover_to_full=True)
        prepared_sources = [
            call["request"] for call in native.session.calls
            if call["op"] == "prepare"
        ]
    finally:
        native.close()

    assert len({json.dumps(source, sort_keys=True)
                for source in prepared_sources}) > 1
    assert len(world_calls) == 1
    assert len(rows) == 1
    assert rows[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
    assert rows[0]["source_request_sha256"] == "d" * 64
    assert rows[0]["reused_exact_native_paid_receipt"] is False


def test_adaptive_revisit_joint_gear_and_pet_keep_paid_survivor_build(
        tmp_path, monkeypatch):
    """Recombine native-listed axes on a paid talent/APL survivor, not seed.

    Synthetic Rust/2D transport checks the finite paid scheduler only:
    no real Warlock kills, world overlap or M0.6 winner is inferred.
    """
    def items(source, options):
        # More gear choices than paid revisit slots: the pet still competes.
        for item_id in (0, 8001, 8002, 8003, 8004):
            proposal = copy.deepcopy(source)
            proposal["raid"]["parties"][0]["players"][0][
                "equipment"]["items"][0] = {"id": item_id}
            yield proposal

    def pets(source, options):
        proposal = copy.deepcopy(source)
        proposal["raid"]["parties"][0]["players"][0].setdefault(
            "warlock", {}).setdefault("options", {}).setdefault(
            "classOptions", {})["summon"] = "Voidwalker"
        yield proposal

    paid_requests = []
    def native_world(binary, prepared_path, **kwargs):
        paid_requests.append(kwargs["prepared_payload"]["request_sha256"])
        return paid_world(binary, prepared_path, **kwargs)

    monkeypatch.setattr(api, "_source_item_alternatives", items)
    monkeypatch.setattr(api, "_source_pet_alternatives", pets)
    native = make_evaluator(tmp_path, monkeypatch, world=native_world)
    native.explore_world_policies = True
    request = dict(level=20, parent=None, mob_count=2,
                   rng_mode="balanced", iterations=1, recover_to_full=True)
    try:
        original = native(**request, budget=4)
        assert [row["proposal_axis"] for row in original] == [
            "talent", "gear", "pet", "talent"]
        selected = original[-1]
        assert selected["talents"] != original[0]["talents"]
        assert selected["gear"]["items"][0]["id"] == 8001

        # The selected paid talent family's serial, rest and rolling policies
        # have already been tried/refused. A new original payment should
        # attempt its native source-item/pet crosses, not the old seed axes.
        excluded = {
            (row["source_request_sha256"],
             json.dumps(row["native_world_policy"], sort_keys=True))
            for row in original
        }
        for policy in (
                api._native_world_policy(0.3, 0.3),
                api._native_world_policy(1.0, 1.0, api.ROLLING_WORLD_APL_50)):
            excluded.add((
                selected["source_request_sha256"],
                json.dumps(policy, sort_keys=True)))
        follow_up = native(
            **request, budget=2,
            candidate_hints=[{
                "from_level": 20, "talents": selected["talents"],
                "source_request_sha256": selected["source_request_sha256"],
            }],
            excluded_paid_source_policies=excluded)
    finally:
        native.close()

    assert [row["proposal_axis"] for row in follow_up] == [
        "survivor_gear", "survivor_pet"]
    assert [row["talents"] for row in follow_up] == [
        selected["talents"]] * 2
    assert follow_up[0]["gear"]["items"][0]["id"] == 8002
    assert follow_up[1]["gear"] == selected["gear"]
    assert follow_up[1]["pet"] == "Voidwalker"
    assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
               for row in follow_up)
    assert len(paid_requests) == 6
    assert paid_requests[-2:] == [
        row["source_request_sha256"] for row in follow_up]
    assert all((
        row["source_request_sha256"],
        json.dumps(row["native_world_policy"], sort_keys=True)
    ) not in excluded for row in follow_up)


def test_adaptive_undercompared_paid_survivor_pays_registered_apl_before_rolling(
        tmp_path, monkeypatch):
    """Original M0.6 paid all gear/pet but zero distinct APLs at L20/L40.

    This synthetic native-API/2D transport test verifies only scheduling:
    one registered source-rank APL gets the second adaptive slot. Real Rust
    whole-build prepare, actual world ACK and paid recovery remain mandatory.
    """
    class RegisteredNativeSession(FakeSession):
        def request(self, payload):
            answer = super().request(payload)
            if payload["op"] == "options":
                answer["spells"] = [
                    {"spell_id": 1088, "name": "Shadow Bolt", "rank": "Rank 2"},
                    {"spell_id": 80003, "name": "Shadow Bolt", "rank": "Rank 4"},
                ]
            else:
                answer["player"]["spells"] = [{
                    "flags": ["SpellFlagAPL"],
                    "action_id": {"spell_id": 80003},
                }]
            return answer

    world_calls = []

    def world(binary, prepared_path, **kwargs):
        world_calls.append((kwargs["health_threshold"],
                            kwargs.get("world_apl")))
        # Fake transport cannot prove native 30% rest or rolling overlap.
        # Preserve the scheduler's requested policy separately from the
        # synthetic paid-world shape accepted by this fixture.
        return paid_world(binary, prepared_path, **dict(
            kwargs, health_threshold=1.0, mana_threshold=1.0))

    FakeSession.instances.clear()
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"registered-apl-test-binary")
    monkeypatch.setattr(api, "_exact_paid_cache_identity",
                        lambda *args, **kwargs: None)
    native = api.PersistentNativeEvaluator(
        binary, Path("fixtures/warlock-l20-native-paid-30s.request.json"),
        tmp_path / "paid", session_factory=RegisteredNativeSession,
        run_world=world)
    native.explore_world_policies = True
    request = dict(level=20, parent=None, mob_count=2, rng_mode="balanced",
                   iterations=1, recover_to_full=True)
    try:
        original = native(**request, budget=1)
        assert len(original) == 1
        assert original[0]["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
        selected = original[0]
        excluded = {(selected["source_request_sha256"],
                     json.dumps(selected["native_world_policy"], sort_keys=True))}
        follow_up = native(
            **request, budget=2,
            candidate_hints=[{
                "from_level": 20, "talents": selected["talents"],
                "source_request_sha256": selected["source_request_sha256"],
            }],
            excluded_paid_source_policies=excluded)
    finally:
        native.close()

    assert [row["proposal_axis"] for row in follow_up] == [
        "world_rest_30pct", "survivor_apl"]
    assert all(row["status"] == "MEASURED_NATIVE_FULLY_RECOVERED"
               and row["native_full_recovery_paid"] for row in follow_up)
    assert follow_up[0]["source_request_sha256"] == selected["source_request_sha256"]
    assert follow_up[0]["native_world_policy"]["rest_when_mana_below"] == 0.3
    assert follow_up[1]["source_request_sha256"] != selected["source_request_sha256"]
    assert follow_up[1]["apl"]["priorityList"][-1]["action"][
        "castSpell"]["spellId"]["spellId"] == 80003
    assert follow_up[1]["native_world_policy"]["pull_mode"] == "serial"
    assert len(world_calls) == 3  # old serial, unpaid rest, new APL; no replay
    assert world_calls == [(1.0, None), (0.3, None), (1.0, None)]
