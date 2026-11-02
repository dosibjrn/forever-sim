"""Unit-only native JSONL clock/ACK contract; not a live Rust session or gate PASS."""
import pytest

from src.game.runtime.native_step_protocol import (
    NativeProtocolError, RustStepSession, PROTOCOL, state_hash,
)


def session_stub():
    """Exercise the production transport's validation, not an invented combat engine."""
    session = RustStepSession.__new__(RustStepSession)
    session.session_id = "unit-session"
    session._seq = 0
    session._last_clock_ms = -1
    session._last_ack = None
    session._pending = None
    sent = []
    session._send = lambda message: sent.append(message)
    return session, sent


def respond_to_boundary(session, world, seq, *, ack_id=None):
    session._read = lambda: {
        "type": "native_action",
        "session_id": session.session_id,
        "seq": seq,
        "observed_world_sha256": state_hash(world),
        "accepted_ack_id": ack_id,
        "action": {"kind": "native-action-unit-only"},
        "action_id": f"action-{seq}",
    }


def test_two_distinct_targets_one_transport_session_and_actual_ack_clock():
    session, sent = session_stub()
    world1 = {"clock_ms": 100, "selected_target_id": "mob-1"}
    respond_to_boundary(session, world1, 1)
    action1 = session.boundary(clock_ms=100, world=world1)
    assert action1["action_id"] == "action-1"
    world_after = {"clock_ms": 125, "selected_target_id": "mob-1", "alive": False}
    ack1 = session.ack_world_applied(action_id="action-1", world_after=world_after)
    assert ack1["clock_ms"] == 125
    assert ack1["world_after_sha256"] == state_hash(world_after)

    world2 = {"clock_ms": 150, "selected_target_id": "mob-2"}
    respond_to_boundary(session, world2, 2, ack_id=ack1["ack_id"])
    session.boundary(clock_ms=150, world=world2)
    assert len(sent) == 2
    assert sent[0]["protocol"] == sent[1]["protocol"] == PROTOCOL
    assert sent[0]["session_id"] == sent[1]["session_id"] == "unit-session"
    assert sent[1]["previous_ack"] == ack1
    assert sent[1]["world_sha256"] == state_hash(world2)


@pytest.mark.parametrize("bad_clock", [None, 90, 110, 100.0, True])
def test_boundary_cannot_claim_a_different_world_clock(bad_clock):
    session, sent = session_stub()
    world = {"clock_ms": bad_clock, "selected_target_id": "mob-1"}
    with pytest.raises(NativeProtocolError, match="WORLD_BOUNDARY_CLOCK_MISMATCH"):
        session.boundary(clock_ms=100, world=world)
    assert not sent


@pytest.mark.parametrize("bad_clock", [None, 99, 99.5, True])
def test_applied_ack_cannot_rewind_or_forge_time(bad_clock):
    session, _ = session_stub()
    world = {"clock_ms": 100, "selected_target_id": "mob-1"}
    respond_to_boundary(session, world, 1)
    session.boundary(clock_ms=100, world=world)
    with pytest.raises(NativeProtocolError, match="WORLD_APPLIED_ACK_CLOCK_INVALID"):
        session.ack_world_applied(
            action_id="action-1",
            world_after={"clock_ms": bad_clock, "selected_target_id": "mob-1"},
        )
    assert session._pending == "action-1"


def test_missing_or_duplicate_ack_fails_closed_before_next_pull():
    session, sent = session_stub()
    world1 = {"clock_ms": 100, "selected_target_id": "mob-1"}
    respond_to_boundary(session, world1, 1)
    session.boundary(clock_ms=100, world=world1)
    with pytest.raises(NativeProtocolError, match="UNACKNOWLEDGED_NATIVE_ACTION"):
        session.boundary(clock_ms=101, world={"clock_ms": 101, "selected_target_id": "mob-2"})
    with pytest.raises(NativeProtocolError, match="WORLD_ACK_ACTION_ID_MISMATCH"):
        session.ack_world_applied(
            action_id="wrong", world_after={"clock_ms": 101, "selected_target_id": "mob-1"}
        )
    session.ack_world_applied(
        action_id="action-1", world_after={"clock_ms": 101, "selected_target_id": "mob-1"}
    )
    with pytest.raises(NativeProtocolError, match="WORLD_ACK_ACTION_ID_MISMATCH"):
        session.ack_world_applied(
            action_id="action-1", world_after={"clock_ms": 102, "selected_target_id": "mob-1"}
        )
    assert len(sent) == 1


def test_next_boundary_must_be_after_last_applied_world_ack_clock():
    """A native boundary cannot rewind into time already paid for by gsim."""
    session, sent = session_stub()
    first = {"clock_ms": 100, "selected_target_id": "mob-1"}
    respond_to_boundary(session, first, 1)
    session.boundary(clock_ms=100, world=first)
    applied = {"clock_ms": 125, "selected_target_id": "mob-1", "alive": False}
    ack = session.ack_world_applied(action_id="action-1", world_after=applied)
    assert ack["clock_ms"] == 125

    # This was previously accepted because the internal monotonic floor was 100.
    for bad_clock in (110, 125):
        with pytest.raises(NativeProtocolError, match="WORLD_CLOCK_NOT_MONOTONIC"):
            session.boundary(
                clock_ms=bad_clock,
                world={"clock_ms": bad_clock, "selected_target_id": "mob-2"},
            )
    assert len(sent) == 1
    assert session._seq == 1
    assert session._pending is None
    assert session._last_ack == ack

    second = {"clock_ms": 126, "selected_target_id": "mob-2"}
    respond_to_boundary(session, second, 2, ack_id=ack["ack_id"])
    session.boundary(clock_ms=126, world=second)
    assert len(sent) == 2
    assert sent[-1]["previous_ack"] == ack
