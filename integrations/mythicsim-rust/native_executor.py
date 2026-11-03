"""Shared selected-MythicSim subprocess boundary; no game-rule knowledge."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import tempfile
import time
from pathlib import Path

from native_matrix import NativeCandidateRefusal, NativeUnscoredCandidate


def _request_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

_OBJECTIVE_PATHS = {
    "DPS": (("raidMetrics", "dps"), "result.raidMetrics.dps"),
    "TPS": (
        ("raidMetrics", "parties", 0, "players", 0, "threat"),
        "result.raidMetrics.parties[0].players[0].threat",
    ),
}


def _objective_path_label(objective):
    name = str(objective).upper()
    if name not in _OBJECTIVE_PATHS:
        raise ValueError("Unsupported native objective: " + name)
    return name, _OBJECTIVE_PATHS[name][1]


def _objective_metric_node(out, objective):
    name, _label = _objective_path_label(objective)
    node = out
    for part in ("result",) + _OBJECTIVE_PATHS[name][0]:
        node = node[part]
    if not isinstance(node, dict):
        raise TypeError("Native objective metric is not an object")
    return node


def objective_score(out, objective="DPS"):
    """Extract only the requested metric from the selected native response."""
    return float(_objective_metric_node(out, objective)["avg"])


def dps(out):
    return objective_score(out, "DPS")


def _has_complete_objective_distribution(out, iterations, objective):
    """Check the requested native metric's complete distribution without scoring it."""
    try:
        metrics = _objective_metric_node(out, objective)
        aggregator = metrics.get("aggregatorData")
        histogram = metrics.get("hist")
    except (KeyError, TypeError, ValueError):
        return False
    if not isinstance(aggregator, dict) or not isinstance(histogram, dict) or not histogram:
        return False
    count = aggregator.get("n")
    if isinstance(count, bool) or not isinstance(count, int) or count != iterations:
        return False
    bucket_counts = []
    for value in histogram.values():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
        bucket_counts.append(value)
    return sum(bucket_counts) == iterations


def _has_complete_dps_distribution(out, iterations):
    return _has_complete_objective_distribution(out, iterations, "DPS")


class NativeExecutionError(RuntimeError):
    """Native invocation failed for an execution/transport reason."""

    status = "ERROR"

    def __init__(self, message, *, raw_response, elapsed_s, request_sha256,
                 returncode, stdout, stderr):
        super().__init__(message)
        self.raw_response = raw_response
        self.elapsed_s = elapsed_s
        self.request_sha256 = request_sha256
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class NativeScoreExtractionError(NativeUnscoredCandidate):
    """Native completed a full distribution but returned no usable objective mean."""

    def __init__(self, cause, *, raw_response, elapsed_s, request_sha256,
                 objective="DPS"):
        _name, metric_path = _objective_path_label(objective)
        super().__init__(
            "Native response has no usable " + metric_path + ".avg: " + str(cause),
            raw_response=raw_response, elapsed_s=elapsed_s,
            request_sha256=request_sha256,
        )
        self.objective = _name


def _json_object(text):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _native_reason(raw, fallback):
    if isinstance(raw, dict):
        refusal = raw.get("refusal")
        if isinstance(refusal, dict):
            return str(refusal.get("reason") or refusal.get("code") or fallback)
        refusals = raw.get("refusals")
        if isinstance(refusals, list):
            reasons = [
                str(item.get("reason") or item.get("code"))
                for item in refusals if isinstance(item, dict)
            ]
            if reasons:
                return "; ".join(reasons)
        reasons = raw.get("reasons")
        if isinstance(reasons, list) and reasons:
            return "; ".join(str(item) for item in reasons)
        if raw.get("reason"):
            return str(raw["reason"])
    return str(fallback or "Native candidate refused")


