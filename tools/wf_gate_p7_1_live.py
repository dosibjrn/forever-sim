"""P7.1 pinned reference: one selected-Rust 1,000-fight stochastic sample.

The actual saved report request recovered by WF648 is immutable source
provenance. The stationary benchmark uses MythicSim's real native scorer;
P7-only 2D/world coupling and duplicate stochastic runs are retired.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from tools.wf_gate_coverage import (P7_FINAL_STOCHASTIC_ITERATIONS,
                                    p7_required_dps,
                                    p7_final_stochastic_mean_passes)

# Historical WF633 engine identity: preserve its provenance after fork updates.
PINNED_RUST = "666fe17a42682068a3c8497d88d5fa3732cbdfb9"
SAVED_BALANCE_RAW_SHA = "e99b06e5aa891a941ac077643a4209ab8582c810b678df4ec2d47ac48c6c646a"
# Exact original 10,000-fight Feral Cat saved request (811.023726 DPS).
SAVED_FERAL_RAW_SHA = "dc8b0e7f5c3315e7f5c1b5dd85946c25b3137bafdd0730f93adb1b6c2e44745f"
FERAL_REFERENCE_DPS = 811.0237260012982
FERAL_REPORT_URL = "https://api.mythicsim.com/api/forever/ranking-sims/f2176db2-8217-47d2-8d3c-c9260d8ccb73/report"


def _selected_rust_submodule(root: Path, upstream: Path) -> str | None:
    """Require the running Rust checkout to match this parent HEAD's gitlink.

    Saved-reference engine revision is historical provenance, not the current
    executable pin. Never select a floating fork branch for a gate run.
    """
    path = "integrations/mythicsim-rust/engine"
    try:
        pin = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "HEAD", "--", path],
            capture_output=True, text=True, check=False)
        if pin.returncode:
            return None
        record = pin.stdout.strip().split()
        if (len(record) != 4 or record[:2] != ["160000", "commit"]
                or record[3] != path or len(record[2]) != 40
                or any(ch not in "0123456789abcdef" for ch in record[2])):
            return None
        actual = subprocess.run(
            ["git", "-C", str(upstream), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return record[2] if actual.returncode == 0 and actual.stdout.strip() == record[2] else None


def _executed_p7_runtime_proof(gate: str, frozen_source_sha256: str, *,
                               engine_revision: str = PINNED_RUST) -> dict:
    """Stamp only an already executed and accepted native/world final.

    The caller reaches this helper after the real pinned Rust + 2D world
    parity and frozen 1000-stochastic DPS predicates succeed. This metadata
    is not a substitute for those production measurements.
    """
    return {"runtime_proof": {
        "executed": True,
        "engine_revision": engine_revision,
        "source_revision": frozen_source_sha256,
        "run_id": f"{gate}-rust-gsim2d-{uuid4()}",
    }}


def _blocked(reason: str, **details) -> dict:
    return {"status": "BLOCKED", "reasons": [reason], **details}



def _source_native_world_parity(
        native: dict | None, live: dict, iterations: int, *,
        expected_raw_sha: str | None = None,
        allow_world_lethal: bool = False) -> str | None:
    """Fail closed on source identity and every ACK-scored world fight.

    A finite source target can die in the live 2D world. Its lethal ACK stops
    the coupled native fight, while a standalone source-only control has no
    world HP feedback and continues the encounter. Those aggregate scores are
    not comparable after a lethal world fight. P7.4 may opt into that narrowly
    scoped case, but still requires the coupled native DPS to equal the full
    per-fight gsim damage/duration ledger. P7.1 remains strict by default.
    """
    samples = live.get("per_iteration")
    if (live.get("iterations_done") != iterations
            or (native is not None and native.get("iterations") != iterations)
            or not isinstance(samples, list) or len(samples) != iterations
            or live.get("native_damage_events", 0) <= 0
            or live.get("native_world_ticks", 0) < iterations):
        return "P7_1_NATIVE_WORLD_EXECUTION_INCOMPLETE"
    if expected_raw_sha is not None and (
            live.get("source_request_raw_sha256") != expected_raw_sha):
        return "P7_1_LIVE_SOURCE_REQUEST_IDENTITY_DIVERGED"

    target_lethal = []
    try:
        for row in samples:
            health_keys = (
                "world_target_health_remaining",
                "world_target_max_health",
                "world_target_lethal",
            )
            present = [key in row for key in health_keys]
            if any(present) and not all(present):
                return "P7_1_WORLD_TARGET_HEALTH_LEDGER_INCOMPLETE"
            if not any(present):
                target_lethal.append(False)
                continue
            health = row["world_target_health_remaining"]
            maximum = row["world_target_max_health"]
            lethal = row["world_target_lethal"]
            if (type(health) not in (int, float)
                    or not math.isfinite(health) or health < 0
                    or type(maximum) not in (int, float)
                    or not math.isfinite(maximum) or maximum <= 0
                    or health > maximum + 1e-6
                    or type(lethal) is not bool
                    or lethal != (health <= 0.0)):
                return "P7_1_WORLD_TARGET_HEALTH_LEDGER_INVALID"
            target_lethal.append(lethal)
    except (KeyError, TypeError, ValueError, OverflowError):
        return "P7_1_WORLD_TARGET_HEALTH_LEDGER_INCOMPLETE"
    world_lethal = any(target_lethal)
    lethal_comparison_allowed = allow_world_lethal and world_lethal

    # NaN makes ordinary abs(actual - expected) >= tolerance comparisons
    # false. Reject nonnumeric/nonfinite coupled native and 2D scores BEFORE
    # parity, even when a standalone native-only control is not comparable.
    try:
        live_scores = (live["native_dps"], live["world_mean_dps"])
        if any(type(value) not in (int, float)
               or not math.isfinite(value) or value < 0
               for value in live_scores):
            return "P7_1_NATIVE_WORLD_DPS_INVALID"
        live_duration = live["sampled_duration_s"]
        if (type(live_duration) not in (int, float)
                or not math.isfinite(live_duration) or live_duration <= 0):
            return "P7_1_NATIVE_WORLD_DURATION_INVALID"
        if native is not None:
            native_score = native["native_dps"]
            native_duration = native["first_duration_s"]
            if (type(native_score) not in (int, float)
                    or not math.isfinite(native_score) or native_score < 0):
                return "P7_1_NATIVE_WORLD_DPS_INVALID"
            if (type(native_duration) not in (int, float)
                    or not math.isfinite(native_duration) or native_duration <= 0):
                return "P7_1_NATIVE_WORLD_DURATION_INVALID"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "P7_1_NATIVE_WORLD_SCALARS_MISSING"

    try:
        if any(
                type(row["iteration_index"]) is not int
                or row["iteration_index"] != i
                or type(row["duration_s"]) not in (int, float)
                or not math.isfinite(row["duration_s"])
                or row["duration_s"] <= 0
                or type(row["world_dps"]) not in (int, float)
                or not math.isfinite(row["world_dps"])
                or row["world_dps"] < 0
                or type(row["world_applied_damage"]) not in (int, float)
                or not math.isfinite(row["world_applied_damage"])
                or row["world_applied_damage"] < 0
                for i, row in enumerate(samples)):
            return "P7_1_WORLD_FIGHT_LEDGER_INCOMPLETE"
        independent_world_mean = math.fsum(
            row["world_dps"] for row in samples) / iterations
        if abs(independent_world_mean - live["world_mean_dps"]) >= 1e-5:
            return "P7_1_WORLD_FIGHT_MEAN_DIVERGED"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "P7_1_WORLD_FIGHT_LEDGER_INCOMPLETE"

    # The coupled native result must always equal the gsim-applied world
    # score. This is the actual source-native↔2D parity assertion.
    if abs(live["native_dps"] - live["world_mean_dps"]) >= 1e-5:
        return "P7_1_NATIVE_LIVE_WORLD_DPS_PARITY_FAILED"
    # The sample ledger's first duration must always agree with the native
    # world-bridged result, including when that first fight ends by lethal ACK.
    if abs(samples[0]["duration_s"] - live_duration) >= 1e-9:
        return "P7_1_NATIVE_WORLD_FIRST_DURATION_DIVERGED"
    # A standalone source-only first fight remains comparable if the first
    # world target survived. If it died, its shorter coupled duration is valid.
    if (native is not None
            and not (lethal_comparison_allowed and target_lethal[0])
            and abs(native["first_duration_s"] - live_duration) >= 1e-9):
        return "P7_1_NATIVE_WORLD_FIRST_DURATION_DIVERGED"
    if native is None and not lethal_comparison_allowed:
        return "P7_1_NATIVE_SOURCE_CONTROL_MISSING"
    if native is not None and not lethal_comparison_allowed:
        if (abs(native["native_dps"] - live["native_dps"]) >= 1e-6
                or abs(native["native_dps"] - live["world_mean_dps"]) >= 1e-5):
            return "P7_1_NATIVE_LIVE_SAVED_DPS_PARITY_FAILED"

    try:
        # Real live_world_probe records actual gsim-applied native damage
        # (including any negative-time/pre-pull damage) and scores only the
        # in-fight portion. Equal reported DPS is not a causal world receipt
        # when the independently applied damage ledger disagrees.
        if any(
                not math.isfinite(row.get("world_applied_precombat_damage", 0.0))
                or row.get("world_applied_precombat_damage", 0.0) < 0
                or row.get("world_applied_precombat_damage", 0.0)
                > row["world_applied_damage"] + 1e-4
                for row in samples):
            return "P7_1_WORLD_FIGHT_LEDGER_INCOMPLETE"
        if any(
                not math.isclose(
                    row["world_applied_damage"]
                    - row.get("world_applied_precombat_damage", 0.0),
                    row["world_dps"] * row["duration_s"],
                    rel_tol=1e-9, abs_tol=1e-4)
                for row in samples):
            return "P7_1_WORLD_FIGHT_DAMAGE_DIVERGED"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "P7_1_WORLD_FIGHT_LEDGER_INCOMPLETE"
    return None


def run_live(root: Path, class_key: str, level: int, *, spec: str = "unrestricted") -> dict:
    if ((class_key, level) != ("druid", 60)
            or spec not in ("balance", "unrestricted", "feral")):
        return _blocked("P7_1_SAVED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT")

    feral = spec == "feral"
    request = root / (
        "docs/evidence/druid-l60-feral/p7.1/saved_811_request.json" if feral
        else "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json")
    witness = root / "docs/evidence/wf633/WF633_VALIDATION.json"
    if not request.is_file() or (not feral and not witness.is_file()):
        return _blocked("P7_1_PINNED_SOURCE_REQUEST_OR_REFERENCE_MISSING")
    raw = request.read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    if raw_sha != (SAVED_FERAL_RAW_SHA if feral else SAVED_BALANCE_RAW_SHA):
        return _blocked("P7_1_SAVED_REQUEST_CHANGED", actual_sha256=raw_sha)
    source = json.loads(raw)
    # The authentic Feral request and report are saved directly, without a
    # WF633 validation sidecar. Do not borrow Balance's score or engine claim.
    meta = ({"reference_dps": FERAL_REFERENCE_DPS} if feral
            else json.loads(witness.read_text()))
    player = source["raid"]["parties"][0]["players"][0]
    target = source["encounter"]["targets"]
    source_iterations = source["simOptions"]["iterations"]
    if ((not feral and meta["engine_revision"] != PINNED_RUST)
            or player.get("class") != "ClassDruid"
            or ("feralCatDruid" if feral else "balanceDruid") not in player
            or len(target) != 1 or target[0]["level"] != 63):
        return _blocked("P7_1_SAVED_REFERENCE_SCENARIO_MISMATCH")
    # Preserve the original report's 10k iteration field as pinned provenance;
    # the user-approved final validation itself uses only 1000 stochastic
    # samples. No universal 10k-simulation acceptance criterion.
    iterations = P7_FINAL_STOCHASTIC_ITERATIONS
    # A brief source-backed runtime diagnostic must not silently replace the
    # approved 1000-fight stochastic verification. Default always remains
    # the 1000-fight production run, independent of the old saved source's
    # original 10000-iteration setting.
    requested = os.environ.get("FOREVER_P7_LIVE_PROBE_ITERATIONS")
    if requested is None:
        run_iterations = iterations
    else:
        try:
            run_iterations = int(requested)
        except ValueError:
            return _blocked("P7_1_INVALID_LIVE_PROBE_ITERATIONS", requested=requested)
        if not 1 <= run_iterations <= iterations:
            return _blocked("P7_1_INVALID_LIVE_PROBE_ITERATIONS", requested=requested)
    full_validation = run_iterations == iterations

    # Refuse arbitrary executables: only the exact fork gitlink checked into
    # this parent HEAD can run. The historical reference stays separately pinned.
    binary = Path(os.environ.get("FOREVER_MYTHICSIM_RUST_BIN", str(
        root.parent / "upstream/target/release/forever-engine"))).resolve()
    if not binary.is_file():
        return _blocked("P7_1_PINNED_RUST_BINARY_MISSING", binary=str(binary))
    upstream = binary.parents[2]
    selected_rust = _selected_rust_submodule(root, upstream)
    if selected_rust is None:
        return _blocked("P7_1_RUST_SOURCE_REVISION_NOT_PINNED")
    # P7 is a stationary native benchmark. Run the original Feral reference
    # for Feral, or the existing Balance reference for Balance/unrestricted;
    # no 2D world handshake or duplicate replay is required.
    path = root / "integrations/mythicsim-rust/live_world_probe.py"
    module_spec = importlib.util.spec_from_file_location("forever_p71_native", path)
    if module_spec is None or module_spec.loader is None:
        return _blocked("P7_1_PRODUCTION_NATIVE_MODULE_MISSING")
    module = importlib.util.module_from_spec(module_spec)
    try:
        module_spec.loader.exec_module(module)
        native = module.native_source_control(
            binary, request, run_iterations, rng_mode="stochastic")
    except (AssertionError, KeyError, TypeError, ValueError, OSError,
            RuntimeError, subprocess.SubprocessError) as exc:
        return {"status": "FAIL",
                "reasons": ["P7_1_NATIVE_STOCHASTIC_EXECUTION_FAILED"],
                "native_execution_error": type(exc).__name__ + ":" + str(exc)[:240],
                "native_source_revision": selected_rust}

    score = native.get("native_dps") if isinstance(native, dict) else None
    if (not isinstance(native, dict)
            or type(native.get("iterations")) is not int
            or native["iterations"] != run_iterations
            or type(score) not in (int, float)
            or not math.isfinite(score) or score < 0):
        return {"status": "FAIL",
                "reasons": ["P7_1_NATIVE_STOCHASTIC_RESULT_INVALID"],
                "native_source_revision": selected_rust,
                "native_iterations": native.get("iterations") if isinstance(native, dict) else None}
    reference = float(meta["reference_dps"])
    actual = {
        "production_engine": "pinned_mythicsim_rust_native",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py:native_source_control",
        "native_dps": float(score),
        "native_source_revision": selected_rust,
        "source_request_raw_sha256": raw_sha,
        "saved_reference_dps": reference,
        "required_dps": p7_required_dps("P7.1", reference),
        "source_report_url": (FERAL_REPORT_URL if feral else
                              "https://api.mythicsim.com/api/forever/ranking-sims/d9d85974-a1f7-4700-ab22-2335d767a944/report"),
        "reference_configuration_source": ("original_saved_feral_report_request" if feral
                                           else "WF648_original_saved_report_request"),
        "reference_profile": "feral" if feral else "balance",
        "checkpoint_spec": spec,
        "iterations": run_iterations,
        "sampled_source_fights": run_iterations,
        "saved_source_iterations": source_iterations,
        "source_original_iterations": source_iterations,
        "stochastic_rng": True,
        "selected_validation": (
            "1000_native_stochastic_fights" if full_validation
            else "bounded_native_stochastic_diagnostic"),
    }
    if not full_validation:
        return {"status": "FAIL",
                "reasons": ["P7_1_BOUNDED_DIAGNOSTIC_NOT_FULL_SAVED_REFERENCE"],
                **actual}
    if not p7_final_stochastic_mean_passes(
            "P7.1", score, reference, iterations=iterations, stochastic=True):
        return {"status": "FAIL",
                "reasons": ["P7_1_DPS_BELOW_APPROVED_99_PERCENT_FLOOR"],
                **actual}
    return {
        "status": "PASS", "reasons": [],
        "p7_1_1_reference_pinned": True,
        "p7_1_2_native_reproduced": True,
        "runtime_proof": {
            "executed": True,
            "engine_revision": selected_rust,
            "source_revision": raw_sha,
            "run_id": "P7.1-native-" + str(uuid4()),
        },
        **actual,
    }
