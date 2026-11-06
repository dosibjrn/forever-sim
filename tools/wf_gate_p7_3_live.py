"""P7.3: pay a changed talent allocation on the selected native scorer.

Gear and APL remain frozen on an authenticated source request. Rust alone
judges the proposed talent-string allocation. A real changed candidate with
three balanced native evaluations and finite DPS satisfies PROCESS v2.22;
2D, 300-second cold search, and stochastic holdout are not P7.3 gates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import tempfile
import time
from uuid import uuid4

from src.engine_client import native_talent_proposals

from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                     SAVED_FERAL_RAW_SHA)
from tools.wf_gate_p7_2_live import (_source_module, _pinned_source_runtime)


def _cold_talents(base: dict, rng: random.Random, proposals, *, reference_parent=False):
    """Propose an independently drawn or source-neighbor talent string.

    The saved request supplies the proposal shape; only Rust decides whether
    the resulting ranks are legal. Gear and APL stay fixed.
    """
    candidate = copy.deepcopy(base)
    old = base["raid"]["parties"][0]["players"][0]
    player = candidate["raid"]["parties"][0]["players"][0]
    if reference_parent:
        selected = proposals.mutate_talent_string(old["talentsString"], rng)
    else:
        selected = proposals.cold_talent_string(old["talentsString"], rng)
    if not isinstance(selected, str) or not selected:
        raise ValueError("P73_NATIVE_TALENT_PROPOSAL_NOT_STRING")
    player["talentsString"] = selected
    if (player["equipment"] != old["equipment"]
            or player["rotation"] != old["rotation"]):
        raise ValueError("TALENT_ONLY_COLD_SEARCH_CHANGED_FIXED_DIMENSIONS")
    return candidate


def _native_refusal(exc: Exception) -> tuple[str, str]:
    """Forward the structured Rust preparation refusal instead of calling it an engine error.

    The scorer's nonzero CLI return embeds Rust's JSON refusal in the
    RuntimeError's `output=` tail. Its talent rejection is authoritative.
    Unrecognized native output remains an execution error.
    """
    status = str(getattr(exc, "status", "")).upper()
    reason = str(getattr(exc, "reason", exc))
    if status in ("INVALID", "UNSUPPORTED", "UNSCORED"):
        return status, reason
    # The selected source adapter raises NativeSourceRefusal with .code and
    # .reason, not a JSON string. Forward those Rust-owned refusals directly.
    code = str(getattr(exc, "code", "")).lower()
    if code in ("talents", "gear", "apl"):
        return "INVALID", "NATIVE_" + code.upper() + ":" + reason
    if code == "unsupported":
        return "UNSUPPORTED", "NATIVE_UNSUPPORTED:" + reason
    if code == "unscored":
        return "UNSCORED", "NATIVE_UNSCORED:" + reason
    if " output=" in reason:
        try:
            decoded = json.loads(reason.rsplit(" output=", 1)[1])
            refusal = decoded.get("refusal") if isinstance(decoded, dict) else None
            if isinstance(refusal, dict):
                code = refusal.get("code")
                message = str(refusal.get("reason", ""))[:400]
                if code == "talents":
                    return "INVALID", "NATIVE_TALENTS:" + message
                if code == "gear":
                    return "INVALID", "NATIVE_GEAR:" + message
                if code == "unsupported":
                    return "UNSUPPORTED", "NATIVE_UNSUPPORTED:" + message
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return "ERROR", reason


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(
        root, class_key, level, spec, "P7.3", require_world=False)
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    production = _source_module(
        root / "integrations/mythicsim-rust/live_world_probe.py",
        "p73_selected_native_scorer")
    original = base["raid"]["parties"][0]["players"][0]["talentsString"]
    # Probe native with minimal source-reference deltas before spending time on
    # large mutations. This changes serialized ranks only; no Python game
    # legality or source-specific tree ordering is inferred.
    minimal = native_talent_proposals.lower_one_rank_neighbors(original)
    # Keep the source point budget intact when simple rank removals are not
    # accepted. These are proposals only; native Rust validates every one.
    transfer_proposals = getattr(
        native_talent_proposals, "one_point_transfer_neighbors", None)
    transfers = (transfer_proposals(original) if transfer_proposals else [])
    rng = random.Random(647003)
    seen = set()
    failures = []
    refusal_samples = []
    invalid = unsupported = unscored = errors = executed = proposals = 0
    best = None
    start = time.monotonic()
    # P7.3 is a changed-talent axis smoke, never a 300s joint search.
    while proposals < len(minimal) + len(transfers) + 8:
        proposals += 1
        try:
            if proposals <= len(minimal):
                candidate = copy.deepcopy(base)
                candidate["raid"]["parties"][0]["players"][0][
                    "talentsString"] = minimal[proposals - 1]
            elif proposals <= len(minimal) + len(transfers):
                candidate = copy.deepcopy(base)
                candidate["raid"]["parties"][0]["players"][0][
                    "talentsString"] = transfers[proposals - len(minimal) - 1]
            else:
                candidate = _cold_talents(
                    base, rng, native_talent_proposals,
                    reference_parent=(
                        proposals <= len(minimal) + len(transfers) + 4))
            player = candidate["raid"]["parties"][0]["players"][0]
            # A no-op is not an independently changed talent candidate.
            if player["talentsString"] == original:
                continue
            sha = hashlib.sha256(json.dumps(
                candidate, sort_keys=True).encode()).hexdigest()
            if sha in seen:
                continue
            seen.add(sha)
            with tempfile.TemporaryDirectory(prefix="forever_p73_native_") as tmp:
                path = Path(tmp) / "changed-talents.json"
                path.write_text(json.dumps(candidate))
                try:
                    native_options = {"go_rules": True} if spec == "feral" else {}
                    native = production.native_source_control(
                        binary, path, 3, rng_mode="balanced", **native_options)
                except Exception as exc:
                    status, reason = _native_refusal(exc)
                    sample = status + ":" + reason[:400]
                    if status == "INVALID":
                        invalid += 1
                        refusal_samples.append(sample)
                    elif status == "UNSUPPORTED":
                        unsupported += 1
                        refusal_samples.append(sample)
                    elif status == "UNSCORED":
                        unscored += 1
                        refusal_samples.append(sample)
                    else:
                        errors += 1
                        failures.append("NATIVE_EXECUTION_ERROR:" + sample)
                    continue  # Native refusals are authoritative.
            if type(native.get("iterations")) is not int or native["iterations"] != 3:
                raise ValueError("P7_3_NATIVE_PAID_ITERATIONS_INCOMPLETE")
            score = native.get("native_dps")
            if (type(score) not in (int, float)
                    or not math.isfinite(score) or score < 0):
                raise ValueError("P7_3_NATIVE_PAID_DPS_INVALID")
            executed += 1
            score = float(score)
            if best is None or score > best[0]:
                best = (score, sha, candidate)
            break  # First real, changed native-paid talent is sufficient.
        except (ValueError, RuntimeError, OSError, KeyError, TypeError,
                AssertionError, subprocess.SubprocessError) as exc:
            errors += 1
            failures.append(type(exc).__name__ + ":" + str(exc)[:180])

    elapsed = time.monotonic() - start
    shared = {
        "production_engine": "pinned_mythicsim_rust_native",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py:native_source_control",
        "native_source_revision": meta.get("selected_engine_revision", PINNED_RUST),
        "source_request_raw_sha256": meta.get(
            "source_request_raw_sha256",
            SAVED_FERAL_RAW_SHA if spec == "feral" else SAVED_BALANCE_RAW_SHA),
        "native_rules": "go_reference" if spec == "feral" else "forever",
        "saved_reference_dps": float(meta["reference_dps"]),
        "reference_profile": meta.get("selected_reference_profile", "balance"),
        "checkpoint_spec": spec,
        "source_original_talents": original,
        "fixed_rotation_and_gear": True,
        "source_legal_cold_candidates_paid": executed,
        "minimal_reference_delta_proposals": len(minimal),
        "point_preserving_delta_proposals": len(transfers),
        "cold_unique_source_requests": len(seen),
        "native_invalid_candidates": invalid,
        "native_unsupported_candidates": unsupported,
        "native_unscored_candidates": unscored,
        "native_execution_errors": errors,
        "native_refusal_samples": refusal_samples[:4],
        "cold_candidate_failures": failures[:4],
        "search_wall_s": elapsed,
        "independent_300s_search_requested": False,
        "independent_300s_search_completed": False,
        "search_rng_mode": "balanced",
        "selected_validation": "3_native_balanced_fights_per_distinct_talents",
    }
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_3_NO_NATIVE_PAID_CHANGED_TALENT_CANDIDATE"],
                **shared}
    score, sha, winner = best
    return {
        "status": "PASS", "reasons": [],
        "runtime_proof": {
            "executed": True,
            "engine_revision": meta.get("selected_engine_revision", PINNED_RUST),
            "source_revision": sha,
            "run_id": "P7.3-native-" + str(uuid4()),
        },
        "cold_winner_request_sha256": sha,
        "cold_winner_talents": winner["raid"]["parties"][0]["players"][0][
            "talentsString"],
        "winner_native_dps": score,
        **shared,
    }
