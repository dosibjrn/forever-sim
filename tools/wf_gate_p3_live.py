"""P3 first production contact: REAL gear catalogue, scorer and combat weights.

Uses existing source/legal IR, paid source search, production stat sensitivities,
actual item_score and P3 smoke. No alternate gear scorer or gate-only simulator.
Constrained profile/native compatibility is explicitly fail-closed until the
selected production build is actually represented.
"""
from __future__ import annotations

from math import isfinite
from pathlib import Path
from hashlib import sha256
from uuid import uuid4
import os


def _source_profile_build_ir(root: Path, ir, class_key: str, level: int, spec: str):
    """Use the actual source-legal talent frontier as the P3 build.

    Never substitute an unrestricted naked caster for a constrained profile,
    or a tree-name label for a real executable full-point talent allocation.
    This returns the IR used by the existing *paid* gear/policy evaluator.
    """
    if spec == "unrestricted":
        return ir, {"profile": spec, "full_point_source_allocation": None}

    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    from src.game.talent_execution_coverage import compile_talent_runtime
    from src.game.talents import (
        apply_talent_selection, available_talent_points,
        talented_bonus_for_level, validate_talent_selection)
    from tools.wf_source_profile import (
        _load_product_spec_profile, _source_spec_profile)

    db = Path(DEFAULT_DB)
    if not db.is_file():
        raise ValueError("P3_CANONICAL_TALENT_DB_MISSING")
    source_hash = sha256(db.read_bytes()).hexdigest()
    compiled, _ = compile_talent_runtime(ir)
    if not compiled.talents:
        raise ValueError("P3_NO_EXECUTABLE_SOURCE_TALENTS")
    bonus = talented_bonus_for_level(level)
    step = int((compiled.provenance.get("talent_tree_rules") or {})
               .get("points_per_row") or 0)
    if step <= 0:
        raise ValueError("P3_SOURCE_TALENT_TIER_RULE_MISSING")
    rule = _load_product_spec_profile(
        root, class_key, level, spec, source_sha256=source_hash)
    builds, profile = _source_spec_profile(
        compiled, spec, level=level, bonus=bonus, step=step,
        source_sha256=source_hash, profile_rule=rule)
    if not profile["source_spec_profile_verified"] or not builds:
        raise ValueError("P3_SPEC_PROFILE_NOT_SOURCE_VERIFIED:" + spec)
    # The production frontier already checked every full-point candidate.
    # A first deterministic legal candidate suffices for P3's *smoke*;
    # P4/P5 must independently search talents rather than reuse this winner.
    allocation = dict(builds[0])
    validate_talent_selection(compiled, allocation, level=level,
                              bonus_talent_points=bonus)
    if sum(allocation.values()) != available_talent_points(
            level, bonus_talent_points=bonus):
        raise ValueError("P3_SPEC_NOT_FULL_POINT_SOURCE_ALLOCATION")
    selected, receipt = apply_talent_selection(
        compiled, allocation, level=level, bonus_talent_points=bonus)
    if not receipt.applied_modifiers:
        raise ValueError("P3_SPEC_ALLOCATION_NOT_APPLIED_TO_RUNTIME")
    return selected, {
        "profile": spec,
        "full_point_source_allocation": allocation,
        "source_profile_candidate_count": len(builds),
        "source_profile_contract": profile["source_spec_profile_kind"],
        "source_talent_db_sha256": source_hash,
        "applied_modifiers": len(receipt.applied_modifiers),
    }


def native_item_options_required(
        class_key: str, level: int, spec: str = "unrestricted") -> bool:
    """Use native ItemSparse only for targets with a source-backed native provider."""
    key = str(class_key).lower()
    profile = str(spec).lower()
    return (
        (key in ("priest", "mage") and level == 20)
        or (key == "shaman" and level == 20 and profile == "unrestricted")
        or (key == "paladin" and level == 20 and profile == "unrestricted")
        or (key == "mage" and level == 30 and profile == "unrestricted")
        or (key == "rogue" and level == 20 and profile == "unrestricted")
        or (key == "druid" and level == 60 and profile == "feral")
        or (key == "mage" and level == 60 and profile in ("arcane", "fire"))
    )


def _p3_stat_witness_priority(ir, policy) -> tuple[str, ...]:
    """Order paid stat probes by their causal proximity to the selected policy.

    The P3 evaluation budget is shared and hard-capped. Alphabetically probing
    zero-weight axes spent Mage's remaining budget on Agility/Attack Power
    before the selected caster policy's Spell Power/Intellect witnesses.
    This is scheduling only: every accepted weight still requires a real paid
    before/after CombatRuntime witness; no value or applicability is inferred.
    """
    from src.game.checkpoint_p3_smoke import policy_uses_weapon_damage

    if policy_uses_weapon_damage(ir, policy):
        return (
            "attack_power", "strength", "agility", "hit", "crit",
            "spell_power", "intellect", "spirit", "mp5",
        )
    return (
        "spell_power", "intellect", "spirit", "mp5", "hit", "crit",
        "agility", "attack_power", "strength",
    )


def _p3_executable_weight_witness_axes(blockers, weights, executable_axes, priority):
    """Retry missing or zero weights only when the selected source can execute them.

    Item-level P3 blockers determine applicability; executable_axes comes from
    the selected IR's real stat-perturbation provider. A missing weight is NOT
    a measured zero, and an unsupported native item stat is NOT executable.
    Both cases remain unresolved unless a genuinely paid same-policy probe
    later establishes a finite weight.
    """
    available = set(executable_axes)
    rank = {axis: index for index, axis in enumerate(priority)}
    selected = set()
    for blocker in blockers:
        kind, separator, axis = str(blocker).partition(":")
        if not separator or kind not in ("MISSING_WEIGHT", "NONPOSITIVE_RELEVANT_WEIGHT"):
            continue
        if kind == "MISSING_WEIGHT":
            # Only the paid source-runner's *actual* axis-selection receipt can
            # authorize a previously missing axis for real stat perturbation.
            if axis not in available or axis in weights:
                continue
        elif weights.get(axis) != 0.0:
            # Keep previously measured zero-weight witness attempts intact.
            # A mock or partial receipt must never erase an existing witness.
            continue
        selected.add(axis)
    return sorted(selected, key=lambda axis: (rank.get(axis, len(rank)), axis))


