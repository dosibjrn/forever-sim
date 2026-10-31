#!/usr/bin/env python3
"""Surgical, SHA-pinned instrumentation of MythicSim Go source event boundary.

Only the exact upstream spell_result.go Git blob may be modified. The added
call is inside actual spell.dealDamageInternal, before native metrics; it
observes native results and DOES NOT replace or recompute the combat engine.
"""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path

PINNED_BLOB_SHA = "f196a60831571c2ff2ccf536aabe17cfa873b5ea"
ORIGINAL = (
    b"func (spell *Spell) dealDamageInternal(sim *Simulation, isPeriodic bool, result *SpellResult) {\n"
    b"\tisPartialResist := result.DidResist()\n\n"
    b"\tif sim.CurrentTime >= 0 {\n"
)
REPLACEMENT = ORIGINAL + b"\t\trecordWorldDamageForGsim(sim, spell, result, isPeriodic)\n"


def git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def patch_native_spell_result(path: Path) -> None:
    raw = path.read_bytes()
    observed = git_blob_sha(raw)
    if observed != PINNED_BLOB_SHA:
        raise ValueError("PINNED_NATIVE_SPELL_RESULT_BLOB_MISMATCH:" + observed)
    if raw.count(ORIGINAL) != 1 or b"recordWorldDamageForGsim(" in raw:
        raise ValueError("PINNED_NATIVE_SPELL_HOOK_ANCHOR_INVALID")
    updated = raw.replace(ORIGINAL, REPLACEMENT, 1)
    path.write_bytes(updated)
    if updated.count(b"recordWorldDamageForGsim(sim, spell, result, isPeriodic)") != 1:
        raise ValueError("PINNED_NATIVE_SPELL_HOOK_NOT_SINGLE")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_native_spell_result.py UPSTREAM/sim/core/spell_result.go")
    patch_native_spell_result(Path(sys.argv[1]))
    print("PINNED_NATIVE_SPELL_DAMAGE_HOOK_APPLIED")
