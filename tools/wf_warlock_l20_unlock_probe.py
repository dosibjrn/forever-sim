"""Source-native, paid Warlock L20 P4 talent-unlock diagnostic.

Find an APL action newly *registered by Rust prepare* when only native-source
proposed talent points change, then pay the same two-mob native/world scenario
with and without that action. Registration and ACKed effects are observations,
NOT a claim that Rust emitted a cast event or that P4 passed. No 300s restart.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path


def player(request: dict) -> dict:
    return request["raid"]["parties"][0]["players"][0]


def prepared_apl_ids(binary: Path, request: dict, out: Path,
                     *, runner=subprocess.run) -> set[int] | None:
    """Read Rust's exact prepared APL registry; None means native refusal.

    This does not interpret spellbook, talent, class or gameplay legality.
    Every proposal still goes to native prepare and native world execution.
    """
    out.mkdir(parents=True, exist_ok=True)
    source = out / "source.request.json"
    prepared_path = out / "source.prepared.json"
    source.write_text(json.dumps(request, sort_keys=True) + "\n")
    prepared_path.unlink(missing_ok=True)
    try:
        result = runner([
            str(binary.resolve()), "prepare", "--request",
            str(source.resolve()), "--actor-level", "20",
            "--outfile", str(prepared_path.resolve()),
        ], capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0 or not prepared_path.is_file():
            return None
        prepared = json.loads(prepared_path.read_text())
        spells = prepared["player"]["spells"]
        if not isinstance(spells, list):
            return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError,
            subprocess.TimeoutExpired):
        return None
    ids = set()
    for spell in spells:
        if not isinstance(spell, dict):
            continue
        action = spell.get("action_id")
        spell_id = action.get("spell_id") if isinstance(action, dict) else None
        if (type(spell_id) is int and spell_id > 0
                and "SpellFlagAPL" in spell.get("flags", [])):
            ids.add(spell_id)
    return ids


def find_native_registered_unlock(reference: dict, options: dict, *,
                                  binary: Path, out: Path, seed: int,
                                  max_talents: int = 48,
                                  prepare=prepared_apl_ids,
                                  proposals=None) -> dict:
    """Find a native-prepared talent-dependent APL action, not a rules guess.

    A negative sampled result DOES NOT prove that no reachable unlock exists.
    Neither native get_options nor prepared registration by itself proves a
    successful cast; the downstream paid execution and Rust casts are separate.
    """
    if max_talents < 1:
        raise ValueError("INVALID_TALENT_PREPARE_BUDGET")
    if (player(reference).get("class") != "ClassWarlock"
            or options.get("class") != "warlock" or options.get("level") != 20):
        raise ValueError("WRONG_NATIVE_WARLOCK_L20_SOURCE")
    if proposals is None:
        from tools.wf_warlock_l20_talent_apl_optimizer import (
            proposals_from_native_talents,
        )
        proposals = proposals_from_native_talents
    original_talents = player(reference).get("talentsString", "0-0-0")
    baseline = prepare(binary, reference, out / "baseline_prepare")
    if baseline is None:
        return {"status": "NATIVE_BASELINE_PREPARE_REFUSED",
                "talent_prepares_attempted": 0, "native_prepare_refusals": 1}

    attempted = 0
    refused = 0
    seen = {original_talents}
    for row in proposals(options, original_talents, seed):
        if not isinstance(row, dict):
            continue
        talents = row.get("talents")
        if not isinstance(talents, str) or talents in seen:
            continue
        seen.add(talents)
        if attempted >= max_talents:
            break
        candidate_source = copy.deepcopy(reference)
        player(candidate_source)["talentsString"] = talents
        current = prepare(binary, candidate_source,
                          out / "talent_prepares" / f"{attempted:03d}")
        attempted += 1
        if current is None:
            refused += 1
            continue
        added_ids = sorted(current - baseline)
        if not added_ids:
            continue
        action_id = added_ids[0]
        native_action = {"action": {"castSpell": {
            "spellId": {"spellId": action_id}}}}
        player(candidate_source)["rotation"]["priorityList"] = [
            native_action,
            *copy.deepcopy(player(reference)["rotation"]["priorityList"]),
        ]
        return {
            "status": "NATIVE_TALENT_DEPENDENT_APL_PROPOSAL",
            "talent_prepares_attempted": attempted,
            "native_prepare_refusals": refused,
            "baseline_registered_action_ids": sorted(baseline),
            "talent_registered_action_ids": sorted(current),
            "new_native_registered_action_id": action_id,
            "original_talents": original_talents,
            "proposed_talents": talents,
            "candidate_source": candidate_source,
        }
    return {
        "status": "NO_DIFFERENTIAL_NATIVE_APL_ACTION_IN_SAMPLED_TALENTS",
        "talent_prepares_attempted": attempted,
        "native_prepare_refusals": refused,
        "baseline_registered_action_ids": sorted(baseline),
        "native_source_unlocked_actions_available": None,
    }


def run_probe(reference: dict, options: dict, *, binary: Path, out: Path,
              seed: int = 20261109, max_talents: int = 48,
              timeout: float = 120.0, prepare=prepared_apl_ids,
              proposals=None, chain=None) -> dict:
    """Execute a *fresh*, matched native two-target policy comparison.

    The receipt deliberately never asserts `native_representative_unlocked_cast_compared`:
    native ACKed damage effects alone are NOT cast-event evidence.
    """
    if timeout <= 0:
        raise ValueError("INVALID_PAID_SCREEN_TIMEOUT")
    if chain is None:
        from tools.wf_warlock_l20_native_cold import paid_chain
        chain = paid_chain
    out.mkdir(parents=True, exist_ok=True)
    selected = find_native_registered_unlock(
        reference, options, binary=binary, out=out / "discovery",
        seed=seed, max_talents=max_talents,
        prepare=prepare, proposals=proposals)
    summary = {key: copy.deepcopy(value) for key, value in selected.items()
               if key != "candidate_source"}
    summary.update(kind="warlock_l20_native_talent_unlock_paid_probe",
                   native_source_revision=options.get("source_revision"),
                   engine_binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                   source_request_sha256=hashlib.sha256(
                       json.dumps(reference, sort_keys=True).encode()).hexdigest(),
                   gate_recorded=False, p4_pass=False)
    if selected["status"] == "NATIVE_TALENT_DEPENDENT_APL_PROPOSAL":
        alternate = selected["candidate_source"]
        (out / "candidate.request.json").write_text(
            json.dumps(alternate, sort_keys=True) + "\n")
        policy = {"health_threshold": 0.5, "mana_threshold": 0.1}
        trials = {
            "baseline": {"source": copy.deepcopy(reference), "recovery": policy},
            "talent_action": {"source": alternate, "recovery": policy},
        }
        results = {}
        for label, candidate in trials.items():
            try:
                receipt = chain(binary, candidate, out / label, targets=2,
                                timeout=timeout)
                results[label] = {"status": "NATIVE_PAID_2_TARGET_COMPLETE",
                                  "seconds_per_mob": receipt["seconds_per_mob"],
                                  "native_receipt": receipt}
            except Exception as exc:
                raw = getattr(exc, "raw_response", None)
                results[label] = {
                    "status": ("NATIVE_PAID_2_TARGET_REFUSED"
                               if isinstance(raw, dict)
                               else "NATIVE_PAID_2_TARGET_ERROR"),
                    "reason": str(exc)[-1200:],
                    "native_response": raw if isinstance(raw, dict) else None,
                }
        summary["paid_comparison"] = results
        if all(row["status"] == "NATIVE_PAID_2_TARGET_COMPLETE"
               for row in results.values()):
            summary["status"] = "NATIVE_PAID_2_TARGET_POLICIES_COMPARED"
        else:
            summary["status"] = "NATIVE_PAID_POLICY_REFUSAL_RETAINED"
        # Forward real native ACK observations without inventing casts.
        # An incomplete native chain may still have genuinely ACKed effects.
        # The paid scorer keeps them on the structured refusal response, not
        # a successful receipt. Report that observation without calling it a
        # cast/result proof or treating an incomplete chain as scoreable.
        challenger = results["talent_action"]
        native_response = (challenger.get("native_receipt")
                           or challenger.get("native_response") or {})
        native_effects = native_response.get(
            "native_source_damage_effects_by_caster", {})
        action_id = selected["new_native_registered_action_id"]
        summary["new_native_action_acked_damage_effects"] = (
            native_effects.get("player", {}).get(f"Spell-{action_id}")
            if isinstance(native_effects, dict)
            and isinstance(native_effects.get("player"), dict) else None)
        summary["native_cast_result_evidence_complete"] = False
    (out / "unlock_probe_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n")
    return summary