def _accept_paid_p3_stat_witness(weights: dict, axis: str, witness: dict) -> bool:
    """Apply only a real paid positive slope or a genuinely measured missing zero.

    Exact-zero derivatives may satisfy P3's nonnegative item requirement, but
    only when a completed paid before/after witness exists. They must not
    overwrite an existing measured weight, turn a negative effect into zero,
    or turn an unsupported stat into an assumed zero.
    """
    status = witness.get("status")
    if witness.get("stat") != axis:
        return False
    measured = witness.get("weight_s_saved_per_mob_per_unit")
    if type(measured) not in (int, float) or not isfinite(measured):
        return False
    if status == "MEASURED_POSITIVE_SOURCE_POLICY_WITNESS":
        if measured <= 0:
            return False
    elif status == "MEASURED_ZERO_SOURCE_POLICY_WITNESS":
        if measured != 0.0 or axis in weights:
            return False
    else:
        return False
    weights[axis] = float(measured)
    return True


def _native_item_stat_probe_deltas(item_check: dict, axis: str):
    """Return native item-sized deltas in descending measurement value.

    Candidate probes are the largest single positive stat amount among the
    selected legal top-five items and, when available, the sum from two
    different slots. Return the largest delta first so a tight paid-evaluation
    budget tests the strongest real item-sized perturbation before smaller
    deltas. The pair is a measured stat delta, not a jointly legal build claim.
    """
    best_by_slot = {}
    for slot, slot_report in item_check.get("slots", {}).items():
        for item in slot_report.get("items", ()):
            amount = item.get("stat_values", {}).get(axis)
            item_id = item.get("item_id")
            if (type(amount) not in (int, float)
                    or not isfinite(float(amount)) or float(amount) <= 0.
                    or type(item_id) is not int):
                continue
            candidate = {
                "slot": str(slot), "item_id": item_id,
                "name": str(item.get("name") or ""),
                "amount": float(amount),
            }
            previous = best_by_slot.get(str(slot))
            if (previous is None or candidate["amount"] > previous["amount"]
                    or (candidate["amount"] == previous["amount"]
                        and candidate["item_id"] < previous["item_id"])):
                best_by_slot[str(slot)] = candidate
    ranked = sorted(best_by_slot.values(),
                    key=lambda item: (-item["amount"], item["slot"], item["item_id"]))
    if not ranked:
        return (), []
    deltas = [ranked[0]["amount"]]
    sources = [{
        "kind": "single_native_item",
        "delta": ranked[0]["amount"],
        "items": [dict(ranked[0])],
    }]
    if len(ranked) >= 2:
        pair = ranked[:2]
        total = sum(item["amount"] for item in pair)
        if total > deltas[0]:
            deltas.append(total)
            sources.append({
                "kind": "two_distinct_native_item_slots",
                "delta": total,
                "items": [dict(item) for item in pair],
            })
    ordered = sorted(zip(deltas, sources), key=lambda pair: -pair[0])
    return (tuple(delta for delta, _source in ordered),
            [source for _delta, source in ordered])


def _source_actor_context_summary(ir) -> dict:
    """Expose source actor/weapon provenance when the paid naked search blocks."""
    actor = getattr(ir, "actor", None)
    if actor is None:
        return {}
    metadata = getattr(actor, "metadata", {}) or {}
    try:
        base_stats = dict(getattr(actor, "base_stats", {}) or {})
    except (TypeError, ValueError):
        base_stats = {}
    actor_provenance = getattr(actor, "provenance", ()) or ()
    if not isinstance(actor_provenance, (list, tuple)):
        actor_provenance = (actor_provenance,)
    auto_attacks = []
    for attack in getattr(ir, "auto_attacks", ()) or ():
        source = getattr(attack, "damage_source", None)
        provenance = getattr(attack, "provenance", ()) or ()
        if not isinstance(provenance, (list, tuple)):
            provenance = (provenance,)
        auto_attacks.append({
            "id": getattr(attack, "id", None),
            "attack_type": getattr(attack, "attack_type", None),
            "required_mode_id": getattr(attack, "required_mode_id", None),
            "swing_time_s": getattr(attack, "swing_time_s", None),
            "damage_source": {
                "kind": getattr(source, "kind", None),
                "flat_dps": getattr(source, "flat_dps", None),
                "dps_stat_id": getattr(source, "dps_stat_id", None),
                "attack_power_stat_id": getattr(source, "attack_power_stat_id", None),
            },
            "provenance": list(provenance),
        })
    return {
        "state_status": getattr(actor, "state_status", None),
        "base_stats": base_stats,
        "base_stats_are_zero_proxy": metadata.get("base_stats_are_zero_proxy"),
        "race_key": metadata.get("race_key"),
        "actor_provenance": list(actor_provenance),
        "auto_attacks": auto_attacks,
    }



def _native_equipped_p3_reservation(
        class_key: str, level: int, spec: str, native_binary: str | None) -> int:
    """Reserve one baseline and up to 17 native slot alternatives for Rogue L20."""
    return (44 if native_binary and str(class_key).lower() == "rogue"
            and int(level) == 20 and str(spec).lower() == "unrestricted"
            and os.environ.get("FOREVER_P3_NATIVE_ROGUE_REQUEST") else 0)


