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

OBJECTIVE_PATHS = {
    "DPS": ("result", "raidMetrics", "dps"),
    "HPS": ("result", "raidMetrics", "parties", 0, "players", 0, "hps"),
    "TPS": ("result", "raidMetrics", "parties", 0, "players", 0, "threat"),
}
OBJECTIVE_ACTION_FIELDS = {
    "DPS": ("damage",),
    "HPS": ("healing", "shielding"),
    "TPS": ("threat",),
}


def _objective_name(objective):
    name = str(objective).upper()
    if name not in OBJECTIVE_PATHS:
        raise ValueError(f"Unsupported native objective {objective!r}")
    return name


def objective_metric_path(objective):
    name = _objective_name(objective)
    path = ""
    for part in OBJECTIVE_PATHS[name]:
        path += f"[{part}]" if isinstance(part, int) else (
            ("." if path else "") + str(part)
        )
    return path + ".avg"


def objective_action_fields(objective):
    return OBJECTIVE_ACTION_FIELDS[_objective_name(objective)]


def _objective_metrics(out, objective):
    value = out
    for part in OBJECTIVE_PATHS[_objective_name(objective)]:
        value = value[part]
    return value


def objective_value(out, objective="DPS"):
    value = _objective_metrics(out, objective)["avg"]
    if isinstance(value, bool):
        raise TypeError("Native objective mean must be numeric, not boolean")
    return float(value)


def dps(out):
    return objective_value(out, "DPS")


def native_action_cast_receipts(out):
    """Preserve actual native first-player action IDs with positive paid casts.

    These are source-Rust combat receipts, not P4/P5 gate credit: the caller
    must still prove a completed native/world/2D screen and source matching.
    Keep the full native action identity (including tag/item IDs), so a proc
    cannot silently become a cast of a differently tagged source action.
    """
    try:
        actions = out["result"]["raidMetrics"]["parties"][0]["players"][0]["actions"]
    except (KeyError, IndexError, TypeError):
        return []
    if not isinstance(actions, list):
        return []
    receipts = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        identity = action.get("id")
        targets = action.get("targets")
        if not isinstance(identity, dict) or not isinstance(targets, list):
            continue
        casts = sum(
            target["casts"] for target in targets
            if isinstance(target, dict)
            and type(target.get("casts")) is int
            and target["casts"] > 0
        )
        if casts:
            receipts.append({"id": copy.deepcopy(identity), "casts": casts})
    return receipts


def _has_complete_distribution(out, iterations, objective="DPS"):
    """Check the requested native metric's complete iteration distribution."""
    try:
        metrics = _objective_metrics(out, objective)
        aggregator = metrics.get("aggregatorData")
        histogram = metrics.get("hist")
    except (KeyError, IndexError, TypeError, ValueError):
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
    """Backward-compatible DPS distribution check."""
    return _has_complete_distribution(out, iterations, "DPS")


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
    """Native completed with a full iteration distribution but no usable objective mean."""

    def __init__(self, cause, *, raw_response, elapsed_s, request_sha256,
                 objective="DPS"):
        super().__init__(
            "Native response has no usable " + objective_metric_path(objective)
            + ": " + str(cause),
            raw_response=raw_response, elapsed_s=elapsed_s,
            request_sha256=request_sha256,
        )
        self.objective = _objective_name(objective)


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


def run(binary, req, iterations, seed, rng_mode, deadline, objective="DPS", *, go_rules=False):
    objective = _objective_name(objective)
    objective_metric_path(objective)  # validate the requested output path before invoking native
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
        command = [str(binary), "sim", "--request", str(inp), "--outfile", str(out),
                   "--gate", "--rng-mode", rng_mode]
        if go_rules:
            command.append("--go-rules")
        res = subprocess.run(
            command,
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
        score = objective_value(output, objective)
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        if _has_complete_distribution(output, iterations, objective):
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
        if _has_complete_distribution(output, iterations, objective):
            raise NativeScoreExtractionError(
                objective_metric_path(objective) + " is non-finite",
                raw_response=output, elapsed_s=elapsed,
                request_sha256=request_sha, objective=objective,
            )
        _raise_execution_error(
            returncode=res.returncode, stdout=stdout,
            stderr=stderr or "Native objective mean is non-finite",
            raw_response=output, elapsed_s=elapsed,
            request_sha256=request_sha, output_exists=True,
        )
    return score, output, elapsed, request_sha
