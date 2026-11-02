"""Transport-unit tests only: fake process must NEVER count as native P7 evidence."""
from __future__ import annotations

import sys
import textwrap

import pytest

from src.game.runtime.native_step_protocol import (
    NativeProtocolError, RustStepSession, state_hash,
)


def fake_engine(tmp_path, *, bad_hash=False):
    engine = tmp_path / "fake-native-for-protocol-test"
    engine.write_text("#!" + sys.executable + "\n" + textwrap.dedent("""
        import json
        import sys
        print(json.dumps({"type":"hello", "protocol":"gsim-msim-step-v1",
                          "engine":"forever-engine", "session_id":"unit-only"}), flush=True)
        for line in sys.stdin:
            boundary=json.loads(line)
            print(json.dumps({"type":"native_action",
                "session_id":"unit-only",
                "seq":boundary["seq"],
                "observed_world_sha256": ("forged" if BAD_HASH else boundary["world_sha256"]),
                "accepted_ack_id":(boundary["previous_ack"] or {}).get("ack_id"),
                "action_id":str(boundary["seq"])+":cast",
                "action":{"kind":"cast", "source_action_id":"unit-test-only"}}), flush=True)
    """).replace("BAD_HASH", "True" if bad_hash else "False"))
    engine.chmod(0o755)
    return engine


def test_real_subprocess_boundary_ack_and_second_decision(tmp_path):
    with RustStepSession(fake_engine(tmp_path)) as session:
        first = {"player_xy":[0,0], "target_xy":[20,0], "target_attacking":False}
        response = session.boundary(clock_ms=0, world=first)
        assert response["observed_world_sha256"] == state_hash(first)
        ack = session.ack_world_applied(
            action_id=response["action_id"],
            world_after={"player_xy":[0,0], "target_xy":[19,0], "target_attacking":False})
        second = session.boundary(clock_ms=100, world={
            "player_xy":[0,0], "target_xy":[19,0], "target_attacking":False})
        assert second["accepted_ack_id"] == ack["ack_id"]
        session.ack_world_applied(action_id=second["action_id"], world_after=first)


def test_missing_ack_prevents_world_from_advancing(tmp_path):
    with RustStepSession(fake_engine(tmp_path)) as session:
        session.boundary(clock_ms=0, world={"x":1})
        with pytest.raises(NativeProtocolError, match="UNACKNOWLEDGED_NATIVE_ACTION"):
            session.boundary(clock_ms=1, world={"x":2})
        with pytest.raises(NativeProtocolError, match="WORLD_ACK_ACTION_ID_MISMATCH"):
            session.ack_world_applied(action_id="not-native-id", world_after={"x":2})


def test_spoofed_world_hash_rejected(tmp_path):
    with RustStepSession(fake_engine(tmp_path, bad_hash=True)) as session:
        with pytest.raises(NativeProtocolError, match="NATIVE_ACTION_DID_NOT_ACK_BOUNDARY"):
            session.boundary(clock_ms=0, world={"real_gsim_state":10})


def test_nonincremental_engine_fails_closed(tmp_path):
    binary=tmp_path/"one-shot-engine"
    binary.write_text("#!/bin/sh\nexit 1\n")
    binary.chmod(0o755)
    with pytest.raises(NativeProtocolError, match="NATIVE_INCREMENTAL_SESSION_UNAVAILABLE"):
        RustStepSession(binary, timeout_s=1)


def test_world_snapshot_came_from_real_moving_gsim_runtime():
    from src.game.model import ActorDefinition, ResourceDefinition
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    from src.game.runtime.native_step_protocol import snapshot_gsim_world

    actor = ActorState.from_ir(
        ActorDefinition('hero', 'player', base_stats={}),
        (ResourceDefinition('health', 'Health', 'hero', initial_amount=500, capacity=500),), ())
    rt = CombatRuntime(
        actor=actor, target=TargetState.with_health('m0', 500),
        other_targets=(TargetState.with_health('m1', 500),),
        spatial_positions_yards={'m0': (0., 0.), 'm1': (20., 0.)},
        enemy_move_speed_yards_s=5., melee_radius_yards=5.)
    rt.engage_target('m1')
    rt.select_target('m1')
    start = snapshot_gsim_world(rt)
    assert start["world_2d_source"] == "gsim.CombatRuntime"
    assert start["enemies"]["m1"]["xy_yards"] == [20., 0.]
    assert start["facing_proven"] is False
    rt.advance_to(1.)
    later = snapshot_gsim_world(rt)
    assert later["enemies"]["m1"]["xy_yards"] == pytest.approx([15., 0.])
    assert later["clock_ms"] == 1000
    assert state_hash(start) != state_hash(later)


def test_world_snapshot_rejects_fake_and_missing_coordinates():
    from src.game.model import ActorDefinition
    from src.game.runtime import ActorState, CombatRuntime, TargetState
    from src.game.runtime.native_step_protocol import snapshot_gsim_world
    with pytest.raises(NativeProtocolError, match="WORLD_CONTROLLER_NOT_GSIM"):
        snapshot_gsim_world({"world": "fake"})
    actor = ActorState.from_ir(ActorDefinition('hero', 'player', base_stats={}), (), ())
    rt = CombatRuntime(actor=actor, target=TargetState.with_health('m0', 100))
    with pytest.raises(NativeProtocolError, match="WORLD_2D_TARGET_COORDINATES_MISSING"):
        snapshot_gsim_world(rt)
