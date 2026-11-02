"""On-demand P7.1 entry into the existing pinned MythicSim Rust/gsim 2D path.

No new engine or score implementation: live_world_probe runs the native
baseline and genuine world-ACKed fight. A bounded source-fight sample
measures coupled DPS but does not measure the fraction of functioning
gate assertions. The original request alone cannot certify P7.1.1's
saved-report interactive Settings UI field audit.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
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
            or meta["iterations"] != source_iterations
            or player.get("class") != "ClassDruid"
            or "balanceDruid" not in player or len(target) != 1
            or target[0]["level"] != 63):
        return _blocked("P7_1_SAVED_REFERENCE_SCENARIO_MISMATCH")
    # Preserve the original report's 10k iteration field as pinned provenance;
    # the user-approved final validation itself uses only 1000 stochastic
    # samples. No universal 10k-simulation acceptance criterion.
    iterations = P7_FINAL_STOCHASTIC_ITERATIONS
    if (type(source_iterations) is not int or source_iterations < iterations):
        return _blocked("P7_1_ORIGINAL_REQUEST_INSUFFICIENT_FOR_1000_SAMPLES")
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
    actual = {"native_dps": native["native_dps"],
              "live_native_dps": live["native_dps"],
              "world_dps": live["world_mean_dps"],
              "world_damage_events": live["native_damage_events"],
              "world_boundaries": live["native_world_ticks"],
              "source_request_raw_sha256": raw_sha,
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
    if (live["iterations_done"] != run_iterations
            or native["iterations"] != run_iterations
            or len(live["per_iteration"]) != run_iterations
            or live["native_damage_events"] <= 0
            or (full_validation and not p7_final_stochastic_mean_passes(
                "P7.1", native["native_dps"], reference,
                iterations=iterations, stochastic=True))
            or (full_validation and not p7_final_stochastic_mean_passes(
                "P7.1", live["world_mean_dps"], reference,
                iterations=iterations, stochastic=True))
            or abs(native["native_dps"] - live["native_dps"]) >= 1e-6
            or abs(native["native_dps"] - live["world_mean_dps"]) >= 1e-5):
        return {"status": "FAIL", "reasons": ["P7_1_NATIVE_LIVE_SAVED_DPS_PARITY_FAILED"],
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

    # Owner-approved WF633 is a genuine native reference replay, but its
    # reconstructed input is not an audited field-by-field capture of the
    # exact saved report's interactive Settings UI. DPS equality is not
    # permission to manufacture that missing P7.1.1 provenance.
    return _blocked("P7_1_1_SAVED_REPORT_UI_FIELD_AUDIT_MISSING",
                    production_engine="pinned_mythicsim_rust_gsim_2d",
                    production_component="integrations/mythicsim-rust/live_world_probe.py",
                    p7_1_2_native_reproduced=True,
                    p7_1_3_live_reproduced=True, **actual)
