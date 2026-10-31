"""Strict JSONL transport for a future *real* MythicSim Rust incremental session.

This is a protocol boundary, NOT evidence that forever-engine currently implements
a session or that a gsim 2D coupled encounter has been executed.  A production
gate must additionally exercise a genuine gsim CombatRuntime with a real native
session, record a perturbation/control pair, and check combat/ACK effects.
"""
from __future__ import annotations

import hashlib
import json
import queue
import subprocess
import threading
from pathlib import Path
from typing import Mapping

PROTOCOL = "gsim-msim-step-v1"


class NativeProtocolError(RuntimeError):
    pass


def state_hash(world: Mapping) -> str:
    if not isinstance(world, Mapping) or not world:
        raise NativeProtocolError("EMPTY_WORLD_STATE")
    return hashlib.sha256(json.dumps(world, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


class RustStepSession:
    """One process / one stateful combat session; never restart per tick.

    Only Rust decides combat, resources, cooldowns and buffs. The world owns
    positions, facing, range, movement and CC. Both sides use integer ms.
    This transport does not invent a native decision or apply combat damage.
    """

    def __init__(self, binary: Path, *, timeout_s: float = 5.0):
        binary = Path(binary).resolve()
        if not binary.is_file():
            raise NativeProtocolError("NATIVE_BINARY_NOT_FOUND")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.binary_sha256 = hashlib.sha256(binary.read_bytes()).hexdigest()
        self.timeout_s = timeout_s
        self._process = subprocess.Popen(
            [str(binary), "session", "--protocol", PROTOCOL],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read_lines, daemon=True)
        self._reader.start()
        self._seq = 0
        self._last_clock_ms = -1
        self._pending = None
        self._last_ack = None
        try:
            hello = self._read()
            if (hello.get("type") != "hello" or hello.get("protocol") != PROTOCOL
                    or hello.get("engine") != "forever-engine"
                    or not isinstance(hello.get("session_id"), str)
                    or not hello["session_id"]):
                raise NativeProtocolError("NATIVE_INCREMENTAL_HELLO_MISSING")
            self.session_id = hello["session_id"]
        except Exception:
            self.close()
            raise

    def _read_lines(self):
        try:
            for line in self._process.stdout:
                self._lines.put(line)
        finally:
            self._lines.put(None)

    def _read(self) -> dict:
        try:
            line = self._lines.get(timeout=self.timeout_s)
        except queue.Empty as exc:
            raise NativeProtocolError("NATIVE_INCREMENTAL_RESPONSE_TIMEOUT") from exc
        if line is None:
            raise NativeProtocolError("NATIVE_INCREMENTAL_SESSION_UNAVAILABLE")
        try:
            obj = json.loads(line)
        except ValueError as exc:
            raise NativeProtocolError("NATIVE_INCREMENTAL_INVALID_JSON") from exc
        if not isinstance(obj, dict):
            raise NativeProtocolError("NATIVE_INCREMENTAL_INVALID_MESSAGE")
        return obj

    def _send(self, message: dict):
        if self._process.poll() is not None or self._process.stdin is None:
            raise NativeProtocolError("NATIVE_SESSION_TERMINATED")
        try:
            self._process.stdin.write(json.dumps(message, sort_keys=True, allow_nan=False) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise NativeProtocolError("NATIVE_SESSION_WRITE_FAILED") from exc

    def boundary(self, *, clock_ms: int, world: Mapping) -> dict:
        """Advance to a real world boundary; return an unexecuted native action.

        Caller must apply the prescribed WORLD action in actual gsim, then ACK
        with the measured resulting world state before advancing further.
        """
        if type(clock_ms) is not int or clock_ms <= self._last_clock_ms:
            raise NativeProtocolError("WORLD_CLOCK_NOT_MONOTONIC")
        if self._pending is not None:
            raise NativeProtocolError("UNACKNOWLEDGED_NATIVE_ACTION")
        digest = state_hash(world)
        seq = self._seq + 1
        self._send({"type": "boundary", "protocol": PROTOCOL, "session_id": self.session_id,
                    "seq": seq, "clock_ms": clock_ms, "world_sha256": digest,
                    "world": dict(world), "previous_ack": self._last_ack})
        reply = self._read()
        if (reply.get("type") != "native_action" or reply.get("session_id") != self.session_id
                or type(reply.get("seq")) is not int or reply["seq"] != seq
                or reply.get("observed_world_sha256") != digest
                or (seq > 1 and reply.get("accepted_ack_id") != self._last_ack["ack_id"])
                or (seq == 1 and reply.get("accepted_ack_id") is not None)
                or not isinstance(reply.get("action"), dict)
                or not isinstance(reply.get("action_id"), str) or not reply["action_id"]):
            raise NativeProtocolError("NATIVE_ACTION_DID_NOT_ACK_BOUNDARY_AND_WORLD")
        self._pending = reply["action_id"]
        self._last_clock_ms = clock_ms
        self._seq = seq
        return reply

    def ack_world_applied(self, *, action_id: str, world_after: Mapping) -> dict:
        """Called only AFTER the real gsim world applies a native world action."""
        if self._pending is None or action_id != self._pending:
            raise NativeProtocolError("WORLD_ACK_ACTION_ID_MISMATCH")
        digest = state_hash(world_after)
        ack = {"ack_id": f"{self.session_id}:{self._seq}:{action_id}",
               "action_id": action_id, "world_after_sha256": digest,
               "clock_ms": self._last_clock_ms}
        self._last_ack = ack
        self._pending = None
        return ack

    def close(self):
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def snapshot_gsim_world(runtime) -> dict:
    """Capture positions and CC from an ACTUAL gsim CombatRuntime, not caller JSON.

    This is a read-only observation function. It never evaluates a native
    spell, advances the world, or pretends an ACK was applied. The native
    combat engine must still implement the session protocol independently.
    """
    from src.game.runtime.simulator import CombatRuntime

    if not isinstance(runtime, CombatRuntime):
        raise NativeProtocolError("WORLD_CONTROLLER_NOT_GSIM_COMBAT_RUNTIME")
    if not runtime._pack_positions or not set(runtime.targets).issubset(runtime._pack_positions):
        raise NativeProtocolError("WORLD_2D_TARGET_COORDINATES_MISSING")
    if runtime.target.id not in runtime.targets:
        raise NativeProtocolError("WORLD_SELECTED_TARGET_UNKNOWN")
    clock_ms = round(float(runtime.actor.current_time_s) * 1000)
    if clock_ms < 0 or abs(clock_ms / 1000 - runtime.actor.current_time_s) > 0.000501:
        raise NativeProtocolError("WORLD_CLOCK_MILLISECOND_PRECISION_UNSUPPORTED")
    enemies = {}
    for target_id, target in sorted(runtime.targets.items()):
        xy = runtime._enemy_position_at(target_id)
        enemies[target_id] = {
            "xy_yards": [float(xy[0]), float(xy[1])],
            "health": float(target.health),
            "alive": bool(target.alive),
            "engaged": target_id in runtime._engaged_targets,
            "controls": {str(k): float(v) for k, v in sorted(target.active_controls.items())},
            "attacker_relative_position": target.metadata.get("attacker_relative_position"),
        }
    return {
        "clock_ms": clock_ms,
        "player_id": runtime.actor.id,
        "player_xy_yards": list(map(float, runtime.player_position_yards)),
        "selected_target_id": runtime.target.id,
        "enemies": enemies,
        "world_2d_source": "gsim.CombatRuntime",
        # No unverified facing: relative position may be None until real
        # source-backed controller geometry supplies it.
        "facing_proven": False,
    }
