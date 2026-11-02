"""On-demand P7.1 entry into the existing pinned MythicSim Rust/gsim 2D path.

No new engine or score implementation: live_world_probe runs the native
baseline and genuine world-ACKed fight. A bounded source-fight sample
measures coupled DPS but does not measure the fraction of functioning
gate assertions. The exact original saved report request was recovered
by WF648; a duplicate Settings UI capture is not mandatory.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess

from tools.wf_gate_coverage import (P7_FINAL_STOCHASTIC_ITERATIONS,
                                    p7_required_dps,
                                    p7_final_stochastic_mean_passes)

PINNED_RUST = "666fe17a42682068a3c8497d88d5fa3732cbdfb9"
SAVED_BALANCE_RAW_SHA = "e99b06e5aa891a941ac077643a4209ab8582c810b678df4ec2d47ac48c6c646a"


def _blocked(reason: str, **details) -> dict:
    return {"status": "BLOCKED", "reasons": [reason], **details}



def _source_native_world_parity(
        native: dict, live: dict, iterations: int, *,
        expected_raw_sha: str | None = None) -> str | None:
    """Fail closed on source identity and every ACK-scored world fight.

    An equal aggregate DPS cannot establish P7.1.3 if the world probe
    omitted, reordered or duplicated a fight. The real Rust/gsim executor
    supplies these measurements; this is only an acceptance assertion.
    """
    if (live["iterations_done"] != iterations
            or native["iterations"] != iterations
            or len(live["per_iteration"]) != iterations
            or live["native_damage_events"] <= 0
            or live["native_world_ticks"] < iterations):
        return "P7_1_NATIVE_WORLD_EXECUTION_INCOMPLETE"
    if expected_raw_sha is not None and (
            live.get("source_request_raw_sha256") != expected_raw_sha):
        return "P7_1_LIVE_SOURCE_REQUEST_IDENTITY_DIVERGED"
    # NaN makes ordinary abs(actual - expected) >= tolerance comparisons
    # false. Reject nonnumeric/nonfinite native and 2D scores BEFORE parity,
    # or a forged full stochastic receipt could appear compatible at every P7 gate.
    try:
        scores = (native["native_dps"], live["native_dps"],
                  live["world_mean_dps"])
        if any(type(value) not in (int, float)
               or not math.isfinite(value) or value < 0
               for value in scores):
            return "P7_1_NATIVE_WORLD_DPS_INVALID"
        durations = (native["first_duration_s"], live["sampled_duration_s"])
        if any(type(value) not in (int, float)
               or not math.isfinite(value) or value <= 0
               for value in durations):
            return "P7_1_NATIVE_WORLD_DURATION_INVALID"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "P7_1_NATIVE_WORLD_SCALARS_MISSING"
    samples = live["per_iteration"]
    try:
        if any(
                type(row["iteration_index"]) is not int
                or row["iteration_index"] != i
                or not math.isfinite(row["duration_s"])
                or row["duration_s"] <= 0
                or not math.isfinite(row["world_dps"])
                or row["world_dps"] < 0
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
    if (abs(native["first_duration_s"] - live["sampled_duration_s"]) >= 1e-9
            or abs(samples[0]["duration_s"] - live["sampled_duration_s"]) >= 1e-9):
        return "P7_1_NATIVE_WORLD_FIRST_DURATION_DIVERGED"
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
    if (class_key, level, spec) != ("druid", 60, "balance"):
        return _blocked("P7_1_SAVED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT")

    request = root / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
    witness = root / "docs/evidence/wf633/WF633_VALIDATION.json"
    if not request.is_file() or not witness.is_file():
        return _blocked("P7_1_PINNED_SOURCE_REQUEST_OR_REFERENCE_MISSING")
    raw = request.read_bytes()
    raw_sha = hashlib.sha256(raw).hexdigest()
    if raw_sha != SAVED_BALANCE_RAW_SHA:
        return _blocked("P7_1_SAVED_REQUEST_CHANGED", actual_sha256=raw_sha)
    source = json.loads(raw)
    meta = json.loads(witness.read_text())
    player = source["raid"]["parties"][0]["players"][0]
    target = source["encounter"]["targets"]
    source_iterations = source["simOptions"]["iterations"]
    if (meta["engine_revision"] != PINNED_RUST
            or player.get("class") != "ClassDruid"
            or "balanceDruid" not in player or len(target) != 1
            or target[0]["level"] != 63):
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

    # Refuse an arbitrary executable: it must be the pinned original Rust
    # checkout with the real world ingress patched into its production Fight.
    binary = Path(os.environ.get("FOREVER_MYTHICSIM_RUST_BIN", str(
        root.parent / "upstream/target/release/forever-engine"))).resolve()
    if not binary.is_file():
        return _blocked("P7_1_PINNED_RUST_BINARY_MISSING", binary=str(binary))
    upstream = binary.parents[2]
    revision = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False)
    if revision.returncode != 0 or revision.stdout.strip() != PINNED_RUST:
        return _blocked("P7_1_RUST_SOURCE_REVISION_NOT_PINNED",
                        observed_revision=revision.stdout.strip())
    if not (upstream / "src/core/fight/world_bridge.rs").is_file():
        return _blocked("P7_1_LIVE_WORLD_INGRESS_NOT_BUILT")

    # Direct genuine production functions, reduced to the approved 1000-fight
    # final stochastic verification; never a separate gate-only simulator.
    path = root / "integrations/mythicsim-rust/live_world_probe.py"
    module_spec = importlib.util.spec_from_file_location("forever_p7_live_world", path)
    if module_spec is None or module_spec.loader is None:
        return _blocked("P7_1_PRODUCTION_WORLD_MODULE_MISSING")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    native = module.native_source_control(binary, request, run_iterations)
    live = module.run(binary, request,
                      distance=player["distanceFromTarget"], iterations=run_iterations)
    reference = float(meta["reference_dps"])
    parity_failure = _source_native_world_parity(
        native, live, run_iterations, expected_raw_sha=raw_sha)
    actual = {"native_dps": native["native_dps"],
              "native_first_duration_s": native["first_duration_s"],
              "world_first_duration_s": live["sampled_duration_s"],
              "live_native_dps": live["native_dps"],
              "world_dps": live["world_mean_dps"],
              "world_damage_events": live["native_damage_events"],
              "world_boundaries": live["native_world_ticks"],
              "source_request_raw_sha256": raw_sha,
              "live_request_raw_sha256": live.get("source_request_raw_sha256"),
              "native_source_revision": PINNED_RUST,
              "iterations": live["iterations_done"],
              "source_original_iterations": source_iterations,
              "stochastic_rng": True,
              "selected_validation": ("1000_native_and_live_stochastic_fights"
                                      if full_validation else
                                      "bounded_native_live_source_diagnostic"),
              "required_dps": p7_required_dps("P7.1", reference),
              "saved_reference_dps": reference,
              "source_report_url": "https://api.mythicsim.com/api/forever/ranking-sims/d9d85974-a1f7-4700-ab22-2335d767a944/report",
              "behavior_probes_executed": len(live["per_iteration"]),
              # Iterations are raw sample breadth, never measured function%
              # for M1 or any gate's partial behavior assertions.
              "sampled_source_fights": live["iterations_done"],
              "saved_source_iterations": source_iterations}
    if parity_failure is not None:
        return {"status": "FAIL", "reasons": [parity_failure],
                "production_engine": "pinned_mythicsim_rust_gsim_2d", **actual}
    if full_validation and (not p7_final_stochastic_mean_passes(
            "P7.1", native["native_dps"], reference,
            iterations=iterations, stochastic=True)
            or not p7_final_stochastic_mean_passes(
                "P7.1", live["world_mean_dps"], reference,
                iterations=iterations, stochastic=True)):
        return {"status": "FAIL",
                "reasons": ["P7_1_DPS_BELOW_APPROVED_99_PERCENT_FLOOR"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d", **actual}

    # The real native↔world execution established source/ACK parity, but a
    # bounded stochastic sample has NO comparable gate success denominator.
    # Use the shared live-DPS proximity output, not pass_count/total_samples.
    if not full_validation:
        return {"status": "FAIL",
                "reasons": ["P7_1_BOUNDED_DIAGNOSTIC_NOT_FULL_SAVED_REFERENCE"],
                "production_engine": "pinned_mythicsim_rust_gsim_2d",
                "p7_1_2_native_reproduced": False,
                "p7_1_3_live_reproduced": False, **actual}

    # Source provenance: original saved MythicSim request recovered directly
    # from this report by WF648, pinned with immutable raw SHA above.
    # All full stochastic native/world and 99%-DPS predicates passed above.
    return {"status": "PASS", "reasons": [],
            "production_engine": "pinned_mythicsim_rust_gsim_2d",
            "production_component": "integrations/mythicsim-rust/live_world_probe.py",
            "reference_configuration_source": "WF648_original_saved_report_request",
            "p7_1_1_reference_pinned": True,
            "p7_1_2_native_reproduced": True,
            "p7_1_3_live_reproduced": True, **actual}
