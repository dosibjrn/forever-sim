"""Fail-closed audit of *actual gsim* consecutive-pull evidence.

This does not implement or attest a native Go/Rust world-action ACK. It checks
the existing persistent CombatRuntime actor trace before a diagnostic may
report that N distinct targets were killed with paid recovery and one clock.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite


def audit_persistent_pull_trace(rows: Sequence[Mapping], *, expected_mobs: int) -> dict:
    if type(expected_mobs) is not int or expected_mobs < 1:
        raise ValueError("PERSISTENT_TRACE_INVALID_EXPECTED_MOBS")
    if len(rows) != expected_mobs:
        raise ValueError("PERSISTENT_TRACE_MOB_COUNT_MISMATCH")
    seen = set()
    previous_recovery_end = None
    tolerance = 1e-7
    for expected_index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping) or type(row.get("mob")) is not int or row["mob"] != expected_index:
            raise ValueError("PERSISTENT_TRACE_MOB_ORDER_INVALID")
        target_id = row.get("target_id")
        if not isinstance(target_id, str) or not target_id or target_id in seen:
            raise ValueError("PERSISTENT_TRACE_TARGET_NOT_UNIQUE")
        seen.add(target_id)
        times = []
        for field in ("pull_started_s", "kill_finished_s", "recovery_s", "recovery_finished_s"):
            value = row.get(field)
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError("PERSISTENT_TRACE_INVALID_TIME:" + field)
            times.append(float(value))
        start, kill, recovery, recovery_end = times
        if kill <= start + tolerance:
            raise ValueError("PERSISTENT_TRACE_NO_POSITIVE_COMBAT")
        if recovery_end + tolerance < kill + recovery:
            raise ValueError("PERSISTENT_TRACE_UNPAID_RECOVERY")
        if previous_recovery_end is not None and start + tolerance < previous_recovery_end:
            raise ValueError("PERSISTENT_TRACE_CLOCK_ROLLBACK")
        previous_recovery_end = recovery_end
    return {
        "status": "GSIM_PERSISTENT_TRACE_INVARIANTS_ONLY",
        "distinct_targets": len(seen),
        "monotonic_pull_clock": True,
        "recovery_accounting_checked": True,
        "native_world_action_ack_verified": False,
    }