def _native_p3_equipped_slot_proposals(native_options: dict) -> dict:
    """Project Rust-supplied option IDs onto the native request's slot names.

    This is equipment-request serialization, not a Python legality check or
    weighted scorer. The selected Rust engine still accepts/refuses every
    fully equipped candidate and measures its DPS.
    """
    # Native ItemSparse categories and request equipment positions have
    # different names for hands, fingers and trinkets. No class/item rules.
    slot_aliases = {
        "one_hand": ("weapon",), "main_hand": ("weapon",),
        "two_hand": ("weapon",), "off_hand": ("offhand",),
        "finger": ("ring1", "ring2"),
        "trinket": ("trinket1", "trinket2"),
        "thrown": ("ranged",),
    }
    native_slots = {
        "weapon", "offhand", "ranged", "head", "neck", "shoulder",
        "back", "chest", "wrist", "hands", "waist", "legs", "feet",
        "ring1", "ring2", "trinket1", "trinket2",
    }
    grouped = {}
    for option in native_options.get("items", ()):
        slot = option.get("slot")
        item_id = option.get("item_id")
        if type(item_id) is not int or item_id <= 0:
            continue
        destinations = slot_aliases.get(slot, (slot,))
        for destination in destinations:
            if destination in native_slots:
                grouped.setdefault(destination, []).append(option)
    proposals = {}
    for slot, items in grouped.items():
        ordered = sorted(
            items, key=lambda row: (
                -(row.get("item_level") if type(row.get("item_level")) is int else -1),
                row["item_id"]))
        # Forward one spare Rust proposal: the first may already be worn,
        # leaving two genuinely distinct native candidates to evaluate.
        selected_ids = list(dict.fromkeys(row["item_id"] for row in ordered))[:3]
        if selected_ids:
            proposals[slot] = {"selected_ids": selected_ids}
    return {"slots": proposals}


def _query_native_unified_p3_items(root: Path, native_binary: str,
                                   class_key: str, level: int) -> dict:
    """Project confirmed Rust get_options items, never Python equip legality.

    A native_eligible row has a Rust-provided structural slot. Unverified
    proficiency has no confirmed equipment position and earns no P3 credit.
    Every proposed full build still goes through selected native prepare/score.
    """
    import importlib.util

    path = root / "integrations/mythicsim-rust/native_options.py"
    spec = importlib.util.spec_from_file_location("selected_native_p3_options", path)
    if spec is None or spec.loader is None:
        raise ValueError("P3_NATIVE_UNIFIED_OPTIONS_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = module.query_native_options(native_binary, class_key, level)
    confirmed = [dict(row["native"]) for row in source["items"]
                 if row["eligibility"] == "native_eligible"]
    unverified = sum(row["eligibility"] == "proficiency_unverified"
                     for row in source["items"])
    return {
        "status": "ok" if confirmed else "empty",
        "transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
        "source": source["source_revision"],
        "coverage": source["coverage"],
        "unverified_candidate_count": unverified,
        "items": confirmed,
    }


def _paid_native_equipped_probe(root: Path, native_binary: str | None,
                                item_check: dict, remaining: int, *,
                                checkpoint: str = "rogue_l20"):
    """Use the existing selected-native sim boundary when an exact source
    request is supplied. Do not convert a level-60 fixture into a claimed
    level-20 actor or spend outside the shared P3 evaluation cap.
    """
    if checkpoint == "feral_l60":
        request_path = str(root / "docs/evidence/druid-l60-feral/p7.1/saved_811_request.json")
    elif checkpoint in ("mage_l60", "mage_fire_l60"):
        # Shared selected-native Mage source fixtures; never invent a build
        # from Python class rules or reuse Arcane's actor for Fire.
        mage_profile = "fire" if checkpoint == "mage_fire_l60" else "arcane"
        request_path = str(root / "integrations/mythicsim-rust/engine"
                           / f"fixtures/mage/prepared-v2/{mage_profile}-reference.request.json")
    else:
        request_path = os.environ.get("FOREVER_P3_NATIVE_ROGUE_REQUEST")
    if not request_path:
        return None
    if remaining < 2:
        return {"status": "NOT_RUN_PAID_BUDGET_EXHAUSTED", "paid_attempts": 0}
    if not native_binary:
        return {"status": "NOT_RUN_NATIVE_BINARY_MISSING", "paid_attempts": 0}
    import json
    import subprocess
    import sys

    script = root / "integrations/mythicsim-rust/native_p3_equipped.py"
    command = [sys.executable, str(script), "--binary", str(native_binary),
               "--request", str(request_path),
               "--max-paid-attempts", str(min(remaining, 44))]
    if checkpoint == "feral_l60":
        command.extend(("--class-key", "druid", "--level", "60", "--go-rules"))
    elif checkpoint in ("mage_l60", "mage_fire_l60"):
        mage_profile = "fire" if checkpoint == "mage_fire_l60" else "arcane"
        command.extend(("--class-key", "mage", "--level", "60",
                        "--current-client-profile", f"mage/{mage_profile}"))
    try:
        completed = subprocess.run(
            command, input=json.dumps(item_check.get("slots", {})),
            capture_output=True, text=True, timeout=150, check=False)
        if completed.returncode != 0:
            return {"status": "NATIVE_EQUIPPED_PROBE_ERROR", "paid_attempts": 0,
                    "error": (completed.stderr or completed.stdout)[-500:]}
        receipt = json.loads(completed.stdout)
        if (not isinstance(receipt, dict)
                or type(receipt.get("paid_attempts")) is not int
                or not 0 <= receipt["paid_attempts"] <= min(remaining, 44)):
            raise ValueError("P3_NATIVE_EQUIPPED_INVALID_RECEIPT")
        return receipt
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"status": "NATIVE_EQUIPPED_PROBE_ERROR",
                "paid_attempts": 0, "error": str(exc)[-500:]}