def _raise_execution_error(*, returncode, stdout, stderr, raw_response,
                           elapsed_s, request_sha256, output_exists):
    raw = raw_response if raw_response is not None else {
        "returncode": returncode,
        "stdout": (stdout or "")[-700:],
        "stderr": (stderr or "")[-700:],
    }
    raise NativeExecutionError(
        "native Rust failed "
        f"(returncode={returncode}, output_exists={output_exists}): "
        f"stdout={(stdout or '')[-700:]!r}; "
        f"stderr={(stderr or '')[-700:]!r}",
        raw_response=raw,
        elapsed_s=elapsed_s,
        request_sha256=request_sha256,
        returncode=returncode,
        stdout=stdout or "",
        stderr=stderr or "",
    )


def _raise_structured_native_outcome(raw, *, returncode, stdout, stderr,
                                     elapsed_s, request_sha256):
    raw_status = raw.get("status")
    status = ""
    if "status" in raw:
        allowed_statuses = {"VALID", "INVALID", "UNSUPPORTED", "ERROR", "FAILED"}
        if not isinstance(raw_status, str) or raw_status.upper() not in allowed_statuses:
            _raise_execution_error(
                returncode=returncode, stdout=stdout,
                stderr=stderr or f"Unknown native status: {raw_status!r}",
                raw_response=raw, elapsed_s=elapsed_s,
                request_sha256=request_sha256, output_exists=True,
            )
        status = raw_status.upper()
    if status in {"INVALID", "UNSUPPORTED"}:
        raise NativeCandidateRefusal(
            status, raw_response=raw,
            reason=_native_reason(raw, status),
            returncode=returncode,
            request_sha256=request_sha256,
            elapsed_s=elapsed_s,
        )
    if raw.get("supported") is False:
        raise NativeCandidateRefusal(
            "UNSUPPORTED", raw_response=raw,
            reason=_native_reason(raw, "Native coverage gate refused the candidate"),
            returncode=returncode,
            request_sha256=request_sha256,
            elapsed_s=elapsed_s,
        )
    if raw.get("prepared") is False:
        refusal = raw.get("refusal")
        code = refusal.get("code") if isinstance(refusal, dict) else None
        if code in {"request", "talents"}:
            status = "INVALID"
        elif code == "prepare_fault":
            _raise_execution_error(
                returncode=returncode, stdout=stdout, stderr=stderr,
                raw_response=raw, elapsed_s=elapsed_s,
                request_sha256=request_sha256, output_exists=True,
            )
        elif isinstance(refusal, dict):
            status = "UNSUPPORTED"
        else:
            _raise_execution_error(
                returncode=returncode, stdout=stdout, stderr=stderr,
                raw_response=raw, elapsed_s=elapsed_s,
                request_sha256=request_sha256, output_exists=True,
            )
        raise NativeCandidateRefusal(
            status, raw_response=raw,
            reason=_native_reason(raw, status),
            returncode=returncode,
            request_sha256=request_sha256,
            elapsed_s=elapsed_s,
        )
    if status in {"ERROR", "FAILED"}:
        _raise_execution_error(
            returncode=returncode, stdout=stdout, stderr=stderr,
            raw_response=raw, elapsed_s=elapsed_s,
            request_sha256=request_sha256, output_exists=True,
        )


