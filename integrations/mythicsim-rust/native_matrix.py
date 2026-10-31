"""Pure class-neutral native search contract for the L60 Rust matrix.

This module deliberately knows nothing about WoW classes, equipment slots, talent
encodings, DPS or subprocesses. Only a production adapter can construct legal
candidates and invoke the pinned MythicSim Rust evaluator. Test callbacks are
not evidence of a native run.
"""
from __future__ import annotations

import copy
import json
import math
import random
import subprocess
import time
from typing import Any, Callable


def enumerate_l60_profiles(registry: dict, *, include_unrestricted: bool = False) -> list[tuple[str, str]]:
    """Follow the canonical checkpoint registry order; no hardcoded class list."""
    rows = [
        (class_key, spec)
        for class_key in registry["class_order"]
        for spec in registry["spec_profiles"][class_key]
    ]
    if len(rows) != len(set(rows)):
        raise ValueError("Duplicate fixed class/spec registry entry")
    if include_unrestricted:
        rows.extend((class_key, "unrestricted") for class_key in registry["class_order"])
        if len(rows) != len(set(rows)):
            raise ValueError("Duplicate unrestricted class/spec registry entry")
    return rows


def next_budget(current: int, result: dict) -> int | None:
    """Promote on actual successful legal evaluations, never on improvement."""
    if (
        result.get("status") != "RAN"
        or int(result.get("paid_candidates", 0)) < 1
        or int(result.get("engine_errors", 0)) != 0
    ):
        return None
    return {5: 30, 30: 300}.get(current)


def _identity(candidate: Any) -> str:
    # Structural identity, not a signature of any particular class or slot count.
    return json.dumps(candidate, sort_keys=True, separators=(",", ":"), default=str)


def search_native(
    *,
    profile_id: str,
    reference: dict | None,
    propose: Callable,
    mutate: Callable,
    legal: Callable,
    evaluate: Callable,
    seconds: float,
    iterations: int,
    seed: int,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Run budgeted screening with one injected evaluator.

    propose(rng) generates the FIRST candidate *cold*. mutate(elite,rng) may
    subsequently exploit evaluated candidates. Neither path is supplied the
    reference by this search core. Keeping it as an explicit input is useful
    for availability / immutability checks, but does not grant seed privilege.

    This pure screening step is not a stochastic holdout or a PROCESS gate.
    The production wrapper owns native request validation, measurement,
    balanced RNG, independent stochastic rerank and evidence persistence.
    """
    result = {
        "profile_id": profile_id,
        "status": "BLOCKED_NO_PAID_NATIVE_EVAL",
        "paid_candidates": 0,
        "best_candidate": None,
        "best_score": None,
        "elapsed_s": 0.0,
        "engine_errors": 0,
        "legal_rejections": 0,
        "duplicate_proposals": 0,
    }
    if reference is None:
        result["status"] = "BLOCKED_REFERENCE_MISSING"
        return result
    if not math.isfinite(seconds) or seconds <= 0 or iterations < 1:
        result["status"] = "BLOCKED_BUDGET_TOO_SMALL"
        return result

    rng = random.Random(seed)
    start = clock()
    deadline = start + seconds
    seen: set[str] = set()
    best = None
    # Clock injection is deterministic in unit tests. Production monotonic
    # deadline is inspected before every native evaluator call.
    while clock() < deadline:
        try:
            raw = propose(rng) if best is None else (
                mutate(copy.deepcopy(best), rng) if rng.random() < 0.85 else propose(rng)
            )
            candidate = copy.deepcopy(raw)
            key = _identity(candidate)
            if key in seen:
                result["duplicate_proposals"] += 1
                continue
            seen.add(key)
            if not legal(candidate):
                result["legal_rejections"] += 1
                continue
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            result["legal_rejections"] += 1
            continue

        if clock() >= deadline:
            break
        try:
            value = evaluate(
                copy.deepcopy(candidate), iterations=iterations, seed=seed,
                rng_mode="balanced"
            )
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("Non-finite native score")
        except (TimeoutError, subprocess.TimeoutExpired):
            # Reaching a strict native deadline is normal budget exhaustion,
            # not a source/engine error and not a failed paid evaluation.
            break
        except Exception:
            result["engine_errors"] += 1
            continue
        result["paid_candidates"] += 1
        if result["best_score"] is None or value > result["best_score"]:
            result["best_score"] = value
            result["best_candidate"] = copy.deepcopy(candidate)
            best = copy.deepcopy(candidate)

    result["elapsed_s"] = max(0.0, clock() - start)
    if result["paid_candidates"]:
        result["status"] = "RAN" if not result["engine_errors"] else "RAN_WITH_ENGINE_ERRORS"
    elif result["engine_errors"]:
        result["status"] = "BLOCKED_ENGINE_ERROR"
    elif result["legal_rejections"]:
        result["status"] = "BLOCKED_NO_LEGAL_CANDIDATE"
    return result