def _native_rogue_p3_verdict(options: dict, receipt: dict, *,
                             checkpoint: str = "rogue_l20") -> dict:
    """P3 is native paid gear scoring, not legacy naked-policy discovery."""
    import json
    source_sha = sha256(json.dumps(
        options, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt = receipt if isinstance(receipt, dict) else {}
    rows = receipt.get("evaluations") or []
    alternatives = receipt.get("native_slot_evaluations") or []
    proposals = _native_p3_equipped_slot_proposals(options)["slots"]
    # Only occupied positions in the actual Mage request need P3 paid scores.
    # The full native options domain may include absent offhand/ranged fields.
    is_mage_l60 = checkpoint in ("mage_l60", "mage_fire_l60")
    occupied = receipt.get("source_occupied_slots")
    occupancy_verified = (
        isinstance(occupied, list) and bool(occupied)
        and all(type(slot) is str for slot in occupied)
        and len(set(occupied)) == len(occupied)
        and len(occupied) <= 17
    )
    statuses = ({slot: [] for slot in occupied}
                if is_mage_l60 and occupancy_verified
                else {slot: [] for slot in proposals})
    for row in alternatives:
        if isinstance(row, dict):
            slot = (row.get("swap") or {}).get("slot")
            if slot in statuses:
                statuses[slot].append(row.get("status"))
    verified = sum("VALID" in outcomes for outcomes in statuses.values())
    baseline = rows[0] if rows and isinstance(rows[0], dict) else {}
    prepared = receipt.get("native_prepared_actor") or {}
    revision = prepared.get("engine_revision")
    request_sha = baseline.get("request_sha256")
    paid = receipt.get("paid_attempts", 0)
    reasons = []
    if is_mage_l60 and not occupancy_verified:
        reasons.append("P3_NATIVE_OCCUPIED_SLOT_RECEIPT_MISSING")
    if type(paid) is not int or not 1 <= paid <= 44:
        reasons.append("P3_NATIVE_PAID_ATTEMPTS_INVALID")
    if baseline.get("status") != "VALID" or (
            type(baseline.get("score")) not in (int, float)
            or not isfinite(baseline["score"])):
        reasons.append("P3_NATIVE_BASELINE_NOT_VALID")
    expected_class, expected_level = (
        ("ClassDruid", 60) if checkpoint == "feral_l60" else
        ("ClassMage", 60) if is_mage_l60 else ("ClassRogue", 20))
    if (receipt.get("actor_checkpoint_verified") is not True
            or prepared.get("actor_class") != expected_class
            or prepared.get("actor_level") != expected_level):
        reasons.append("P3_NATIVE_EQUIPPED_SCORE_UNVERIFIED:"
                       + str(receipt.get("status")))
    if not statuses:
        reasons.append("P3_NATIVE_REPRESENTATIVE_SLOTS_UNAVAILABLE")
    for slot, outcomes in statuses.items():
        if "VALID" not in outcomes:
            reasons.append("P3_NATIVE_SLOT_UNSCORED:" + slot + ":"
                           + (str(outcomes[-1]) if outcomes else "NOT_ATTEMPTED"))
    if not any(
            isinstance(row, dict) and row.get("status") == "VALID"
            and type(row.get("delta_dps")) in (int, float)
            and isfinite(row["delta_dps"]) and row["delta_dps"] != 0
            for row in alternatives):
        reasons.append("P3_NATIVE_RELEVANT_SCORE_SENSITIVITY_NOT_MEASURED")
    if not isinstance(revision, str) or not revision:
        reasons.append("P3_NATIVE_ENGINE_REVISION_UNAVAILABLE")
    if not isinstance(request_sha, str) or not request_sha:
        reasons.append("P3_NATIVE_PAID_REQUEST_ID_UNAVAILABLE")
    status = "PASS" if not reasons else "BLOCKED" if not paid else "FAIL"
    proof = ({"runtime_proof": {
        "executed": True, "engine_revision": revision,
        "source_revision": source_sha, "run_id": request_sha}}
        if status == "PASS" else {})
    return {
        "status": status, "reasons": reasons, **proof,
        "production_component": "integrations/mythicsim-rust/native_p3_equipped.py",
        "production_engine": "mythicsim_rust",
        "item_options_source": options.get("transport", "MYTHICSIM_NATIVE_ITEM_OPTIONS"),
        "native_item_options_status": options.get("status"),
        "native_item_options_source": options.get("source"),
        "native_unverified_candidate_count": options.get("unverified_candidate_count", 0),
        "real_catalogue_legal_items": len(options.get("items") or []),
        "real_catalogue_slots_scored": verified,
        "real_native_representative_items_scored": receipt.get("native_slots_valid", 0),
        "real_selected_item_alternatives_by_slot": proposals,
        "source_occupied_slots": occupied if occupancy_verified else None,
        "real_source_search_attempts": 0, "real_source_search_evaluated": 0,
        "native_equipped_paid_receipt": receipt,
        "native_equipped_paid_attempts": paid,
        "p3_shared_budget_attempts": paid,
        "p3_native_pair_reserved_attempts": 44,
        "behavior_probes_executed": paid,
        "reachability_count": len(statuses), "pass_count": verified,
        "partial_scope": "NATIVE_REPRESENTATIVE_SLOTS_PAID",
        "coverage_basis": "executed_native_slot_alternatives",
        "coverage_scope_complete": False,
        "real_item_score_checked": bool(verified),
        "source_context_sha256": source_sha,
    }


def run_live(root: Path, class_key: str, level: int, *, spec: str = "unrestricted") -> dict:
    # Selected P3 class/level paths require authoritative native ItemSparse.
    # Unsupported native queries refuse; never fall back to Python/SQLite gear.
    native_required = native_item_options_required(class_key, level, spec)
    native_binary = (os.environ.get('FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN')
                     if native_required else None)
    if native_required and not native_binary:
        return {'status': 'BLOCKED',
                'reasons': ['P3_NATIVE_ITEM_OPTIONS_BINARY_REQUIRED'],
                'production_component': 'src.game.native_p3_item_options'}
    native_options = None
    is_rogue_native = (str(class_key).lower() == "rogue" and int(level) == 20
                       and str(spec).lower() == "unrestricted")
    is_feral_native = (str(class_key).lower() == "druid" and int(level) == 60
                       and str(spec).lower() == "feral")
    is_mage_native = (str(class_key).lower() == "mage" and int(level) == 60
                      and str(spec).lower() in ("arcane", "fire"))
    if is_rogue_native or is_feral_native or is_mage_native:
        # Rogue's selected engine capability was previously untested because
        # SQLite returned no items. Refuse *before* consuming paid evaluations
        # until the exact pinned native engine can supply legal options.
        from src.game.native_p3_item_options import (
            NativeItemOptionsError, query_native_p3_item_options)
        try:
            if is_mage_native:
                native_options = _query_native_unified_p3_items(
                    root, native_binary, class_key, level)
            else:
                native_options = query_native_p3_item_options(
                    native_binary, class_key, level,
                    spec=("unrestricted" if is_feral_native else spec), slot="all")
        except (NativeItemOptionsError, ValueError) as exc:
            return {'status': 'BLOCKED', 'reasons': [str(exc)],
                    'production_component': 'src.game.native_p3_item_options',
                    'real_source_search_evaluated': 0}
        if not native_options['items']:
            return {'status': 'BLOCKED',
                    'reasons': ['NATIVE_ITEM_OPTIONS_NO_VERIFIED_CANDIDATES'],
                    'production_component': 'src.game.native_p3_item_options',
                    'real_source_search_evaluated': 0}

    # Native P3 scores the source actor directly; no GameIR or policy fallback.
    if native_options is not None:
        if is_rogue_native and not os.environ.get("FOREVER_P3_NATIVE_ROGUE_REQUEST"):
            return {"status": "BLOCKED",
                    "reasons": ["P3_NATIVE_ROGUE_REQUEST_REQUIRED"],
                    "production_component": "integrations/mythicsim-rust/native_p3_equipped.py"}
        selection = _native_p3_equipped_slot_proposals(native_options)
        checkpoint = ("feral_l60" if is_feral_native else
                      "mage_fire_l60" if is_mage_native and str(spec).lower() == "fire"
                      else "mage_l60" if is_mage_native else "rogue_l20")
        if is_rogue_native:
            receipt = _paid_native_equipped_probe(root, native_binary, selection, 44)
        else:
            receipt = _paid_native_equipped_probe(
                root, native_binary, selection, 44, checkpoint=checkpoint)
        return _native_rogue_p3_verdict(
            native_options, receipt, checkpoint=checkpoint)

    rogue_native_preflight = None
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.checkpoint_p3_smoke import fast_p3_smoke_for_policy
    from src.v2.source_budgeted_gear import (
        run_source_budgeted_gear, paid_search_winner_baseline,
        paid_source_policy_stat_witness)
    from src.v2.source_stateful_budgeted import _make_policy
    from src.game.model import PolicyCondition

    # This is an actual cheap P3 attempt, not a 300s optimization. No default
    # weights, class-specific winners or invented P3 positive epsilons.
    ir = build_game_ir_slice(class_key=class_key, level=level)
    if ir is None:
        return {"status": "BLOCKED", "reasons": [
            "P3_SELECTED_CLASS_LEVEL_SOURCE_IR_UNAVAILABLE"],
            "production_component": "src.game.checkpoint_p3_smoke.fast_p3_smoke_for_policy"}
    try:
        ir, profile_context = _source_profile_build_ir(
            root, ir, class_key, level, spec)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {"status": "BLOCKED", "reasons": [
            "P3_SOURCE_PROFILE_PRODUCTION_BUILD_UNAVAILABLE:"
            + str(exc)], "production_component":
            "src.v2.source_bounded_joint_frontier.source_spec_talent_frontier"}
    native_spell_facts = None
    native_spell_coefficients_applied = []
    native_spell_coefficients_error = None
    mage_l30_spellbook = (
        str(class_key).lower() == "mage" and int(level) == 30
        and str(spec).lower() == "unrestricted")
    shaman_l20_spellbook = (
        str(class_key).lower() == "shaman" and int(level) == 20
        and str(spec).lower() == "unrestricted")
    if mage_l30_spellbook or shaman_l20_spellbook:
        from src.game.native_p3_item_options import (
            NativeItemOptionsError, apply_native_mage_spell_coefficients,
            apply_native_shaman_lightning_bolt_coefficient,
            query_native_mage_spell_coefficients,
            query_native_shaman_spell_coefficients,
        )
        try:
            if shaman_l20_spellbook:
                native_spell_facts = query_native_shaman_spell_coefficients(native_binary)
                ir, native_spell_coefficients_applied = (
                    apply_native_shaman_lightning_bolt_coefficient(
                        ir, native_spell_facts))
            else:
                native_spell_facts = query_native_mage_spell_coefficients(native_binary)
                ir, native_spell_coefficients_applied = (
                    apply_native_mage_spell_coefficients(ir, native_spell_facts))
        except (NativeItemOptionsError, ValueError, TypeError, OSError) as exc:
            if shaman_l20_spellbook:
                # Native spell coefficient evidence is optional for this P3
                # continuation. Preserve the existing measured result and
                # report the exact refusal; never turn missing source data
                # into a guessed coefficient, weight or BLOCKED gate verdict.
                native_spell_coefficients_error = str(exc)
            else:
                return {
                    "status": "BLOCKED",
                    "reasons": [str(exc)],
                    "production_component": "src.game.native_p3_item_options",
                }
    native_player_context = None
    if (str(class_key).lower() == "paladin" and int(level) == 20
            and str(spec).lower() == "unrestricted"):
        # Source-backed actor and equipped-weapon facts come from the selected
        # Rust authority, never from the old zero-stat/14-DPS scenario proxy.
        # This is still a context-only query, not native L20 combat execution.
        from src.game.native_p3_player_context import (
            NativePlayerContextError, apply_native_player_context,
            query_native_player_context,
        )
        # The selected item-options engine is also the Paladin actor authority.
        # A second environment variable is optional; never silently fall back
        # to the zero-stat proxy when it is omitted.
        player_context_binary = (
            os.environ.get("FOREVER_P3_NATIVE_PLAYER_CONTEXT_BIN") or native_binary)
        try:
            native_player_context = query_native_player_context(
                player_context_binary, class_key, level)
            ir = apply_native_player_context(ir, native_player_context)
        except (NativePlayerContextError, ValueError, TypeError, KeyError) as exc:
            return {
                "status": "BLOCKED",
                "reasons": [str(exc)],
                "production_component": "src.game.native_p3_player_context",
            }
    max_p3_evaluations = 44
    # Reserve the shared budget for one native baseline and representative
    # per-slot Rust alternatives. Never run these after 44 source+native pays.
    native_pair_reserved = _native_equipped_p3_reservation(
        class_key, level, spec, native_binary)
    source_search_budget = max_p3_evaluations - native_pair_reserved
    schedule_incoming_attacks = True
    result = run_source_budgeted_gear(
        class_key=class_key, level=level, ir_slice=ir,
        max_evaluations=source_search_budget, initial_search=12, search_per_gear=3,
        max_gear_states=1, probe_deltas=(5., 20.),
        probe_stats=("armor", "stamina", "strength", "agility", "intellect",
                     "spirit", "spell_power", "attack_power", "mp5",
                     "crit", "hit", "dodge", "parry",
                     "health_regeneration_per_5s", "weapon_dps"),
        schedule_incoming_attacks=schedule_incoming_attacks,
        # Neither cooldown pacing nor existing melee auto-attacks are P3
        # legality gates; try them through the real paid executor for any class.
        allow_cooldown_fallback=True,
        source_search_auto_fallback=True)
    stages = result.get("stages") or []
    naked = next((x for x in stages if x.get("stage") == "source_naked"), None)
    sensitivity = next((x for x in result.get("sensitivity_history", ())
                        if x.get("stage") == "source_naked"
                        and isinstance(x.get("values"), dict)), None)
    # A cooldown-bound source action can now be explored by the real prefix
    # executor even when no zero-cooldown filler exists. Its observed score
    # is NOT P3 evidence when the selected actor or weapon is still a
    # scenario proxy. Do not turn a successful proxy search into an M1 row.
    fallback_id = str(((naked or {}).get("winner") or {}).get("fallback") or "")
    cooldown_fallback = any(
        getattr(action, 'id', None) == fallback_id
        and float(getattr(action, 'cooldown_s', 0) or 0) > 0
        for action in ir.actions)
    actor_proxy = getattr(ir.actor, "metadata", {}).get("base_stats_are_zero_proxy") is True
    weapon_proxy = any(
        "proxy" in str(source.get("caveat") or "")
        for attack in getattr(ir, 'auto_attacks', ())
        for source in getattr(attack, 'provenance', ())
        if isinstance(source, dict))
    auto_fallback = fallback_id == "__source_verified_auto_attack_only__"
    if (cooldown_fallback or auto_fallback) and (actor_proxy or weapon_proxy):
        return {
            "status": "BLOCKED",
            "reasons": ["P3_SOURCE_CONTINUATION_HAS_PROXY_ACTOR_OR_WEAPON"],
            "production_component": "src.v2.source_budgeted_gear.run_source_budgeted_gear",
            "real_source_search_attempts": result.get("attempted", 0),
            "real_source_search_evaluated": 0,
            "diagnostic_proxy_search_evaluated": result.get("evaluated", 0),
            "source_naked_stage": {
                "search_backend": naked.get("search_backend"),
                "search_status": naked.get("search_status"),
                "attempted": naked.get("attempted", 0),
                "evaluated": naked.get("evaluated", 0),
                "blocked": naked.get("blocked", 0),
            },
            "source_naked_diagnostics": naked.get("source_search_diagnostics"),
            "source_actor_context": _source_actor_context_summary(ir),
        }
    if not naked or not naked.get("winner") or sensitivity is None:
        return {"status": "BLOCKED", "reasons": [
            "P3_PRODUCTION_SEARCH_OR_MEASURED_WEIGHT_CONTEXT_UNAVAILABLE:"
            + str(result.get("status"))],
            "production_component": "src.v2.source_budgeted_gear.run_source_budgeted_gear",
            "real_source_search_attempts": result.get("attempted", 0),
            "real_source_search_evaluated": result.get("evaluated", 0),
            "source_naked_stage": ({
                "search_backend": naked.get("search_backend"),
                "search_status": naked.get("search_status"),
                "attempted": naked.get("attempted", 0),
                "evaluated": naked.get("evaluated", 0),
                "blocked": naked.get("blocked", 0),
            } if naked else None),
            "source_naked_diagnostics": (
                naked.get("source_search_diagnostics") if naked else None),
            "source_actor_context": _source_actor_context_summary(ir),
            # A bounded/unavailable legacy policy winner is not permission to
            # discard already paid, source-native Rogue equipment scoring.
            "native_equipped_paid_receipt": rogue_native_preflight,
            "native_equipped_paid_attempts": (
                rogue_native_preflight.get("paid_attempts", 0)
                if rogue_native_preflight else 0),
            "p3_shared_budget_attempts": (
                int(result.get("attempted", 0))
                + (rogue_native_preflight.get("paid_attempts", 0)
                   if rogue_native_preflight else 0)),
            "p3_native_pair_reserved_attempts": native_pair_reserved,
        }
    record = naked["winner"]
    native_spell_action_ids = {
        str(row.get("action_id")) for row in native_spell_coefficients_applied
        if isinstance(row, dict) and row.get("action_id")
    }
    native_fallback_action = str(record.get("fallback") or "") in native_spell_action_ids
    policy = _make_policy(
        ir, record["fallback"],
        guarded_action=record.get("guarded_action"),
        guarded_conditions=tuple(PolicyCondition(**x)
                                 for x in record.get("guarded_conditions", ())))
    weights = dict(sensitivity["values"])
    if not all(type(v) in (int, float) and isfinite(v) for v in weights.values()):
        return {"status": "FAIL", "reasons": ["P3_REAL_PRODUCTION_WEIGHTS_NONFINITE"]}
    # Native ItemSparse activation was required before paid search above;
    # non-target profiles continue through their existing P3 source path.
    try:
        item_check = fast_p3_smoke_for_policy(
            source_ir=ir, policy=policy, class_key=class_key, level=level,
            weights=weights, weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
            native_options_binary=native_binary,
            native_options_response=native_options)
    except ValueError as exc:
        if native_binary is None:
            raise
        return {'status': 'BLOCKED', 'reasons': [str(exc)],
                'production_component': 'src.game.native_p3_item_options',
                'real_source_search_evaluated': result.get('evaluated', 0)}
    # One narrowly chosen 12-evaluation winner is not proof that an ordinary
    # stat has no causal value to this build. The same source-legal full-point
    # IR may carry alternative executable policies. When the first policy
    # measured exactly ZERO for a required axis, seek a positive *paid* witness
    # with the source-authored policies and the same combat+recovery scorer.
    # Do not erase observed negative weights, waive missing stats, fabricate an
    # epsilon, or change P4/P5 search. The only extra work is paid from the
    # source search's remaining bounded budget.
    extra_evaluations = 0
    source_policy_stat_witnesses = []
    newly_measured_weight = False
    # Reuse a paid baseline for the same source policy across stat axes. Without
    # this, repeated baseline runs consume the fixed P3 budget before later
    # required axes (such as Spirit) receive their own paid perturbation.
    source_policy_baseline_cache = {}
    witness_priority = _p3_stat_witness_priority(ir, policy)
    # Reuse the *same* source-executor axis receipt that fed the paid search:
    # querying an unrelated/default IR again can silently change DB scope.
    source_probe_axes = (
        (result.get("stat_probe_axis_selection") or {})
        .get("selected_for_paid_probe") or ())
    witness_axes = _p3_executable_weight_witness_axes(
        item_check["blockers"], weights, source_probe_axes, witness_priority)
    mage_l30_native = (
        str(class_key).lower() == "mage" and int(level) == 30
        and str(spec).lower() == "unrestricted"
        and item_check.get("source") == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
    )
    shaman_l20_native = (
        shaman_l20_spellbook
        and item_check.get("source") == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
    )
    rogue_l20_native = (
        str(class_key).lower() == "rogue" and int(level) == 20
        and str(spec).lower() == "unrestricted"
        and item_check.get("source") == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
    )
    # The Rogue item catalogue now comes from the same selected native
    # ItemSparse provider as Mage/Shaman. Probe real top-five item stat sizes,
    # not guessed (5, 20) deltas; every weight still needs a paid comparison.
    native_item_sized_probe = (
        mage_l30_native or shaman_l20_native or rogue_l20_native)
    if shaman_l20_native:
        # This issue is only the Spell Power witness. Other zero axes are
        # separate P3 defects. If the exact native coefficient/action was not
        # obtained, retain the existing score without attempting a substitute.
        witness_axes = (
            [] if native_spell_coefficients_error else [
                axis for axis in witness_axes if axis == "spell_power"
            ])
    # The Shaman paid winner is eligible only when its actual fallback is the
    # exact, native-enriched rank-915 source action.
    native_spell_winner = (
        mage_l30_native or (shaman_l20_native and native_fallback_action))
    force_native_shaman_spell_power_witness = (
        shaman_l20_native and native_spell_winner
        and native_spell_coefficients_error is None
        and bool(native_spell_coefficients_applied))
    if (force_native_shaman_spell_power_witness
            and "spell_power" not in witness_axes):
        # The native coefficient can make the initial CombatRuntime sensitivity
        # positive, removing the NONPOSITIVE blocker. Still require the explicit
        # paid source-policy witness for the exact native fallback action.
        witness_axes.insert(0, "spell_power")
    paid_winner_baseline_available = (
        native_spell_winner
        and paid_search_winner_baseline(
            policy, record, tuple(record.get("prefix") or ())) is not None
    )
    for axis in witness_axes:
        if (axis in weights and weights[axis] != 0.0
                and not (force_native_shaman_spell_power_witness
                         and axis == "spell_power")):
            continue
        if native_item_sized_probe:
            probe_deltas, probe_delta_sources = _native_item_stat_probe_deltas(
                item_check, axis)
            # If native top-five items have no positive value for this axis,
            # do not fall back to guessed generic deltas.
            if not probe_deltas:
                continue
        else:
            probe_deltas = (5., 20.)
            probe_delta_sources = []
        remaining = max(0, source_search_budget - int(result.get("attempted", 0)) - extra_evaluations)
        cache_prefix = (id(ir), int(level), bool(schedule_incoming_attacks))
        has_reusable_baseline = any(
            key[:3] == cache_prefix
            and type(value) in (int, float)
            and isfinite(value) and value > 0
            for key, value in source_policy_baseline_cache.items()
        )
        minimum_evaluations = (
            1 if (has_reusable_baseline or paid_winner_baseline_available)
            else (3 if native_item_sized_probe and record.get("prefix") else 2)
        )
        if remaining < minimum_evaluations:
            break
        witness = paid_source_policy_stat_witness(
            ir, stat=axis, level=level, probe_deltas=probe_deltas,
            max_evaluations=remaining,
            schedule_incoming_attacks=schedule_incoming_attacks,
            baseline_cache=source_policy_baseline_cache,
            opening_action_ids=tuple(record.get("prefix", ())),
            preferred_policy=(policy if native_spell_winner else None),
            baseline_record=(record if native_spell_winner else None),
            allow_paid_winner_after_nonpositive=(
                native_fallback_action and (mage_l30_native or shaman_l20_native)),
            breadth_first_verified_native_winner=mage_l30_native)
        if native_item_sized_probe:
            witness["probe_delta_sources"] = probe_delta_sources
        extra_evaluations += int(witness["paid_evaluations"])
        source_policy_stat_witnesses.append(witness)
        if _accept_paid_p3_stat_witness(weights, axis, witness):
            newly_measured_weight = True
    if newly_measured_weight:
        item_check = fast_p3_smoke_for_policy(
            source_ir=ir, policy=policy, class_key=class_key, level=level,
            weights=weights, weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
            native_options_binary=native_binary,
            native_options_response=native_options)
    native_equipped_receipt = (
        rogue_native_preflight if rogue_native_preflight is not None else
        _paid_native_equipped_probe(
            root, native_binary, item_check,
            max(0, max_p3_evaluations
                - int(result.get("attempted", 0)) - extra_evaluations))
        if rogue_l20_native else None)
    reasons = list(item_check["blockers"])
    # The native slot sweep is measured separately; it does not erase any
    # unresolved P3 source-policy stat assertion or award an automatic PASS.
    # An item-options source snapshot and Python weighted score alone cannot
    # certify an actual selected-Rust equipped L20 actor. The native pair
    # receipt remains explicit until the authoritative actor matches L20.
    if rogue_l20_native and not (
            native_equipped_receipt
            and native_equipped_receipt.get("actor_checkpoint_verified") is True
            and native_equipped_receipt.get("status") == "PAID_NATIVE_DIFFERENCE"):
        reasons.append("P3_NATIVE_L20_EQUIPPED_SCORE_NOT_ESTABLISHED")
    # The source policy was paid by CombatRuntime, but item scoring does NOT
    # become native equipped-build execution merely because candidate items
    # originated in Rust. Preserve real provenance and the measured receipt.
    status = "FAIL" if reasons else "PASS"
    proof = {}
    if status == "PASS":
        from src.version import SOFTWARE_VERSION
        proof = {"runtime_proof": {
            "executed": True, "engine_revision": "gsim-" + SOFTWARE_VERSION,
            "source_revision": result["source_context_sha256"],
            "run_id": "p3-live-" + str(uuid4())}}
    return {
        "status": status, "reasons": sorted(set(reasons)),
        **proof,
        "production_component": "src.game.checkpoint_p3_smoke.fast_p3_smoke_for_policy",
        "production_engine": "gsim_CombatRuntime",
        "source_profile_production_build": profile_context,
        "real_source_search_attempts": result.get("attempted", 0),
        "real_source_search_evaluated": result.get("evaluated", 0) + extra_evaluations,
        "source_policy_stat_witnesses": source_policy_stat_witnesses,
        "native_equipped_paid_receipt": native_equipped_receipt,
        "native_equipped_paid_attempts": (
            native_equipped_receipt.get("paid_attempts", 0)
            if native_equipped_receipt else 0),
        "p3_shared_budget_attempts": (
            int(result.get("attempted", 0)) + extra_evaluations
            + (native_equipped_receipt.get("paid_attempts", 0)
               if native_equipped_receipt else 0)),
        "p3_native_pair_reserved_attempts": native_pair_reserved,
        # This is the resolver used by the paid source search, not a second
        # P3 applicability rule or an invented zero for absent primary stats.
        "real_stat_probe_axis_selection": result.get("stat_probe_axis_selection"),
        "real_measured_stat_weights": dict(sorted(weights.items())),
        "real_catalogue_legal_items": item_check["legal_item_count"],
        # Compatibility alias for existing gate/recorder consumers. Native
        # options are now an explicit <=2 representative per-slot sample.
        "real_catalogue_top5_items_scored": item_check["tested_item_count"],
        "real_native_representative_items_scored": (
            item_check["tested_item_count"] if item_check["source"] ==
            "MYTHICSIM_NATIVE_ITEM_OPTIONS" else None),
        "real_selected_item_alternatives_by_slot": item_check["slots"],
        "real_catalogue_slots_scored": item_check["slot_count"],
        # Comparable measured unit: one source-legal top-ilvl item x
        # applicable ordinary stat requirement, checked in the real selector.
        # Runtime-paid stat sensitivities establish causal context. Global
        # conditions may still fail P3; this fraction is NOT a gate PASS.
        "reachability_count": item_check["tested_stat_assertions"],
        "pass_count": item_check["verified_stat_assertions"],
        "behavior_probes_executed": result.get("evaluated", 0) + extra_evaluations,
        "partial_scope": (
            "CURRENT_NATIVE_REPRESENTATIVE_ITEM_STAT_WEIGHT_ASSERTIONS"
            if item_check["source"] == "MYTHICSIM_NATIVE_ITEM_OPTIONS"
            else "CURRENT_SOURCE_TOP5_ITEM_STAT_WEIGHT_ASSERTIONS"),
        "coverage_basis": "executed_behavior_assertions",
        "coverage_scope_complete": False,
        "real_item_score_checked": item_check["source"] in (
            "CURRENT_CANONICAL_SQLITE_LEGAL_ITEMS", "MYTHICSIM_NATIVE_ITEM_OPTIONS"),
        "item_options_source": item_check["source"],
        "native_item_options_status": item_check.get("native_item_options_status"),
        "native_unverified_candidate_count": item_check.get("native_unverified_candidate_count", 0),
        "native_excluded_non_client_item_count": item_check.get(
            "native_excluded_non_client_item_count", 0),
        "native_item_options_source": item_check.get("native_item_options_source"),
        "real_measured_stat_weight_axes": sorted(weights),
        "actual_search_result_status": result.get("status"),
        "source_context_sha256": result.get("source_context_sha256"),
        "native_spell_coefficients_source": (
            native_spell_facts.get("source") if native_spell_facts else None),
        "native_spell_coefficients_engine_revision": (
            native_spell_facts.get("engine_revision") if native_spell_facts else None),
        "native_spell_coefficients_applied": native_spell_coefficients_applied,
        "native_spell_coefficients_error": native_spell_coefficients_error,
        "native_paid_winner_spell_probe_enabled": native_fallback_action,
        "native_player_context_id": (
            native_player_context.get("source_context_id")
            if native_player_context else None),
        "native_player_context_scope": (
            native_player_context.get("source_scope")
            if native_player_context else None),
        "native_player_context_kind": (
            native_player_context.get("context_kind")
            if native_player_context else None),
        "native_player_context_race": (
            native_player_context.get("race") if native_player_context else None),
        "native_player_context_base_stats": (
            dict(native_player_context.get("base_stats") or {})
            if native_player_context else {}),
        "native_player_context_resources": (
            dict(native_player_context.get("resources") or {})
            if native_player_context else {}),
        "native_player_context_weapon": (
            dict(native_player_context.get("weapon") or {})
            if native_player_context else {}),
        "native_player_context_unresolved_fields": (
            native_player_context.get("unsupported_fields", ())
            if native_player_context else ()),
    }
