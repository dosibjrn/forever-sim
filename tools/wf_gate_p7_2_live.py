"""P7.2: pay a distinct APL-only candidate on the selected native scorer.

The approved stationary P7.2 gate needs one genuine native-legal changed
rotation with fixed gear/talents and a finite paid balanced-RNG score. No P7-only
2D world, independent 300-second search or 1,000-fight holdout is required.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time
from uuid import uuid4

from tools.wf_gate_p7_1_live import (FERAL_REFERENCE_DPS, PINNED_RUST,
                                     SAVED_BALANCE_RAW_SHA, SAVED_FERAL_RAW_SHA,
                                     _selected_rust_submodule)


def _source_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("SOURCE_PRODUCTION_MODULE_UNAVAILABLE:" + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _blocked(reason: str):
    return {"status": "BLOCKED", "reasons": [reason]}


def _cold_apl(base: dict, rng: random.Random, mutation, *,
              reference_parent=False, preserve_source_conditions=False):
    """Generate an APL-only proposal while freezing the source build.

    P7.2 does not require a cold restart: a local mutation of the runnable
    source rotation is a useful first candidate before broader cold draws.
    Gear and talents are never mutated. Rust alone judges the resulting APL.
    """
    result = copy.deepcopy(base)
    p = result["raid"]["parties"][0]["players"][0]
    original = base["raid"]["parties"][0]["players"][0]
    grammar = original["rotation"]["priorityList"]
    # The authenticated Feral APL has opaque item-swap/cooldown actions and
    # nested native predicates. Mutate complete source entries without
    # independently interpreting Warcraft conditions in Forever.
    mutation_options = ({"preserve_source_conditions": True}
                        if preserve_source_conditions else {})
    if reference_parent:
        # The authenticated reference is a legal starting *policy* for this
        # single-axis reachability gate, not an already-paid changed result.
        # Native alone decides legality of the proposed changed rotation.
        candidate = mutation.mutate_apl(
            grammar, grammar, rng, cold=False, **mutation_options)
    else:
        candidate = mutation.mutate_apl(
            None, grammar, rng, cold=True, **mutation_options)
    p["rotation"]["priorityList"] = candidate
    original = base["raid"]["parties"][0]["players"][0]
    if p["equipment"] != original["equipment"] or (
            p.get("talentsString") != original.get("talentsString")):
        raise ValueError("ROTATION_ONLY_COLD_SEARCH_CHANGED_FIXED_DIMENSIONS")
    return result


def _pinned_source_runtime(root: Path, class_key: str, level: int,
                           spec: str, gate: str, *, require_world: bool = True):
    """One exact-source native preflight shared by P7 discovery gates."""
    if (class_key, level, spec, gate) in (
            ("druid", 30, "unrestricted", "P7.2"),
            ("druid", 30, "unrestricted", "P7.3"),
            ("druid", 30, "unrestricted", "P7.4"),
            ("warlock", 20, "unrestricted", "P7.2"),
            ("warlock", 20, "unrestricted", "P7.3")):
        # The checkpoint reference is a distinct frozen native request, not
        # an L60 Balance donor. Reuse its authenticated stochastic receipt and
        # native PREPARE without charging another 1,000-fight sample.
        from tools.wf_p7_native_reference import (
            _binary_and_pin, _reference_directory, run_generated_p71,
        )
        checked = run_generated_p71(root, class_key, level, spec)
        if checked.get("status") != "PASS":
            # Preserve the underlying native-reference refusal. In particular,
            # a changed gitlink must remain distinguishable from a failed
            # source prepare or a missing frozen reference; none is a paid
            # changed-axis result. Do not silently select a different engine.
            reason = gate.replace(".", "_") + "_NATIVE_GENERATED_REFERENCE_NOT_VERIFIED"
            native_reasons = checked.get("reasons")
            return {
                "status": "BLOCKED",
                "reasons": [reason, *(
                    item for item in native_reasons
                    if isinstance(item, str)
                )] if isinstance(native_reasons, list) else [reason],
                "native_reference_status": checked.get("status"),
            }
        selected = _binary_and_pin(root)
        if selected is None:
            return _blocked(gate.replace(".", "_") + "_PINNED_RUST_BINARY_OR_GITLINK_MISSING")
        binary, revision = selected
        request_path = (_reference_directory(root, class_key, level, spec)
                        / "request.json")
        # run_generated_p71 already checked the exact bytes, encounter, engine
        # revision and real prepared actor against the frozen paid manifest.
        base = json.loads(request_path.read_bytes())
        return base, {
            "reference_dps": checked["saved_reference_dps"],
            "selected_engine_revision": revision,
            "selected_reference_profile": spec,
            "source_request_raw_sha256": checked["source_request_raw_sha256"],
            "native_actor_level_context": level,
        }, binary
    # An unrestricted checkpoint may optimize any native-legal Druid build.
    # Reuse the authentic Balance reference encounter without claiming it is
    # an independently measured unrestricted reference; P7.5 is eligible too.
    feral = spec == "feral" and gate in ("P7.2", "P7.3", "P7.4", "P7.5")
    if ((class_key, level) != ("druid", 60)
            or not (spec == "balance" or feral
                    or (gate in ("P7.2", "P7.3", "P7.4", "P7.5")
                        and spec == "unrestricted"))):
        return _blocked(gate.replace(".", "_") + "_PINNED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT")
    request = root / (
        "docs/evidence/druid-l60-feral/p7.1/saved_811_request.json" if feral
        else "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json")
    witness = root / "docs/evidence/wf633/WF633_VALIDATION.json"
    if not request.is_file() or (not feral and not witness.is_file()):
        return _blocked(gate.replace(".", "_") + "_PINNED_SOURCE_REQUEST_OR_REFERENCE_MISSING")
    raw = request.read_bytes()
    source_sha = SAVED_FERAL_RAW_SHA if feral else SAVED_BALANCE_RAW_SHA
    if hashlib.sha256(raw).hexdigest() != source_sha:
        return _blocked(gate.replace(".", "_") + "_PINNED_SOURCE_REQUEST_CHANGED")
    base = json.loads(raw)
    # Feral has its own original saved report and source identity; never
    # attribute the unrelated Balance WF633 sidecar to the Feral request.
    meta = ({"reference_dps": FERAL_REFERENCE_DPS} if feral
            else json.loads(witness.read_text()))
    player = base["raid"]["parties"][0]["players"][0]
    if ((not feral and meta.get("engine_revision") != PINNED_RUST)
            or not isinstance(meta.get("reference_dps"), (float, int))
            or meta["reference_dps"] <= 0
            or player["class"] != "ClassDruid"
            or (feral and "feralCatDruid" not in player)
            or len(base["encounter"]["targets"]) != 1
            or base["encounter"]["targets"][0]["level"] != 63):
        return _blocked(gate.replace(".", "_") + "_PINNED_REFERENCE_SCENARIO_MISMATCH")
    binary = Path(os.environ.get("FOREVER_MYTHICSIM_RUST_BIN", str(
        root.parent / "upstream/target/release/forever-engine"))).resolve()
    if not binary.is_file():
        return _blocked(gate.replace(".", "_") + "_PINNED_RUST_BINARY_MISSING")
    upstream = binary.parents[2]
    selected_rust = _selected_rust_submodule(root, upstream)
    if (selected_rust is None
            or (require_world and not
                (upstream / "src/core/fight/world_bridge.rs").is_file())):
        return _blocked(gate.replace(".", "_") + "_PINNED_NATIVE_WORLD_BUILD_NOT_VERIFIED")
    # Keep the saved report's original engine_revision unchanged.
    meta["selected_engine_revision"] = selected_rust
    # Preserve the actual source profile instead of relabeling the saved
    # Balance report as an independently measured unrestricted reference.
    meta["selected_reference_profile"] = "feral" if feral else "balance"
    meta["source_request_raw_sha256"] = source_sha
    return (base, meta, binary)


def _native_source_apl_proposals(root: Path, binary: Path, base: dict,
                                 class_key: str, level: int) -> list[dict]:
    """Build one-axis APL challengers from native get_options spell proposals.

    The frozen Warlock reference has only one priority action, so the generic
    mutator's two-action grammar cannot start from it. Rust supplies proposed
    spell IDs and remains the sole authority on their actual execution.
    """
    options = _source_module(
        root / "integrations/mythicsim-rust/native_options.py",
        "p72_selected_native_options").query_native_options(
            binary, class_key, level)
    player = base["raid"]["parties"][0]["players"][0]
    original = player["rotation"]["priorityList"]
    original_ids = {
        entry.get("action", {}).get("castSpell", {}).get("spellId", {}).get("spellId")
        for entry in original
    }
    candidates = []
    seen = set()
    for spell in options["spells"]:
        spell_id = spell.get("spell_id") if isinstance(spell, dict) else None
        if (type(spell_id) is not int or spell_id <= 0
                or spell_id in original_ids or spell_id in seen):
            continue
        seen.add(spell_id)
        # Only the exact native-returned identity is proposed. No Python
        # ranking, rank/learnability gate, or original gear/talent mutation.
        action = {"action": {"castSpell": {"spellId": {"spellId": spell_id}}}}
        for apl in ([action, *copy.deepcopy(original)], [action]):
            changed = copy.deepcopy(base)
            changed["raid"]["parties"][0]["players"][0][
                "rotation"]["priorityList"] = copy.deepcopy(apl)
            candidates.append(changed)
    return candidates


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    prepared = _pinned_source_runtime(
        root, class_key, level, spec, "P7.2", require_world=False)
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    feral = spec == "feral"
    source_sha = meta.get("source_request_raw_sha256",
                          SAVED_FERAL_RAW_SHA if feral else SAVED_BALANCE_RAW_SHA)
    native_rules = "go_reference" if feral else "forever"
    warlock_l20 = (class_key, level, spec) == (
        "warlock", 20, "unrestricted")
    if warlock_l20:
        try:
            native_proposals = _native_source_apl_proposals(
                root, binary, base, class_key, level)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError,
                KeyError, TypeError) as exc:
            return {**_blocked("P7_2_NATIVE_SOURCE_OPTIONS_UNAVAILABLE"),
                    "native_options_error": type(exc).__name__ + ":" + str(exc)[:240]}
        mutation = None
    else:
        native_proposals = []
        mutation = _source_module(
            root / "integrations/mythicsim-rust/apl_mutation.py",
            "p72_source_apl_mutator")
    production = _source_module(
        root / "integrations/mythicsim-rust/live_world_probe.py",
        "p72_selected_native_scorer")
    player = base["raid"]["parties"][0]["players"][0]
    original_apl = player["rotation"]["priorityList"]
    rng = random.Random(63272)
    initial_hash = hashlib.sha256(
        json.dumps(original_apl, sort_keys=True).encode()).hexdigest()
    best = None
    executed = 0
    failures = []
    native_refusals = []
    paid_or_rejected = set()
    proposals = 0
    search_start = time.monotonic()
    # One genuinely changed native-paid APL is sufficient for P7.2.
    # Bounded Rust-source attempts let the single-action Warlock reference
    # reach alternatives without manufacturing a Python spell catalogue.
    attempt_limit = min(len(native_proposals), 16) if warlock_l20 else 4
    while proposals < attempt_limit:
        proposals += 1
        try:
            candidate = (native_proposals[proposals - 1] if warlock_l20
                         else _cold_apl(
                             base, rng, mutation, reference_parent=(proposals <= 2),
                             preserve_source_conditions=feral))
            changed_apl = candidate["raid"]["parties"][0]["players"][0][
                "rotation"]["priorityList"]
            if changed_apl == original_apl:
                continue  # an unchanged reference is never P7.2 evidence
            candidate_sha = hashlib.sha256(
                json.dumps(candidate, sort_keys=True).encode()).hexdigest()
            if candidate_sha in paid_or_rejected:
                continue
            paid_or_rejected.add(candidate_sha)
            with tempfile.TemporaryDirectory(prefix="forever_p72_native_") as tmp:
                path = Path(tmp) / "changed-apl.json"
                path.write_text(json.dumps(candidate))
                native_options = {"go_rules": True} if feral else {}
                if level != 60:
                    # L30's native Player.level extension is not a substitute
                    # for the engine's explicit actor context during SIM.
                    native_options["actor_level"] = level
                native = production.native_source_control(
                    binary, path, 3, rng_mode="balanced", **native_options)
            if (type(native.get("iterations")) is not int
                    or native["iterations"] != 3):
                raise ValueError("P7_2_NATIVE_PAID_ITERATIONS_INCOMPLETE")
            score = native.get("native_dps")
            if (type(score) not in (int, float)
                    or not math.isfinite(score) or score < 0):
                raise ValueError("P7_2_NATIVE_PAID_DPS_INVALID")
            score = float(score)
            executed += 1
            best = (score, candidate_sha, candidate)
            break  # One changed, genuinely native-paid rotation satisfies P7.2.
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError,
                KeyError, TypeError, AssertionError) as exc:
            if isinstance(exc, getattr(production, "NativeSourceRefusal", ())):
                native_refusals.append({
                    "code": exc.code, "reason": exc.reason[:240]})
            failures.append(type(exc).__name__ + ":" + str(exc)[:180])

    search_wall_s = time.monotonic() - search_start
    if best is None:
        all_refused = bool(failures) and len(native_refusals) == len(failures)
        return {
            "status": "BLOCKED" if all_refused else "FAIL",
            "reasons": ["P7_2_NATIVE_REFUSED_ALL_DISTINCT_APL_CANDIDATES"
                        if all_refused else
                        "P7_2_NO_NATIVE_PAID_DISTINCT_APL_CANDIDATE"],
            "production_engine": "pinned_mythicsim_rust_native",
            "native_source_revision": meta.get("selected_engine_revision"),
            "source_request_raw_sha256": source_sha,
            "reference_profile": meta.get("selected_reference_profile"),
            "checkpoint_spec": spec,
            "native_rules": native_rules,
            "native_refusals": native_refusals[:4],
            "search_wall_s": search_wall_s,
            "independent_300s_search_requested": False,
            "independent_300s_search_completed": False,
            "source_legal_cold_candidates_paid": executed,
            "cold_unique_source_requests": len(paid_or_rejected),
            "cold_candidate_failures": failures[:4],
        }

    score, selected_sha, winner = best
    return {
        "status": "PASS",
        "reasons": [],
        "runtime_proof": {
            "executed": True,
            "engine_revision": meta.get("selected_engine_revision", PINNED_RUST),
            "source_revision": selected_sha,
            "run_id": "P7.2-native-" + str(uuid4()),
        },
        "production_engine": "pinned_mythicsim_rust_native",
        "production_component": "integrations/mythicsim-rust/live_world_probe.py:native_source_control",
        "native_source_revision": meta.get("selected_engine_revision", PINNED_RUST),
        "source_request_raw_sha256": source_sha,
        "native_rules": native_rules,
        "saved_reference_dps": float(meta["reference_dps"]),
        "reference_profile": meta.get("selected_reference_profile", "balance"),
        "checkpoint_spec": spec,
        "original_apl_hash": initial_hash,
        "cold_winner_request_sha256": selected_sha,
        "cold_winner_apl": winner["raid"]["parties"][0]["players"][0][
            "rotation"]["priorityList"],
        "cold_winner_request": winner,
        "winner_native_dps": score,
        "search_wall_s": search_wall_s,
        "independent_300s_search_requested": False,
        "independent_300s_search_completed": False,
        "cold_unique_source_requests": len(paid_or_rejected),
        "source_legal_cold_candidates_paid": executed,
        "cold_candidate_failures": failures[:4],
        "selected_validation": "3_native_balanced_fights_per_distinct_apl",
        "search_rng_mode": "balanced",
        "source_fixed_gear_and_talents": True,
        "coverage_scope_complete": False,
    }
