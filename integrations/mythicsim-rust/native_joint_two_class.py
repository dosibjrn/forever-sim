#!/usr/bin/env python3
"""Two-class native Rust JOINT diagnostic using the shared search core.

Python supplies a bounded proposal domain from same-class source requests.
It does not consult a Python item index or certify game legality or P7.5;
MythicSim Rust alone decides whether each exact candidate is valid and
supported. No mocked scorer is permitted in this integration path.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import subprocess
import time
from pathlib import Path

from apl_mutation import mutate_apl
from native_gear_adapter import GearRejected, NativeGearAdapter
from native_joint_composition import (
    MISSING_TALENT_STRING, CandidateAxis, JointCandidateAdapter, search_joint,
)
from native_l60_matrix import (
    HEAL, TANK, ROOT, create_inventory, digest, fingerprint, player,
)
from native_executor import objective_action_fields, objective_metric_path, run
from native_source_donors import load_source_donor_fixtures


def _write_native_failure(outdir: Path, request_sha256: str,
                          effective_request: dict, exc: Exception) -> dict:
    """Persist failed request plus any native response without inventing a score."""
    request_path = outdir / ("failed_" + request_sha256 + ".json")
    request_path.write_text(json.dumps(effective_request, indent=2) + "\n")
    record = {
        "effective_request_sha256": request_sha256,
        "native_status": getattr(exc, "status", "ERROR"),
        "error": str(exc)[-1200:],
    }
    raw = getattr(exc, "raw_response", None)
    if raw is not None:
        response_path = outdir / ("failed_" + request_sha256 + ".response.json")
        response_path.write_text(json.dumps(raw, indent=2) + "\n")
        record["raw_response_sha256"] = fingerprint(raw)
        record["response_file"] = response_path.name
        elapsed = getattr(exc, "elapsed_s", None)
        if isinstance(elapsed, (int, float)) and math.isfinite(float(elapsed)):
            record["native_duration_s"] = float(elapsed)
    return record


def objective_for_profile(profile_id: str) -> str:
    """Select the native result metric for an existing fixed profile role."""
    if profile_id in HEAL:
        return "HPS"
    if profile_id in TANK:
        return "TPS"
    return "DPS"


def _native_positive_source_casts(source_actions: list[dict],
                                  native_response: dict,
                                  objective: str = "DPS") -> list[dict]:
    """Find source APL casts with positive native output for this objective.

    The selected engine's per-action receipt is the witness: damage for DPS,
    healing/shielding for HPS, and generated threat for TPS. HPS/TPS retain the
    full source cast object so target selection is not lost when a fallback is
    inserted. No spell-name or Python game-rule inference is used.
    """
    fields = objective_action_fields(objective)
    try:
        native_actions = native_response["result"]["raidMetrics"]["parties"][0]["players"][0]["actions"]
    except (KeyError, IndexError, TypeError):
        return []
    if not isinstance(native_actions, list):
        return []
    positive_ids = set()
    for action in native_actions:
        if not isinstance(action, dict):
            continue
        identity = action.get("id", {})
        spell_id = identity.get("spellId") if isinstance(identity, dict) else None
        if not isinstance(spell_id, int) or isinstance(spell_id, bool):
            continue
        targets = action.get("targets", [])
        if not isinstance(targets, list):
            continue
        if any(
            isinstance(target.get(field), (int, float))
            and not isinstance(target.get(field), bool)
            and math.isfinite(float(target[field]))
            and target[field] > 0
            for target in targets if isinstance(target, dict)
            for field in fields
        ):
            positive_ids.add(spell_id)
    witnesses = []
    seen = set()
    objective = str(objective).upper()
    for entry in source_actions:
        action = entry.get("action", {}) if isinstance(entry, dict) else {}
        cast = action.get("castSpell") if isinstance(action, dict) else None
        identity = cast.get("spellId") if isinstance(cast, dict) else None
        if not isinstance(identity, dict):
            continue
        spell_id = identity.get("spellId")
        witness = identity if objective == "DPS" else cast
        key = json.dumps(witness, sort_keys=True, separators=(",", ":"))
        if spell_id in positive_ids and key not in seen:
            witnesses.append(copy.deepcopy(witness))
            seen.add(key)
    return witnesses


def _ensure_native_objective_action(actions: list[dict],
                                     witnesses: list[dict], rng,
                                     objective: str = "DPS", *,
                                     source_actions: list[dict]) -> list[dict]:
    """Retain native-positive source actions without stripping their guards.

    The native receipt identifies a positive cast identity, not permission to
    rewrite that source action. Reinsert the exact source action (including its
    condition and target) when the candidate omits or mutates it. Conditional
    witnesses remain conditional; an unguarded fallback is allowed only when
    the source APL itself contains that exact unguarded action.
    """
    if not witnesses:
        return actions
    objective = str(objective).upper()

    def action_identity(cast):
        return cast.get("spellId") if objective == "DPS" else cast

    allowed = {
        json.dumps(witness, sort_keys=True, separators=(",", ":"))
        for witness in witnesses
    }
    source_entries_by_identity = {}
    source_entry_keys_by_identity = {}
    for entry in source_actions:
        action = entry.get("action", {}) if isinstance(entry, dict) else None
        cast = action.get("castSpell") if isinstance(action, dict) else None
        if not isinstance(cast, dict):
            continue
        identity_key = json.dumps(
            action_identity(cast), sort_keys=True, separators=(",", ":")
        )
        if identity_key not in allowed:
            continue
        entry_key = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        known = source_entry_keys_by_identity.setdefault(identity_key, set())
        if entry_key in known:
            continue
        known.add(entry_key)
        source_entries_by_identity.setdefault(identity_key, []).append(
            copy.deepcopy(entry)
        )

    missing = allowed - set(source_entries_by_identity)
    if missing:
        raise ValueError(
            "NATIVE_OBJECTIVE_WITNESS_NOT_PRESENT_IN_EXACT_SOURCE_APL"
        )

    conditional_or_opaque = []
    source_witness_actions = []
    unconditional = []
    seen_witness_actions = set()
    for entry in actions:
        action = entry.get("action", {}) if isinstance(entry, dict) else {}
        cast = action.get("castSpell")
        is_cast = isinstance(cast, dict)
        identity_key = json.dumps(
            action_identity(cast) if is_cast else None,
            sort_keys=True,
            separators=(",", ":"),
        )
        if is_cast and identity_key in allowed:
            # Keep only exact source action/condition variants. A changed or
            # unguarded witness is discarded and restored from source below.
            entry_key = json.dumps(entry, sort_keys=True, separators=(",", ":"))
            if (entry_key in source_entry_keys_by_identity[identity_key]
                    and entry_key not in seen_witness_actions):
                source_witness_actions.append(copy.deepcopy(entry))
                seen_witness_actions.add(entry_key)
            continue
        if not is_cast or "condition" in action:
            conditional_or_opaque.append(copy.deepcopy(entry))
        else:
            unconditional.append(copy.deepcopy(entry))

    # A positive source action may have been dropped by structural mutation.
    # Restore every exact source variant for the witnessed cast identity.
    for witness in witnesses:
        identity_key = json.dumps(
            witness, sort_keys=True, separators=(",", ":")
        )
        for entry in source_entries_by_identity[identity_key]:
            entry_key = json.dumps(entry, sort_keys=True, separators=(",", ":"))
            if entry_key not in seen_witness_actions:
                source_witness_actions.append(copy.deepcopy(entry))
                seen_witness_actions.add(entry_key)

    source_witness_actions = source_witness_actions[:20]
    prefix_room = 20 - len(source_witness_actions)
    conditional_or_opaque = conditional_or_opaque[:prefix_room]
    utility_room = 20 - len(conditional_or_opaque) - len(source_witness_actions)
    unconditional = unconditional[:utility_room]
    return conditional_or_opaque + source_witness_actions + unconditional


def _ensure_native_damage_action(actions: list[dict], witnesses: list[dict],
                                 rng, objective: str = "DPS", *,
                                 source_actions: list[dict]) -> list[dict]:
    """Compatibility alias for the historical DPS-named helper."""
    return _ensure_native_objective_action(
        actions, witnesses, rng, objective=objective,
        source_actions=source_actions,
    )


def native_payload(candidate: dict, iterations: int, seed: int) -> dict:
    payload = copy.deepcopy(candidate)
    payload["simOptions"]["iterations"] = iterations
    payload["simOptions"]["randomSeed"] = str(seed)
    return payload


def native_score_request(
    binary: Path,
    candidate: dict,
    iterations: int,
    seed: int,
    rng_mode: str,
    deadline: float,
    *,
    objective: str = "DPS",
    runner=run,
) -> tuple[dict, dict]:
    """Score one exact request with an explicit balanced RNG and native objective."""
    if rng_mode != "balanced":
        raise ValueError("JOINT_OPTIMIZER_REQUIRES_EXPLICIT_BALANCED_RNG")
    metric_path = objective_metric_path(objective)
    effective = native_payload(candidate, iterations, seed)
    expected_sha = fingerprint(effective)
    score, raw, elapsed, scored_sha = runner(
        binary, candidate, iterations, seed, rng_mode, deadline,
        objective=objective,
    )
    if scored_sha != expected_sha:
        raise RuntimeError("Native payload/score provenance mismatch")
    if not math.isfinite(float(score)):
        raise RuntimeError("Native evaluator returned a non-finite score")
    return {
        "effective_request_sha256": expected_sha,
        "score": float(score),
        "objective": str(objective).upper(),
        "native_metric_path": metric_path,
        "rng_mode": rng_mode,
        "iterations": iterations,
        "seed": seed,
        "native_duration_s": elapsed,
        "native_status": "VALID",
        "raw_response_sha256": fingerprint(raw),
    }, raw


def _probe_native_objective_donor_witnesses(
    binary: Path,
    reference: dict,
    source_request_records: list[dict],
    baseline_witnesses: list[dict],
    *,
    iterations: int,
    seed: int,
    objective: str,
    baseline_apl_source_path: str | None = None,
    outdir: Path | None = None,
    max_probes: int = 24,
    max_variants_per_talent: int = 2,
    score_request=native_score_request,
) -> tuple[dict, list[dict], dict]:
    """Pay native probes for source APLs across source-observed talent builds.

    First cross each alternate source talent build with the reference's exact
    source APL. Then try each donor's own APL as a fallback. APL/talent
    combinations enter the candidate domain only after MythicSim accepts the
    exact request and returns an objective-positive action receipt.
    """
    objective = str(objective).upper()
    objective_metric_path(objective)
    original = player(reference)
    baseline_talent = original.get("talentsString", MISSING_TALENT_STRING)
    baseline_apl = original.get("rotation", {}).get("priorityList", [])
    baseline_apl_sha = fingerprint(baseline_apl)
    witnesses_by_talent = {
        baseline_talent: copy.deepcopy(baseline_witnesses or [])
    }
    seen = set()
    attempts_by_talent = {}
    probes = []
    positive_apls_by_talent = {}
    probe_dir = None
    if outdir is not None:
        probe_dir = Path(outdir) / "donor_probes"
        probe_dir.mkdir(parents=True, exist_ok=True)

    # The baseline APL is a source-observed axis in its own right. Probe it
    # against each alternate source talent build before donor-specific APLs;
    # otherwise damage-oriented donor APLs can hide reachable healing builds.
    cross_build_records = []
    cross_build_talents = set()
    if isinstance(baseline_apl, list) and baseline_apl:
        for source_record in source_request_records:
            if isinstance(source_record, dict) and isinstance(source_record.get("request"), dict):
                source_request = source_record["request"]
                source_path = source_record.get("source_path")
            else:
                source_request = source_record
                source_path = None
            if not isinstance(source_request, dict):
                continue
            try:
                source_player = player(source_request)
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            if source_player.get("class") != original.get("class"):
                continue
            talent = source_player.get("talentsString", MISSING_TALENT_STRING)
            if not (isinstance(talent, str) or talent is None
                    or talent == MISSING_TALENT_STRING):
                continue
            if talent == baseline_talent or talent in cross_build_talents:
                continue
            cross_build_talents.add(talent)
            cross_request = copy.deepcopy(reference)
            cross_player = player(cross_request)
            if talent == MISSING_TALENT_STRING:
                cross_player.pop("talentsString", None)
            else:
                cross_player["talentsString"] = copy.deepcopy(talent)
            cross_player["rotation"]["priorityList"] = copy.deepcopy(baseline_apl)
            cross_build_records.append({
                "request": cross_request,
                "source_path": source_path,
                "apl_source_path": baseline_apl_source_path or "REFERENCE_SOURCE_APL",
                "probe_kind": "REFERENCE_APL_CROSS_BUILD",
            })

    # Up to 12 distinct source builds may each need both variants: the
    # reference APL cross-build first, then that build's donor-APL fallback.
    # A 12-probe total cap starves every fallback after 12 cross-build misses.
    ordered_source_records = cross_build_records + source_request_records
    for source_record in ordered_source_records:
        if isinstance(source_record, dict) and isinstance(source_record.get("request"), dict):
            source_request = source_record["request"]
            source_path = source_record.get("source_path")
            apl_source_path = source_record.get("apl_source_path", source_path)
            probe_kind = source_record.get("probe_kind", "SOURCE_DONOR_APL")
        else:
            source_request = source_record
            source_path = None
            apl_source_path = None
            probe_kind = "SOURCE_DONOR_APL"
        if not isinstance(source_request, dict):
            continue
        try:
            source_player = player(source_request)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if source_player.get("class") != original.get("class"):
            continue
        talent = source_player.get("talentsString", MISSING_TALENT_STRING)
        if not (isinstance(talent, str) or talent is None
                or talent == MISSING_TALENT_STRING):
            continue
        rotation = source_player.get("rotation")
        source_actions = (
            rotation.get("priorityList") if isinstance(rotation, dict) else None
        )
        if not isinstance(source_actions, list) or not source_actions:
            continue
        apl_sha = fingerprint(source_actions)
        if talent == baseline_talent and apl_sha == baseline_apl_sha:
            continue
        probe_key = (talent, apl_sha)
        if probe_key in seen:
            continue
        seen.add(probe_key)
        if witnesses_by_talent.get(talent):
            continue
        if attempts_by_talent.get(talent, 0) >= max_variants_per_talent:
            continue
        if len(probes) >= max_probes:
            break
        attempts_by_talent[talent] = attempts_by_talent.get(talent, 0) + 1

        probe = copy.deepcopy(reference)
        probe_player = player(probe)
        if talent == MISSING_TALENT_STRING:
            probe_player.pop("talentsString", None)
        else:
            probe_player["talentsString"] = copy.deepcopy(talent)
        probe_player["rotation"]["priorityList"] = copy.deepcopy(source_actions)
        effective = native_payload(probe, iterations, seed)
        request_sha = fingerprint(effective)
        if probe_dir is not None:
            (probe_dir / (request_sha + ".request.json")).write_text(
                json.dumps(effective, indent=2) + "\n"
            )
        try:
            record, raw = score_request(
                binary, probe, iterations, seed, "balanced",
                time.monotonic() + 30.0, objective=objective,
            )
            witnesses = _native_positive_source_casts(
                source_actions, raw, objective=objective
            )
            selected = witnesses_by_talent.setdefault(talent, [])
            known = {
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in selected
            }
            for witness in witnesses:
                key = json.dumps(witness, sort_keys=True, separators=(",", ":"))
                if key not in known:
                    selected.append(copy.deepcopy(witness))
                    known.add(key)
            if witnesses:
                known_apls = {
                    fingerprint(actions)
                    for actions in positive_apls_by_talent.get(talent, [])
                }
                if apl_sha not in known_apls:
                    positive_apls_by_talent.setdefault(talent, []).append(
                        copy.deepcopy(source_actions)
                    )
            if probe_dir is not None:
                (probe_dir / (request_sha + ".response.json")).write_text(
                    json.dumps(raw, indent=2) + "\n"
                )
            probes.append({
                "source_path": source_path,
                "apl_source_path": apl_source_path,
                "probe_kind": probe_kind,
                "talentsString": (
                    "<MISSING_TALENT_STRING>"
                    if talent == MISSING_TALENT_STRING else talent
                ),
                "status": "VALID",
                "objective": objective,
                "native_metric_path": objective_metric_path(objective),
                "score": record.get("score"),
                "effective_request_sha256": record.get("effective_request_sha256"),
                "raw_response_sha256": record.get("raw_response_sha256"),
                "positive_witnesses": witnesses,
            })
        except Exception as exc:
            failure = (
                _write_native_failure(probe_dir, request_sha, effective, exc)
                if probe_dir is not None else None
            )
            probes.append({
                "source_path": source_path,
                "apl_source_path": apl_source_path,
                "probe_kind": probe_kind,
                "talentsString": (
                    "<MISSING_TALENT_STRING>"
                    if talent == MISSING_TALENT_STRING else talent
                ),
                "status": getattr(exc, "status", "ERROR"),
                "error": str(exc)[-500:],
                "failure_receipt": failure,
            })
    return witnesses_by_talent, probes, positive_apls_by_talent


def source_bounded_adapter(
    class_key: str, reference: dict, same_class: list[dict], *,
    donor_fixtures: list[dict] | None = None,
    native_objective_witnesses: list[dict] | None = None,
    native_damage_witnesses: list[dict] | None = None,
    native_objective_witnesses_by_talentsString: dict | None = None,
    native_objective_source_apls_by_talentsString: dict | None = None,
    objective: str = "DPS",
) -> tuple[JointCandidateAdapter, dict]:
    """Use same-class source proposals; Rust owns all build legality."""
    objective = str(objective).upper()
    objective_metric_path(objective)
    if native_objective_witnesses is not None and native_damage_witnesses is not None:
        raise ValueError("Pass only one native objective witness argument")
    supplied_witnesses = (
        native_objective_witnesses
        if native_objective_witnesses is not None else native_damage_witnesses
    )
    original = player(reference)
    extra_same_class = [
        fixture for fixture in (donor_fixtures or [])
        if fixture.get("class_name") == original.get("class")
        and isinstance(fixture.get("request"), dict)
    ]
    donor_requests = [fixture["request"] for fixture in extra_same_class]
    source_requests = same_class + donor_requests
    gear = NativeGearAdapter(class_key, reference, source_requests)
    if not gear.mutable_indices:
        raise ValueError("BLOCKED_GEAR_POOL: no source-observed alternate item")

    base_gear = copy.deepcopy(original["equipment"]["items"])
    source_talents = set()
    talents = set()
    source_casts_by_talentsString: dict[object, set[str]] = {}
    source_apl_by_talentsString: dict[object, list[dict]] = {}
    source_apl_keys_by_talentsString: dict[object, set[str]] = {}

    def talent_sort_key(value):
        if value == MISSING_TALENT_STRING:
            return (0, "")
        if value is None:
            return (1, "")
        return (2, str(value))

    def talent_label(value):
        if value == MISSING_TALENT_STRING:
            return "<MISSING_TALENT_STRING>"
        if value is None:
            return "<NULL_TALENT_STRING>"
        return value

    for request in source_requests:
        try:
            source_player = player(request)
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if source_player.get("class") != original["class"]:
            continue
        source_talent = source_player.get("talentsString", MISSING_TALENT_STRING)
        if not (isinstance(source_talent, str)
                or source_talent is None
                or source_talent == MISSING_TALENT_STRING):
            continue
        source_talents.add(source_talent)
        source_casts = source_casts_by_talentsString.setdefault(source_talent, set())
        source_apl = source_apl_by_talentsString.setdefault(source_talent, [])
        source_apl_keys = source_apl_keys_by_talentsString.setdefault(source_talent, set())
        rotation = source_player.get("rotation")
        priority_list = rotation.get("priorityList", []) if isinstance(rotation, dict) else []
        if isinstance(priority_list, list):
            for entry in priority_list:
                if not isinstance(entry, dict):
                    continue
                action = entry.get("action", {})
                if not isinstance(action, dict):
                    continue
                entry_key = json.dumps(entry, sort_keys=True, separators=(",", ":"))
                if entry_key not in source_apl_keys:
                    source_apl.append(copy.deepcopy(entry))
                    source_apl_keys.add(entry_key)
                cast = action.get("castSpell")
                if isinstance(cast, dict) and cast:
                    source_casts.add(json.dumps(
                        cast, sort_keys=True, separators=(",", ":")
                    ))
        # Missing talentString is a source-observed candidate too. Preserve
        # its absence in the request; only MythicSim can accept or refuse it.
        talents.add(source_talent)

    # Add only source APL variants that were paid and returned a native-positive
    # objective witness for this exact talent build. This permits an independently
    # observed APL axis to combine with a talent donor without guessing legality.
    native_objective_source_apl_hashes = {}
    for source_talent, apl_variants in (
        native_objective_source_apls_by_talentsString or {}
    ).items():
        if source_talent not in source_talents or not isinstance(apl_variants, list):
            continue
        hashes = []
        source_casts = source_casts_by_talentsString.setdefault(source_talent, set())
        source_apl = source_apl_by_talentsString.setdefault(source_talent, [])
        source_apl_keys = source_apl_keys_by_talentsString.setdefault(source_talent, set())
        for priority_list in apl_variants:
            if not isinstance(priority_list, list) or not priority_list:
                continue
            apl_sha = fingerprint(priority_list)
            if apl_sha not in hashes:
                hashes.append(apl_sha)
            for entry in priority_list:
                if not isinstance(entry, dict):
                    continue
                action = entry.get("action", {})
                if not isinstance(action, dict):
                    continue
                entry_key = json.dumps(entry, sort_keys=True, separators=(",", ":"))
                if entry_key not in source_apl_keys:
                    source_apl.append(copy.deepcopy(entry))
                    source_apl_keys.add(entry_key)
                cast = action.get("castSpell")
                if isinstance(cast, dict) and cast:
                    source_casts.add(json.dumps(
                        cast, sort_keys=True, separators=(",", ":")
                    ))
        if hashes:
            native_objective_source_apl_hashes[source_talent] = hashes

    talents = sorted(talents, key=talent_sort_key)
    original_talents = original["talentsString"]
    if original_talents not in source_talents or len(talents) < 2:
        raise ValueError(
            "BLOCKED_TALENTS: need a source-observed baseline and two "
            "same-class candidate talent strings"
        )

    native_objective_witnesses = [
        copy.deepcopy(witness) for witness in (supplied_witnesses or [])
        if isinstance(witness, dict) and witness
    ]
    witness_label = {"DPS": "damage", "HPS": "healing", "TPS": "threat"}[objective]
    witness_code = (
        "BLOCKED_NATIVE_DAMAGE_WITNESS" if objective == "DPS"
        else "BLOCKED_NATIVE_" + objective + "_WITNESS"
    )

    def witness_key(witness):
        identity = {"spellId": witness} if objective == "DPS" else witness
        return json.dumps(identity, sort_keys=True, separators=(",", ":"))

    candidate_talents = set(talents)
    common_cast_keys = set()
    common_witnesses = []
    if native_objective_witnesses_by_talentsString is None:
        original_source_casts = source_casts_by_talentsString.get(original_talents, set())
        native_witness_keys = []
        for witness in native_objective_witnesses:
            key = witness_key(witness)
            if key in original_source_casts and key not in native_witness_keys:
                native_witness_keys.append(key)

        supported_build_sets = []
        for witness_identity_key in native_witness_keys:
            builds = [
                talent for talent in talents
                if witness_identity_key in source_casts_by_talentsString.get(talent, set())
            ]
            if len(builds) >= 2:
                supported_build_sets.append((len(builds), witness_identity_key, builds))
        if not supported_build_sets:
            raise ValueError(
                f"{witness_code}: no baseline-positive source {witness_label} cast "
                "is present in the reference and at least two same-class "
                "source candidate talent strings"
            )
        _support_count, selected_witness_key, selected_builds = max(
            supported_build_sets, key=lambda row: row[0]
        )
        talents = sorted(selected_builds, key=talent_sort_key)
        excluded_talents = sorted(
            candidate_talents - set(talents), key=talent_sort_key
        )
        selected_talent_strings = list(dict.fromkeys(
            [original_talents] + [talent for talent in talents if talent != original_talents]
        ))
        common_cast_keys = set(original_source_casts)
        for talent in selected_talent_strings[1:]:
            common_cast_keys.intersection_update(
                source_casts_by_talentsString.get(talent, set())
            )
        if not common_cast_keys or selected_witness_key not in common_cast_keys:
            raise ValueError(
                "BLOCKED_SOURCE_APL: selected talent builds have no common "
                "baseline-positive source cast identity"
            )

        seen_common_witnesses = set()
        for witness in native_objective_witnesses:
            key = witness_key(witness)
            if key in common_cast_keys and key not in seen_common_witnesses:
                common_witnesses.append(copy.deepcopy(witness))
                seen_common_witnesses.add(key)
        if not common_witnesses:
            raise ValueError(
                f"{witness_code}: selected talent builds have no common "
                f"baseline-positive source {witness_label} cast"
            )
        objective_witnesses_by_talent = {
            talent: common_witnesses for talent in selected_talent_strings
        }
    else:
        supplied_by_talent = native_objective_witnesses_by_talentsString
        objective_witnesses_by_talent = {}
        for talent in talents:
            source_casts = source_casts_by_talentsString.get(talent, set())
            selected = []
            seen_selected = set()
            for witness in supplied_by_talent.get(talent, []):
                if not isinstance(witness, dict) or not witness:
                    continue
                key = witness_key(witness)
                if key in source_casts and key not in seen_selected:
                    selected.append(copy.deepcopy(witness))
                    seen_selected.add(key)
            if selected:
                objective_witnesses_by_talent[talent] = selected
        if original_talents not in objective_witnesses_by_talent:
            raise ValueError(
                f"{witness_code}: baseline talent build has no native-positive "
                f"source {witness_label} cast"
            )
        selected_builds = sorted(
            objective_witnesses_by_talent, key=talent_sort_key
        )
        if len(selected_builds) < 2:
            raise ValueError(
                f"{witness_code}: need at least two source talent builds with "
                f"native-positive {witness_label} casts"
            )
        talents = selected_builds
        excluded_talents = sorted(
            candidate_talents - set(talents), key=talent_sort_key
        )
        selected_talent_strings = list(dict.fromkeys(
            [original_talents] + [talent for talent in talents if talent != original_talents]
        ))
        common_cast_keys = set.intersection(*[
            set(source_casts_by_talentsString.get(talent, set()))
            for talent in selected_talent_strings
        ])
        common_witness_keys = set.intersection(*[
            {witness_key(witness) for witness in objective_witnesses_by_talent[talent]}
            for talent in selected_talent_strings
        ])
        first_build_witnesses = objective_witnesses_by_talent[selected_talent_strings[0]]
        common_witnesses = [
            copy.deepcopy(witness) for witness in first_build_witnesses
            if witness_key(witness) in common_witness_keys
        ]
    alternate = [t for t in talents if t != original_talents]

    gear_donor_fixtures_scanned = [
        {
            "source_path": fixture["source_path"],
            "source_sha256": fixture["source_sha256"],
            "item_count": fixture["item_count"],
        }
        for fixture in extra_same_class
        if fixture.get("item_count") == len(base_gear)
    ]
    talent_donor_fixtures = []
    for fixture in extra_same_class:
        donor_player = player(fixture["request"])
        has_talent_string = "talentsString" in donor_player
        talent_donor_fixtures.append({
            "source_path": fixture["source_path"],
            "source_sha256": fixture["source_sha256"],
            "talent_string_present": has_talent_string,
            "talentsString": donor_player.get("talentsString"),
            "talents_sha256": (
                fingerprint(donor_player.get("talentsString"))
                if has_talent_string else None
            ),
            "source_type": fixture.get("source_type", "PINNED_SOURCE_FIXTURE"),
            "native_response_sha256": fixture.get("native_response_sha256"),
            "native_positive_damage_witnesses": fixture.get("native_positive_damage_witnesses", []),
            "talent_source_repository": fixture.get("talent_source_repository"),
            "talent_source_pull_request": fixture.get("talent_source_pull_request"),
            "talent_source_commit": fixture.get("talent_source_commit"),
            "talent_source_path": fixture.get("talent_source_path"),
            "talent_source_blob_sha": fixture.get("talent_source_blob_sha"),
            "talent_source_url": fixture.get("talent_source_url"),
            "talent_preset_name": fixture.get("talent_preset_name"),
            "composed_over_profile": fixture.get("composed_over_profile"),
        })

    def make_gear(rng):
        request, _audit = gear.mutate_one(rng)
        return copy.deepcopy(player(request)["equipment"]["items"])

    def mutate_gear(current, rng):
        request = copy.deepcopy(reference)
        player(request)["equipment"]["items"] = copy.deepcopy(current)
        try:
            updated, _audit = gear.mutate_from(request, rng)
        except GearRejected:
            return make_gear(rng)
        return copy.deepcopy(player(updated)["equipment"]["items"])

    def gear_legal(value):
        request = copy.deepcopy(reference)
        player(request)["equipment"]["items"] = copy.deepcopy(value)
        try:
            gear.validate(request)
            return True
        except (GearRejected, KeyError, ValueError, TypeError):
            return False

    def cold_talent(rng):
        return rng.choice(alternate)

    def mutate_talent(current, rng):
        choices = [t for t in talents if t != current]
        return rng.choice(choices)

    def talent_legal(value):
        # This is only source-corpus membership, not a game-legality verdict.
        # Native Rust decides whether the exact talent string can be prepared
        # and scored when the candidate reaches the evaluator.
        return value == original["talentsString"] or value in talents


    def cast_identity_key(cast):
        if not isinstance(cast, dict) or not cast:
            return None
        return json.dumps(cast, sort_keys=True, separators=(",", ":"))

    def apl_cast_identity_keys(actions):
        return {
            key
            for entry in actions if isinstance(entry, dict)
            for action in [entry.get("action", {})]
            if isinstance(action, dict)
            for cast in [action.get("castSpell")]
            if (key := cast_identity_key(cast)) is not None
        }

    def source_apl_for_candidate(candidate_context):
        candidate_player = player(candidate_context)
        talent_string = candidate_player.get("talentsString", MISSING_TALENT_STRING)
        source_actions = source_apl_by_talentsString.get(talent_string, [])
        if not source_actions:
            raise ValueError("BLOCKED_SOURCE_APL: selected talent build has no source APL")
        return talent_string, source_actions

    def filter_to_selected_source_actions(actions, source_actions, source_casts):
        source_noncast_keys = {
            json.dumps(entry["action"], sort_keys=True, separators=(",", ":"))
            for entry in source_actions
            if isinstance(entry, dict)
            and isinstance(entry.get("action"), dict)
            and "castSpell" not in entry["action"]
        }
        filtered = []
        for entry in actions:
            action = entry.get("action", {}) if isinstance(entry, dict) else {}
            if not isinstance(action, dict):
                continue
            cast = action.get("castSpell")
            if isinstance(cast, dict):
                if cast_identity_key(cast) in source_casts:
                    filtered.append(copy.deepcopy(entry))
            elif "castSpell" not in action:
                key = json.dumps(action, sort_keys=True, separators=(",", ":"))
                if key in source_noncast_keys:
                    filtered.append(copy.deepcopy(entry))
        return filtered

    def cold_apl(rng, candidate_context):
        talent_string, source_actions = source_apl_for_candidate(candidate_context)
        current_apl = player(candidate_context)["rotation"]["priorityList"]
        for _ in range(8):
            actions = _ensure_native_objective_action(
                mutate_apl(None, source_actions, rng, cold=True),
                objective_witnesses_by_talent.get(talent_string, []),
                rng,
                objective=objective,
                source_actions=source_actions,
            )
            if actions != current_apl:
                return actions
        raise ValueError("BLOCKED_APL: no different selected-build source action generated")

    def mutate_apl_axis(current, rng, candidate_context):
        talent_string, source_actions = source_apl_for_candidate(candidate_context)
        selected_casts = source_casts_by_talentsString.get(talent_string, set())
        current = filter_to_selected_source_actions(
            current, source_actions, selected_casts
        )
        if len(current) < 2:
            updated = mutate_apl(None, source_actions, rng, cold=True)
        else:
            updated = mutate_apl(current, source_actions, rng)
        return _ensure_native_objective_action(
            updated,
            objective_witnesses_by_talent.get(talent_string, []),
            rng,
            objective=objective,
            source_actions=source_actions,
        )

    def apl_legal(value):
        # This is a request-shape check, not a spell/APL legality decision.
        # MythicSim Rust accepts or refuses the exact proposed APL.
        return isinstance(value, list) and bool(value)

    def joint_legal(candidate):
        candidate_player = player(candidate)
        talent_string = candidate_player.get("talentsString", MISSING_TALENT_STRING)
        source_casts = source_casts_by_talentsString.get(talent_string)
        if source_casts is None:
            return False
        candidate_apl = candidate_player["rotation"]["priorityList"]
        candidate_casts = apl_cast_identity_keys(candidate_apl)
        if not candidate_casts.issubset(source_casts):
            return False

        eligible_witness_keys = {
            witness_key(witness)
            for witness in objective_witnesses_by_talent.get(talent_string, [])
        }
        source_witness_action_keys = set()
        for entry in source_apl_by_talentsString.get(talent_string, []):
            action = entry.get("action", {}) if isinstance(entry, dict) else None
            cast = action.get("castSpell") if isinstance(action, dict) else None
            if not isinstance(cast, dict):
                continue
            witness_identity = cast.get("spellId") if objective == "DPS" else cast
            if witness_key(witness_identity) in eligible_witness_keys:
                source_witness_action_keys.add(
                    json.dumps(entry, sort_keys=True, separators=(",", ":"))
                )
        has_exact_source_native_witness = any(
            json.dumps(entry, sort_keys=True, separators=(",", ":"))
            in source_witness_action_keys
            for entry in candidate_apl
        )
        return (
            candidate_player["class"] == original["class"]
            and gear_legal(candidate_player["equipment"]["items"])
            and talent_legal(talent_string)
            and apl_legal(candidate_apl)
            and has_exact_source_native_witness
        )

    result = JointCandidateAdapter(
        reference,
        gear=CandidateAxis(make_gear, mutate_gear, gear_legal),
        talents=CandidateAxis(cold_talent, mutate_talent, talent_legal),
        apl=CandidateAxis(
            cold_apl, mutate_apl_axis, apl_legal, candidate_aware=True
        ),
        joint_legal=joint_legal,
    )
    scope = {
        "gear_mutable_slots": list(gear.mutable_indices),
        "talent_builds": [talent_label(value) for value in talents],
        "talent_builds_excluded_for_native_objective_witness": [
            talent_label(value) for value in excluded_talents
        ],
        "source_donor_fixture_count": len(extra_same_class),
        "gear_donor_fixtures_scanned": gear_donor_fixtures_scanned,
        "talent_donor_fixtures": talent_donor_fixtures,
        "source_casts_by_talentsString": {
            talent_label(talent): [
                json.loads(key)
                for key in sorted(source_casts_by_talentsString[talent])
            ]
            for talent in sorted(source_casts_by_talentsString, key=talent_sort_key)
        },
        "source_apl_action_counts_by_talentsString": {
            talent_label(talent): len(source_apl_by_talentsString[talent])
            for talent in sorted(source_apl_by_talentsString, key=talent_sort_key)
        },
        "native_positive_objective_source_apl_sha256_by_talentsString": {
            talent_label(talent): hashes
            for talent, hashes in sorted(
                native_objective_source_apl_hashes.items(),
                key=lambda row: talent_sort_key(row[0]),
            )
        },
        "common_source_casts": [
            json.loads(key) for key in sorted(common_cast_keys)
        ],
        "native_positive_objective_witnesses_common_to_selected_talent_builds": common_witnesses,
        "native_positive_objective_witnesses_by_talentsString": {
            talent_label(talent): copy.deepcopy(objective_witnesses_by_talent.get(talent, []))
            for talent in selected_talent_strings
        },
        "objective": objective,
        "native_metric_path": objective_metric_path(objective),
        "talent_candidate_source": "SOURCE_OBSERVED_PROPOSALS_NATIVE_RUST_AUTHORITATIVE",
        "gear_candidate_source": "PINNED_SAME_CLASS_SOURCE_REQUESTS_SAME_POSITION",
        "apl_candidate_source": (
            "SELECTED_TALENT_SOURCE_APL_WITH_PER_BUILD_NATIVE_POSITIVE_OBJECTIVE_WITNESS"
            if native_objective_witnesses_by_talentsString is not None
            else "SELECTED_TALENT_SOURCE_APL_WITH_COMMON_NATIVE_POSITIVE_OBJECTIVE_WITNESS"
        ),
    }
    if objective == "DPS":
        # Keep the established DPS receipt keys stable for existing consumers.
        scope["talent_builds_excluded_for_native_damage_witness"] = [
            talent_label(value) for value in excluded_talents
        ]
        scope["native_positive_damage_witnesses_common_to_selected_talent_builds"] = common_witnesses
    return result, scope


def axis_delta(reference: dict, candidate: dict) -> dict[str, bool]:
    r, p = player(reference), player(candidate)
    return {
        "gear": p["equipment"]["items"] != r["equipment"]["items"],
        "talents": (
            p.get("talentsString", MISSING_TALENT_STRING)
            != r.get("talentsString", MISSING_TALENT_STRING)
        ),
        "apl": p["rotation"]["priorityList"] != r["rotation"]["priorityList"],
    }


def execute(profile_id: str, inventory: list, *,
            binary: Path, engine_src: Path, seconds: float, iterations: int,
            seed: int, outdir: Path,
            donor_fixtures: list[dict] | None = None) -> dict:
    objective = objective_for_profile(profile_id)
    metric_path = objective_metric_path(objective)
    row = {
        "profile_id": profile_id, "status": "BLOCKED_SOURCE",
        "objective": objective, "native_metric_path": metric_path,
        "dimensions_requested": ["gear", "talents", "apl"],
        "native_paid": 0, "baseline_paid": 0, "native_paid_total": 0,
        "native_donor_probe_attempts": 0, "native_donor_probe_paid": 0,
        "native_donor_probe_positive_builds": 0,
        "native_donor_probe_positive_apl_builds": 0,
        "native_donor_probe_receipts": [],
        "baseline_balanced_score": None,
        "baseline_effective_request_sha256": None,
        "baseline_native_duration_s": None,
        "baseline_rng_mode": None,
        "baseline_iterations": None,
        "baseline_seed": None,
        "baseline_response_sha256": None,
        "three_axis_paid": 0,
        "native_errors": 0, "native_unscored": 0, "native_refusals": 0,
        "native_invalid": 0, "native_unsupported": 0,
        "source_scope": "SMOKE_FIXTURE_OR_PINNED_REFERENCE",
    }
    source = next(((inv, req) for inv, req in inventory
                   if inv["profile_id"] == profile_id), None)
    if source is None:
        row["blocker"] = "Profile absent from canonical inventory"
        return row
    inv, reference = source
    row["source_sha256"] = inv["source_sha256"]
    row["source_type"] = inv["source_type"]
    row["source_path"] = inv["source_path"]
    if reference is None:
        row["blocker"] = inv["blocker"]
        return row

    cls = profile_id.split("/", 1)[0]
    same_class = [req for entry, req in inventory if req is not None
                  and entry["profile_id"].split("/", 1)[0] == cls]
    outdir.mkdir(parents=True, exist_ok=True)
    paid_dir = outdir / "paid"
    paid_dir.mkdir(exist_ok=True)
    (outdir / "source_request.json").write_text(json.dumps(reference, indent=2) + "\n")

    # The baseline native receipt is the source of truth for objective witnesses.
    # Run it before constructing the adapter so talent-build intersections and
    # the unconditional APL fallback use the same native objective as scoring.
    paid = []
    native_failures = []
    baseline_effective = native_payload(reference, iterations, seed)
    try:
        baseline_record, baseline_raw = native_score_request(
            binary, reference, iterations, seed, "balanced",
            time.monotonic() + 30.0, objective=objective,
        )
    except Exception as exc:
        row["status"] = "BLOCKED_NATIVE_BASELINE"
        row["blocker"] = "Balanced native reference baseline failed: " + str(exc)[-700:]
        failure = _write_native_failure(
            outdir, fingerprint(baseline_effective), baseline_effective, exc
        )
        row["native_failures"] = [{"stage": "baseline", **failure}]
        return row
    native_objective_witnesses = _native_positive_source_casts(
        player(reference)["rotation"]["priorityList"], baseline_raw,
        objective=objective)
    row["native_positive_objective_apl_witnesses"] = native_objective_witnesses
    if objective == "DPS":
        row["native_positive_damage_apl_witnesses"] = native_objective_witnesses
    row["baseline_paid"] = 1
    row["native_paid_total"] = row["baseline_paid"]
    row["baseline_balanced_score"] = baseline_record["score"]
    row["baseline_effective_request_sha256"] = baseline_record["effective_request_sha256"]
    row["baseline_native_duration_s"] = baseline_record["native_duration_s"]
    row["baseline_rng_mode"] = baseline_record["rng_mode"]
    row["baseline_iterations"] = baseline_record["iterations"]
    row["baseline_seed"] = baseline_record["seed"]
    row["baseline_response_sha256"] = baseline_record["raw_response_sha256"]
    (outdir / "baseline_effective_request.json").write_text(
        json.dumps(baseline_effective, indent=2) + "\n"
    )
    (outdir / "baseline_response.json").write_text(
        json.dumps(baseline_raw, indent=2) + "\n"
    )

    adapter_kwargs = {
        "donor_fixtures": donor_fixtures,
        "native_objective_witnesses": native_objective_witnesses,
        "objective": objective,
    }
    try:
        adapter, scope = source_bounded_adapter(
            cls, reference, same_class, **adapter_kwargs
        )
    except Exception as initial_exc:
        witness_block = (
            "BLOCKED_NATIVE_" + objective + "_WITNESS:"
        )
        if objective not in {"HPS", "TPS"} or not str(initial_exc).startswith(witness_block):
            row["status"] = "BLOCKED_CANDIDATE_DOMAIN"
            row["blocker"] = str(initial_exc)[:500]
            row["native_paid_total"] = row["baseline_paid"]
            row["native_failures"] = native_failures
            return row

        source_request_records = [
            {
                "request": req,
                "source_path": entry.get("source_path"),
            }
            for entry, req in inventory
            if req is not None
            and entry["profile_id"].split("/", 1)[0] == cls
        ]
        source_request_records.extend(
            {
                "request": fixture["request"],
                "source_path": fixture.get("source_path"),
            }
            for fixture in (donor_fixtures or [])
            if fixture.get("class_name") == player(reference).get("class")
            and isinstance(fixture.get("request"), dict)
        )
        witnesses_by_talent, probe_receipts, source_apls_by_talent = (
            _probe_native_objective_donor_witnesses(
                binary,
                reference,
                source_request_records,
                native_objective_witnesses,
                iterations=iterations,
                seed=seed,
                objective=objective,
                baseline_apl_source_path=inv.get("source_path"),
                outdir=outdir,
            )
        )
        probe_paid = sum(item.get("status") == "VALID" for item in probe_receipts)
        row["native_donor_probe_attempts"] = len(probe_receipts)
        row["native_donor_probe_paid"] = probe_paid
        baseline_talent = player(reference).get(
            "talentsString", MISSING_TALENT_STRING
        )
        row["native_donor_probe_positive_builds"] = sum(
            bool(witnesses_by_talent.get(talent))
            for talent in witnesses_by_talent
            if talent != baseline_talent
        )
        row["native_donor_probe_receipts"] = probe_receipts
        row["native_donor_probe_positive_apl_builds"] = len(source_apls_by_talent)
        adapter_kwargs["native_objective_witnesses_by_talentsString"] = witnesses_by_talent
        adapter_kwargs["native_objective_source_apls_by_talentsString"] = source_apls_by_talent
        try:
            adapter, scope = source_bounded_adapter(
                cls, reference, same_class, **adapter_kwargs
            )
        except Exception as exc:
            row["status"] = "BLOCKED_CANDIDATE_DOMAIN"
            row["blocker"] = str(exc)[:500]
            row["native_paid_total"] = row["baseline_paid"] + probe_paid
            row["native_failures"] = native_failures
            return row
    row.update(scope)
    deadline = time.monotonic() + seconds
    # One evaluator; no home-made objective, Go scorer or fake score can enter report.
    def evaluate(candidate, *, iterations, seed, rng_mode):
        effective = native_payload(candidate, iterations, seed)
        key = fingerprint(effective)
        if not adapter.legal(candidate):
            raise ValueError("JOINT_SEARCH_DOMAIN_REJECTED_BEFORE_NATIVE")
        try:
            native_record, raw = native_score_request(
                binary, candidate, iterations, seed, rng_mode, deadline,
                objective=objective,
            )
            score = native_record["score"]
            elapsed = native_record["native_duration_s"]
            scored_sha = native_record["effective_request_sha256"]
        except (TimeoutError, subprocess.TimeoutExpired):
            raise
        except Exception as exc:
            if len(native_failures) < 12:
                native_failures.append({
                    "stage": "candidate",
                    **_write_native_failure(outdir, key, effective, exc),
                })
            raise
        if key != scored_sha or not math.isfinite(score):
            raise RuntimeError("Native payload/score provenance mismatch")
        delta = axis_delta(reference, candidate)
        if not any(delta.values()):
            raise ValueError("Reference-identical search not counted as 3-axis discovery")
        (paid_dir / (key + ".json")).write_text(json.dumps(effective, indent=2) + "\n")
        (paid_dir / (key + ".response.json")).write_text(
            json.dumps(raw, indent=2) + "\n"
        )
        paid.append({
            "effective_request_sha256": key,
            "score": score, "objective": objective,
            "native_metric_path": metric_path, "rng_mode": rng_mode,
            "iterations": iterations, "seed": seed,
            "native_duration_s": elapsed,
            "raw_response_sha256": native_record["raw_response_sha256"],
            "delta_from_reference": delta,
            "item_ids": [x.get("id", 0) for x in player(candidate)["equipment"]["items"]],
            "talents_string_present": "talentsString" in player(candidate),
            "talents": player(candidate).get("talentsString"),
            "apl_sha256": fingerprint(player(candidate)["rotation"]["priorityList"]),
            "candidate_domain_bounded": True,
            "native_outcome": native_record.get("native_status", "VALID"),
        })
        return score

    result = search_joint(
        profile_id=profile_id, adapter=adapter, evaluate=evaluate,
        seconds=seconds, iterations=iterations, seed=seed)
    row["search_status"] = result["status"]
    row["native_paid"] = len(paid)
    row["native_paid_total"] = (
        row["baseline_paid"] + row["native_donor_probe_paid"] + row["native_paid"]
    )
    row["paid_unique"] = result["paid_candidates"]
    row["native_errors"] = result["engine_errors"]
    row["native_unscored"] = result["unscored_candidates"]
    row["native_unscored_samples"] = result["native_unscored_samples"]
    row["native_refusals"] = result["native_refusals"]
    row["native_invalid"] = result["native_invalid"]
    row["native_unsupported"] = result["native_unsupported"]
    row["native_refusal_samples"] = result["native_refusal_samples"]
    row["legal_rejections"] = result["legal_rejections"]
    row["search_elapsed_s"] = result["elapsed_s"]
    row["three_axis_paid"] = sum(all(e["delta_from_reference"].values()) for e in paid)
    row["best_balanced_screen"] = result["best_score"]
    row["native_joint_paid"] = row["three_axis_paid"] > 0
    if row["native_joint_paid"]:
        row["status"] = (
            "NATIVE_JOINT_PAID" if not row["native_errors"]
            else "NATIVE_JOINT_PAID_WITH_EXECUTION_ERRORS"
        )
    elif row["native_errors"]:
        row["status"] = "BLOCKED_NATIVE_EXECUTION_ERROR"
    elif row["native_refusals"]:
        row["status"] = "BLOCKED_NATIVE_REFUSALS"
    elif row["native_unscored"]:
        row["status"] = "BLOCKED_NATIVE_UNSCORED"
    else:
        row["status"] = "BLOCKED_NO_NATIVE_ACCEPTED_THREE_AXIS_CANDIDATE"
    if row["status"] == "NATIVE_JOINT_PAID":
        row["blocker"] = None
    elif row["status"] == "BLOCKED_NATIVE_REFUSALS":
        row["blocker"] = "MythicSim refused every scored three-axis proposal in this screen"
    elif row["status"] == "BLOCKED_NATIVE_UNSCORED":
        row["blocker"] = (
            "Native completed the requested distribution but returned no usable "
            + objective + " mean"
        )
    elif row["status"] == "BLOCKED_NATIVE_EXECUTION_ERROR":
        row["blocker"] = "Native execution/response errors prevented a usable three-axis score"
    elif row["status"] == "NATIVE_JOINT_PAID_WITH_EXECUTION_ERRORS":
        row["blocker"] = "Native execution/response errors occurred alongside paid candidates"
    else:
        row["blocker"] = "No native-accepted paid candidate changed gear, talents, and APL"
    row["native_failures"] = native_failures

    (outdir / "paid_trace.json").write_text(json.dumps(paid, indent=2) + "\n")
    if result["best_candidate"] is not None:
        winner = native_payload(result["best_candidate"], iterations, seed)
        row["best_effective_request_sha256"] = fingerprint(winner)
        (outdir / "best_effective_request.json").write_text(json.dumps(winner, indent=2) + "\n")
        # Independent exact-byte native replay with the same seed and RNG mode.
        try:
            replay_record, replay_raw = native_score_request(
                binary, result["best_candidate"], iterations, seed,
                "balanced", time.monotonic() + 30.0, objective=objective,
            )
            replay = replay_record["score"]
            replay_sha = replay_record["effective_request_sha256"]
            row["replay_score"] = replay
            row["replay_rng_mode"] = replay_record["rng_mode"]
            row["replay_response_sha256"] = replay_record["raw_response_sha256"]
            row["replay_effective_sha256"] = replay_sha
            (outdir / "best_replay_response.json").write_text(
                json.dumps(replay_raw, indent=2) + "\n"
            )
            row["replay_matches"] = (
                replay_sha == row["best_effective_request_sha256"]
                and math.isclose(replay, row["best_balanced_screen"], rel_tol=1e-10))
        except Exception as exc:
            row["replay_matches"] = False
            row["replay_error"] = str(exc)[-800:]
        if not row["replay_matches"]:
            row["status"] = "BLOCKED_NATIVE_REPLAY_MISMATCH"
            row["blocker"] = "Frozen effective scorer payload did not reproduce"
    else:
        row["replay_matches"] = False

    (outdir / "report.json").write_text(json.dumps(row, indent=2) + "\n")
    return row

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine-src", type=Path, required=True)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--profile", action="append", required=True)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--iterations", type=int, default=40)
    ap.add_argument("--seed", type=int, default=731)
    args = ap.parse_args()
    if not (0 < args.seconds <= 300) or not math.isfinite(args.seconds):
        ap.error("Finite 0 < seconds <= 300 required")
    if args.iterations < 1:
        ap.error("Positive iterations required")
    if len({x.split("/", 1)[0] for x in args.profile}) < 2:
        ap.error("Real native two-class proof requires two different classes")
    if not args.binary.is_file():
        ap.error("Real pinned native Rust binary missing")
    registry = ROOT / "config/validation/checkpoint_148.json"
    inventory = create_inventory(registry, args.engine_src)
    donor_inventory = load_source_donor_fixtures(args.engine_src)
    donor_fixtures = donor_inventory["fixtures"]
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, profile in enumerate(args.profile):
        outdir = args.out / profile.replace("/", "__")
        row = execute(
            profile, inventory,
            binary=args.binary, engine_src=args.engine_src,
            seconds=args.seconds, iterations=args.iterations,
            seed=args.seed + idx, outdir=outdir,
            donor_fixtures=donor_fixtures)
        rows.append(row)
        print(json.dumps({"profile":profile, "status":row["status"],
                          "paid":row["native_paid"],
                          "three_axis_paid":row["three_axis_paid"],
                          "source_donor_fixture_count":row.get("source_donor_fixture_count", 0),
                          "replay_matches":row.get("replay_matches")}), flush=True)
    (args.out / "joint_matrix.json").write_text(json.dumps(rows, indent=2) + "\n")
    # This is a native-paid/replay diagnostic, not a source-legality or P7 gate.
    if not all(r["status"] == "NATIVE_JOINT_PAID"
               and r.get("replay_matches") and r["three_axis_paid"] >= 1
               for r in rows):
        raise SystemExit("BLOCKED: No native-paid two-class JOINT diagnostic with exact replay; see artifacts")


if __name__ == "__main__":
    main()
