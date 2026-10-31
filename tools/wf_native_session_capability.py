#!/usr/bin/env python3
"""Probe a *real* native executable for the incremental world/ACK protocol.

This is intentionally not a simulation or P7 certificate. Current one-shot
forever-engine builds are expected to return BLOCKED until native session
support is implemented in the selected engine revision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Direct CLI invocation (python tools/...) must resolve the repository package.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.game.runtime.native_step_protocol import NativeProtocolError, RustStepSession, PROTOCOL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = {"protocol": PROTOCOL, "binary": str(args.binary), "status": "BLOCKED",
              "checkpoint_certified": False, "live_2d_trace_executed": False}
    try:
        result["binary_sha256"] = hashlib.sha256(args.binary.read_bytes()).hexdigest()
        with RustStepSession(args.binary, timeout_s=4) as session:
            result["status"] = "SESSION_HANDSHAKE_ONLY"
            result["session_id"] = session.session_id
            result["blocker"] = "REAL_GSIM_2D_ACTION_ACK_AND_CAUSAL_PERTURBATION_NOT_EXECUTED"
    except (NativeProtocolError, OSError) as exc:
        result["blocker"] = type(exc).__name__ + ":" + str(exc)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result))
    return 0 if result["status"] == "SESSION_HANDSHAKE_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
