"""Neutral selected-MythicSim request/prepare/execute transport.

This module knows only the native wire contract. It does not encode GameIR,
source legality, talent rules, action availability or gameplay semantics.
Callers own scenario/candidate generation; MythicSim owns validation,
preparation, refusal and execution.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import time
from enum import Enum
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NATIVE_INTEGRATION = _REPO_ROOT / "integrations" / "mythicsim-rust"
if str(_NATIVE_INTEGRATION) not in sys.path:
    sys.path.insert(0, str(_NATIVE_INTEGRATION))

import native_executor as _native_executor


class NativeCandidateClientError(RuntimeError):
    """Malformed native request envelope supplied by the caller."""


class NativeRngMode(str, Enum):
    BALANCED = "balanced"


def _request_player(request: dict) -> dict:
    """Extract the request player without making a class/game-legality decision."""
    try:
        player = request["raid"]["parties"][0]["players"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise NativeCandidateClientError("NATIVE_REQUEST_PLAYER_PATH_MISSING") from exc
    if not isinstance(player, dict):
        raise NativeCandidateClientError("NATIVE_REQUEST_PLAYER_INVALID")
    if not isinstance(request.get("simOptions"), dict):
        raise NativeCandidateClientError("NATIVE_REQUEST_SIM_OPTIONS_MISSING")
    return player

def _json_object(raw: str) -> dict | None:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None

def prepare_native_request(
    *,
    binary: str | Path,
    request: dict,
    scenario: str,
    deadline: float,
) -> dict[str, object]:
    """Forward any class's candidate request to the selected prepare CLI.

    This transport validates only the request envelope. It does
    not whitelist classes or decide game legality; the result preserves the
    native PreparedV2 object or its structured refusal.
    """
    binary_path = Path(binary)
    if not binary_path.is_file():
        return {"status": "BLOCKED", "stage": "prepare",
                "reason": "SELECTED_RUST_BINARY_MISSING"}
    if not isinstance(scenario, str) or not scenario.strip() or len(scenario) > 200:
        raise NativeCandidateClientError("NATIVE_CANDIDATE_SCENARIO_ID_INVALID")

    payload = copy.deepcopy(request)
    player = _request_player(payload)
    options = payload["simOptions"]
    if isinstance(options.get("iterations"), bool) or not isinstance(options.get("iterations"), int) or options["iterations"] < 1:
        raise NativeCandidateClientError("NATIVE_CANDIDATE_PREPARE_ITERATIONS_INVALID")
    options["debugFirstIteration"] = False

    with tempfile.TemporaryDirectory(prefix="forever-native-candidate-") as directory:
        request_path = Path(directory) / "request.json"
        prepared_path = Path(directory) / "prepared.json"
        request_path.write_text(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0.05:
            return {"status": "ERROR", "stage": "prepare",
                    "reason": "NATIVE_CANDIDATE_PREPARE_DEADLINE_EXPIRED"}
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [
                    str(binary_path), "prepare", "--request", str(request_path),
                    "--scenario", scenario, "--outfile", str(prepared_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max(0.001, deadline - time.monotonic()),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "ERROR", "stage": "prepare",
                    "reason": f"NATIVE_PREPARE_CLI_FAILED:{type(exc).__name__}:{exc}"}

        elapsed = round(time.monotonic() - started, 6)
        if completed.returncode != 0:
            refusal = _json_object(completed.stdout or "")
            if refusal is not None and refusal.get("prepared") is False:
                details = refusal.get("refusal")
                details = details if isinstance(details, dict) else {}
                code = details.get("code")
                status = (
                    # The native prepare contract distinguishes invalid
                    # request/talent payloads from explicit unsupported coverage.
                    "INVALID" if code in {"request", "talents"}
                    else "ERROR" if code == "prepare_fault"
                    else "UNSUPPORTED"
                )
                return {
                    "status": status,
                    "stage": "prepare",
                    "reason": str(details.get("reason") or code or "NATIVE_PREPARE_REFUSED"),
                    "refusal": details,
                    "elapsed_seconds": elapsed,
                }
            return {
                "status": "ERROR",
                "stage": "prepare",
                "reason": "NATIVE_PREPARE_FAILED_WITHOUT_STRUCTURED_REFUSAL",
                "returncode": completed.returncode,
                "stdout_tail": (completed.stdout or "")[-700:],
                "stderr_tail": (completed.stderr or "")[-700:],
                "elapsed_seconds": elapsed,
            }
        if not prepared_path.is_file():
            return {"status": "ERROR", "stage": "prepare",
                    "reason": "NATIVE_PREPARE_OUTPUT_MISSING",
                    "stdout_tail": (completed.stdout or "")[-700:],
                    "stderr_tail": (completed.stderr or "")[-700:],
                    "elapsed_seconds": elapsed}
        raw = prepared_path.read_bytes()
        try:
            prepared = json.loads(raw)
        except (UnicodeDecodeError, ValueError) as exc:
            return {"status": "ERROR", "stage": "prepare",
                    "reason": f"NATIVE_PREPARE_OUTPUT_INVALID_JSON:{exc}",
                    "elapsed_seconds": elapsed}
        if (not isinstance(prepared, dict)
                or prepared.get("schema_version") != 2
                or prepared.get("contract") != "forever-prepared"
                or prepared.get("scenario_id") != scenario):
            return {"status": "ERROR", "stage": "prepare",
                    "reason": "NATIVE_PREPARE_OUTPUT_CONTRACT_MISMATCH",
                    "elapsed_seconds": elapsed}
        reference = prepared.get("reference")
        prepared_player = prepared.get("player")
        if (not isinstance(reference, dict)
                or not isinstance(reference.get("engine_revision"), str)
                or not reference["engine_revision"].strip()
                or not isinstance(prepared_player, dict)
                or prepared_player.get("talents_string") != player.get("talentsString")
                or not isinstance(prepared_player.get("talents"), dict)):
            return {"status": "ERROR", "stage": "prepare",
                    "reason": "NATIVE_PREPARE_OUTPUT_IDENTITY_MISMATCH",
                    "elapsed_seconds": elapsed}
        return {
            "status": "PREPARED",
            "stage": "prepare",
            "engine_identity": reference["engine_revision"],
            "request_sha256": prepared.get("request_sha256"),
            "prepared_sha256": hashlib.sha256(raw).hexdigest(),
            "elapsed_seconds": elapsed,
            "prepared": prepared,
        }

def _simulate_prepared(
    *,
    binary_path: Path,
    prepared: dict,
    rng_mode: NativeRngMode,
    iterations: int,
    seed: int,
    deadline: float,
) -> dict[str, object]:
    """Execute one PreparedV2 input through the selected Rust simulator.

    Missing, malformed or non-finite native scores remain execution errors;
    this client never synthesizes a score or falls back to Python.
    """
    with tempfile.TemporaryDirectory(prefix="forever-native-candidate-sim-") as directory:
        root = Path(directory)
        prepared_path = root / "prepared.json"
        report_path = root / "report.json"
        prepared_payload = copy.deepcopy(prepared)
        sim_options = prepared_payload.get("sim")
        if not isinstance(sim_options, dict):
            return {"status": "ERROR", "stage": "sim",
                    "reason": "NATIVE_PREPARED_SIM_OPTIONS_MISSING"}
        sim_options["iterations"] = int(iterations)
        sim_options["seed"] = int(seed)
        prepared_bytes = json.dumps(
            prepared_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        prepared_path.write_bytes(prepared_bytes)
        remaining = deadline - time.monotonic()
        if remaining <= 0.05:
            return {"status": "ERROR", "stage": "sim",
                    "reason": "NATIVE_CANDIDATE_SIM_DEADLINE_EXPIRED"}
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [
                    str(binary_path), "sim", "--infile", str(prepared_path),
                    "--outfile", str(report_path), "--gate",
                    "--rng-mode", rng_mode.value,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max(0.001, deadline - time.monotonic()),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "ERROR", "stage": "sim",
                    "reason": f"NATIVE_SIM_CLI_FAILED:{type(exc).__name__}:{exc}"}
        elapsed = round(time.monotonic() - started, 6)
        if completed.returncode != 0:
            refusal = _json_object(completed.stdout or "")
            # The selected Rust CLI reserves exit 3 for an explicit gate refusal.
            # A JSON object that merely contains "supported" is not enough:
            # malformed output, validation errors and faults must remain ERROR.
            if (
                completed.returncode == 3
                and refusal is not None
                and refusal.get("supported") is False
                and isinstance(refusal.get("reasons"), list)
                and bool(refusal["reasons"])
                and isinstance(refusal.get("refusals"), list)
                and bool(refusal["refusals"])
            ):
                return {
                    "status": "UNSUPPORTED",
                    "stage": "sim",
                    "reason": "NATIVE_PREPARED_GATE_REFUSED",
                    "coverage": refusal,
                    "elapsed_seconds": elapsed,
                }
            return {
                "status": "ERROR",
                "stage": "sim",
                "reason": "NATIVE_SIM_FAILED_WITHOUT_STRUCTURED_COVERAGE",
                "returncode": completed.returncode,
                "stdout_tail": (completed.stdout or "")[-700:],
                "stderr_tail": (completed.stderr or "")[-700:],
                "elapsed_seconds": elapsed,
            }
        if not report_path.is_file():
            return {"status": "ERROR", "stage": "sim",
                    "reason": "NATIVE_SIM_REPORT_MISSING",
                    "elapsed_seconds": elapsed}
        try:
            report_bytes = report_path.read_bytes()
            report = json.loads(report_bytes)
            result = report.get("result")
            iterations_done = (
                result.get("iterationsDone") if isinstance(result, dict) else None
            )
            if type(iterations_done) is not int or iterations_done != iterations:
                return {
                    "status": "ERROR",
                    "stage": "sim",
                    "reason": "NATIVE_SIM_ITERATION_COUNT_MISMATCH",
                    "iterations_done": iterations_done,
                    "expected_iterations": iterations,
                    "elapsed_seconds": elapsed,
                }
            score = float(_native_executor.dps(report))
        except (UnicodeDecodeError, ValueError, KeyError, TypeError, OverflowError) as exc:
            return {"status": "ERROR", "stage": "sim",
                    "reason": f"NATIVE_SIM_REPORT_INVALID:{type(exc).__name__}:{exc}",
                    "elapsed_seconds": elapsed}
        if not math.isfinite(score):
            return {"status": "ERROR", "stage": "sim",
                    "reason": "NATIVE_SIM_DPS_NONFINITE",
                    "elapsed_seconds": elapsed}
        return {
            "status": "EXECUTED",
            "stage": "sim",
            "dps": score,
            "iterations_done": iterations_done,
            "elapsed_seconds": elapsed,
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "prepared_input_sha256": hashlib.sha256(prepared_bytes).hexdigest(),
            "engine_identity": report.get("identity"),
        }