def run(binary, req, iterations, seed, rng_mode, deadline, objective="DPS"):
    objective, _metric_path = _objective_path_label(objective)
    remaining = deadline - time.monotonic()
    if remaining <= 0.05:
        raise TimeoutError("No remaining time before native execution")
    payload = copy.deepcopy(req)
    payload["simOptions"]["iterations"] = iterations
    payload["simOptions"]["randomSeed"] = str(seed)
    request_sha = _request_sha(payload)
    with tempfile.TemporaryDirectory() as directory:
        inp = Path(directory) / "req.json"
        out = Path(directory) / "out.json"
        inp.write_text(json.dumps(payload, separators=(",", ":")))
        started = time.monotonic()
        res = subprocess.run(
            [str(binary), "sim", "--request", str(inp), "--outfile", str(out),
             "--gate", "--rng-mode", rng_mode],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=max(0.001, deadline - time.monotonic()),
        )
        elapsed = round(time.monotonic() - started, 6)
        stdout = res.stdout or ""
        stderr = res.stderr or ""
        output_text = out.read_text() if out.exists() else ""
        raw = _json_object(stdout) or _json_object(output_text)

        # These are the pinned MythicSim CLI's documented exit outcomes:
        # 3 = unsupported coverage, 4 = invalid prepared request,
        # 5 = request preparation refusal/fault.
        if res.returncode == 3:
            raise NativeCandidateRefusal(
                "UNSUPPORTED", raw_response=raw or {
                    "returncode": res.returncode, "stdout": stdout, "stderr": stderr,
                },
                reason=_native_reason(raw, stderr or stdout or "Native coverage refused candidate"),
                returncode=res.returncode, request_sha256=request_sha,
                elapsed_s=elapsed,
            )
        if res.returncode == 4:
            raise NativeCandidateRefusal(
                "INVALID", raw_response=raw or {
                    "returncode": res.returncode, "stdout": stdout, "stderr": stderr,
                },
                reason=stderr or stdout or "Native rejected the prepared request",
                returncode=res.returncode, request_sha256=request_sha,
                elapsed_s=elapsed,
            )
        if res.returncode == 5:
            if raw is not None and isinstance(raw.get("refusal"), dict):
                _raise_structured_native_outcome(
                    raw, returncode=res.returncode, stdout=stdout, stderr=stderr,
                    elapsed_s=elapsed, request_sha256=request_sha,
                )
            _raise_execution_error(
                returncode=res.returncode, stdout=stdout, stderr=stderr,
                raw_response=raw, elapsed_s=elapsed,
                request_sha256=request_sha, output_exists=out.exists(),
            )
        if res.returncode != 0 or not out.exists():
            _raise_execution_error(
                returncode=res.returncode, stdout=stdout, stderr=stderr,
                raw_response=raw, elapsed_s=elapsed,
                request_sha256=request_sha, output_exists=out.exists(),
            )
        try:
            output = json.loads(output_text)
        except (TypeError, ValueError) as exc:
            _raise_execution_error(
                returncode=res.returncode, stdout=stdout,
                stderr=stderr or str(exc), raw_response=output_text,
                elapsed_s=elapsed, request_sha256=request_sha,
                output_exists=out.exists(),
            )
        if not isinstance(output, dict):
            _raise_execution_error(
                returncode=res.returncode, stdout=stdout, stderr=stderr,
                raw_response=output, elapsed_s=elapsed,
                request_sha256=request_sha, output_exists=out.exists(),
            )
        _raise_structured_native_outcome(
            output, returncode=res.returncode, stdout=stdout, stderr=stderr,
            elapsed_s=elapsed, request_sha256=request_sha,
        )

    try:
        score = objective_score(output, objective)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        if _has_complete_objective_distribution(output, iterations, objective):
            raise NativeScoreExtractionError(
                exc, raw_response=output, elapsed_s=elapsed,
                request_sha256=request_sha, objective=objective,
            ) from exc
        _raise_execution_error(
            returncode=res.returncode, stdout=stdout,
            stderr=stderr or str(exc), raw_response=output,
            elapsed_s=elapsed, request_sha256=request_sha,
            output_exists=True,
        )
    if not math.isfinite(score):
        if _has_complete_objective_distribution(output, iterations, objective):
            raise NativeScoreExtractionError(
                _objective_path_label(objective)[1] + ".avg is non-finite",
                raw_response=output, elapsed_s=elapsed,
                request_sha256=request_sha, objective=objective,
            )
        _raise_execution_error(
            returncode=res.returncode, stdout=stdout,
            stderr=stderr or f"Native {objective} mean is non-finite", raw_response=output,
            elapsed_s=elapsed, request_sha256=request_sha,
            output_exists=True,
        )
    return score, output, elapsed, request_sha
