#!/usr/bin/env python3
"""Source-bounded two-class REAL Rust JOINT smoke using the shared gsim search.

This is an integration proof, not a PROCESS P7.5 PASS: talent strings are
source-observed candidate proposals and MythicSim Rust alone decides whether
they are valid. Gear options are source-observed native DB items, NOT full
equip-law parity. The class-neutral native_matrix.search_native remains the
only search loop. No mocked scorer is permitted here.
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
    ROOT, create_inventory, digest, fingerprint, legal_apl_only_request,
    load_native_item_index, player,
)
from p73_talent_search_v2 import encode, random_build, run
from native_source_donors import load_source_donor_fixtures


def _write_native_failure(outdir: Path, request_sha256: str,
                          effective_request: dict, exc: Exception) -> dict:
    """Persist failed request plus any native response without inventing a score."""
    request_path = outdir / ("failed_" + request_sha256 + ".json")
    request_path.write_text(json.dumps(effective_request, indent=2) + "\n")
    record = {
        "effective_request_sha256": request_sha256,
        "error": str(exc)[-1200:],
    }
    raw = getattr(exc, "raw_response", None)
    if isinstance(raw, dict):
        response_path = outdir / ("failed_" + request_sha256 + ".response.json")
        response_path.write_text(json.dumps(raw, indent=2) + "\n")
        record["raw_response_sha256"] = fingerprint(raw)
        record["response_file"] = response_path.name
        elapsed = getattr(exc, "elapsed_s", None)
        if isinstance(elapsed, (int, float)) and math.isfinite(float(elapsed)):
            record["native_duration_s"] = float(elapsed)
    return record


def _native_positive_source_casts(source_actions: list[dict],
                                  native_response: dict) -> list[dict]:
    """Find source APL casts that actually dealt damage in the paid baseline.

    Native action metrics, not spell-name guesses or source inventories, are
    the witness. Keep exact source spell identities (including rank). A class
    whose damage is only white attacks/pets gets no fabricated cast witness.
    """
    try:
        native_actions = native_response["result"]["raidMetrics"]["parties"][0]["players"][0]["actions"]
    except (KeyError, IndexError, TypeError):
        return []
    positive_ids = set()
    for action in native_actions:
        identity = action.get("id", {})
        spell_id = identity.get("spellId") if isinstance(identity, dict) else None
        if not isinstance(spell_id, int) or isinstance(spell_id, bool):
            continue
        if any(
            isinstance(target.get("damage"), (int, float))
            and not isinstance(target.get("damage"), bool)
            and math.isfinite(float(target["damage"]))
            and target["damage"] > 0
            for target in action.get("targets", []) if isinstance(target, dict)
        ):
            positive_ids.add(spell_id)
    witnesses = []
    seen = set()
    for entry in source_actions:
        cast = entry.get("action", {}).get("castSpell")
        identity = cast.get("spellId") if isinstance(cast, dict) else None
        if not isinstance(identity, dict):
            continue
        spell_id = identity.get("spellId")
        key = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        if spell_id in positive_ids and key not in seen:
            witnesses.append(copy.deepcopy(identity))
            seen.add(key)
    return witnesses


def _ensure_native_damage_action(actions: list[dict],
                                 witnesses: list[dict], rng) -> list[dict]:
    """Keep every source-observed damaging cast in the unconditional fallback block.

    Conditional and opaque source actions retain priority. Existing
    unconditional witnesses keep their relative order; missing baseline-positive
    witnesses are inserted after them and before non-damaging unconditional
    casts. The list is capped at the native 20-action limit.
    """
    if not witnesses:
        return actions
    actions = copy.deepcopy(actions)
    allowed = {json.dumps(x, sort_keys=True, separators=(",", ":"))
               for x in witnesses}

    conditional_or_opaque = []
    existing_witnesses = []
    seen_witnesses = set()
    unconditional = []
    for entry in actions:
        action = entry.get("action", {})
        cast = action.get("castSpell")
        is_cast = isinstance(cast, dict)
        identity = cast.get("spellId") if is_cast else None
        identity_key = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        is_witness = (is_cast and "condition" not in action
                      and identity_key in allowed)
        if is_witness:
            if identity_key not in seen_witnesses:
                existing_witnesses.append(entry)
                seen_witnesses.add(identity_key)
        elif not is_cast or "condition" in action:
            conditional_or_opaque.append(entry)
        else:
            unconditional.append(entry)

    # Keep all existing positive casts first, then append any baseline-positive
    # witnesses missing from this candidate. The order is source-response order.
    for witness in witnesses:
        identity_key = json.dumps(witness, sort_keys=True, separators=(",", ":"))
        if identity_key in seen_witnesses:
            continue
        existing_witnesses.append({"action": {"castSpell": {
            "spellId": copy.deepcopy(witness)}}})
        seen_witnesses.add(identity_key)

    # Reserve the native 20-action budget for observed damage witnesses before
    # retaining the highest-priority conditional prefix. A full conditional
    # APL must not evict every fallback (or produce >20 actions). Trim only
    # lower-priority tail actions; source APL objects are never modified.
    existing_witnesses = existing_witnesses[:20]
    prefix_room = 20 - len(existing_witnesses)
    conditional_or_opaque = conditional_or_opaque[:prefix_room]
    utility_room = 20 - len(conditional_or_opaque) - len(existing_witnesses)
    unconditional = unconditional[:utility_room]

    # Conditional/opaque actions retain their relative order, followed by
    # native-positive fallback casts and any remaining utility actions.
    return conditional_or_opaque + existing_witnesses + unconditional

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
    runner=run,
) -> tuple[dict, dict]:
    """Score one exact request with an explicit optimizer RNG mode.

    This joint-search lane is selection, not holdout: every baseline,
    candidate and exact replay must use the typed balanced backend. Stochastic
    evaluation is reserved for a separate frozen finalist holdout.
    """
    if rng_mode != "balanced":
        raise ValueError("JOINT_OPTIMIZER_REQUIRES_EXPLICIT_BALANCED_RNG")
    effective = native_payload(candidate, iterations, seed)
    expected_sha = fingerprint(effective)
    score, raw, elapsed, scored_sha = runner(
        binary, candidate, iterations, seed, rng_mode, deadline
    )
    if scored_sha != expected_sha:
        raise RuntimeError("Native payload/score provenance mismatch")
    if not math.isfinite(float(score)):
        raise RuntimeError("Native evaluator returned a non-finite score")
    return {
        "effective_request_sha256": expected_sha,
        "score": float(score),
        "rng_mode": rng_mode,
        "iterations": iterations,
        "seed": seed,
        "native_duration_s": elapsed,
        "raw_response_sha256": fingerprint(raw),
    }, raw




def _generate_native_druid_talent_donors(
    binary: Path, reference: dict, baseline_witnesses: list[dict], outdir: Path,
    *, iterations: int, seed: int, existing_talents: set[str] | None = None,
    runner=run, max_attempts: int = 12,
) -> tuple[list[dict], list[dict], dict]:
    """Propose Druid talent candidates and let native Rust decide validity.

    Candidates come from the existing source-derived proposal generator. Each
    exact request is executed through the selected native Rust binary in
    Balanced mode. A donor is usable only when native execution succeeds and
    the baseline-positive cast also deals native damage under that build.
    """
    source_player = player(reference)
    if source_player.get("class") != "ClassDruid":
        return [], [], {"status": "NOT_APPLICABLE", "native_evaluations": 0,
                        "native_failures": 0}
    source_actions = source_player.get("rotation", {}).get("priorityList", [])
    original_talents = source_player.get("talentsString")
    def witness_key(identity: dict) -> str:
        return json.dumps({"spellId": identity}, sort_keys=True,
                          separators=(",", ":"))

    baseline_keys = {witness_key(identity) for identity in baseline_witnesses}
    if not baseline_keys:
        return [], [], {
            "status": "BLOCKED_NO_BASELINE_NATIVE_DAMAGE_WITNESS",
            "native_evaluations": 0, "native_failures": 0,
            "attempted_builds": [],
        }

    donor_dir = Path(outdir) / "generated_talent_donors"
    donor_dir.mkdir(parents=True, exist_ok=True)
    seen = set(existing_talents or ())
    if isinstance(original_talents, str):
        seen.add(original_talents)
    by_witness: dict[str, list[dict]] = {}
    attempted_builds = []
    native_evaluations = 0
    native_failures = 0

    for attempt in range(max_attempts):
        build_seed = seed + 1_000_003 + attempt
        ranks = random_build(random.Random(build_seed))
        talents = encode(ranks)
        if talents in seen:
            continue
        seen.add(talents)

        donor_seed = seed + 2_000_003 + attempt
        candidate = copy.deepcopy(reference)
        player(candidate)["talentsString"] = talents
        effective = native_payload(candidate, iterations, donor_seed)
        request_sha = fingerprint(candidate)
        prefix = fingerprint(talents)[:16]
        try:
            record, raw = native_score_request(
                binary, candidate, iterations, donor_seed, "balanced",
                time.monotonic() + 30.0, runner=runner,
            )
        except (TimeoutError, subprocess.TimeoutExpired) as exc:
            native_failures += 1
            failure = _write_native_failure(
                donor_dir, fingerprint(effective), effective, exc
            )
            attempted_builds.append({
                "talents": talents, "status": "NATIVE_TIMEOUT", "failure": failure,
            })
            break
        except Exception as exc:
            native_failures += 1
            failure = _write_native_failure(
                donor_dir, fingerprint(effective), effective, exc
            )
            attempted_builds.append({
                "talents": talents, "status": "NATIVE_FAILURE", "failure": failure,
            })
            continue

        native_evaluations += 1
        positive = _native_positive_source_casts(source_actions, raw)
        positive_keys = {witness_key(identity) for identity in positive}
        common = [
            copy.deepcopy(identity) for identity in baseline_witnesses
            if witness_key(identity) in positive_keys
        ]
        request_path = donor_dir / (prefix + ".request.json")
        effective_path = donor_dir / (prefix + ".effective_request.json")
        response_path = donor_dir / (prefix + ".response.json")
        request_path.write_text(json.dumps(candidate, indent=2) + "\n")
        effective_path.write_text(json.dumps(effective, indent=2) + "\n")
        response_path.write_text(json.dumps(raw, indent=2) + "\n")

        attempt_record = {
            "talents": talents,
            "status": "NATIVE_POSITIVE_WITNESS" if common else "NO_COMMON_POSITIVE_WITNESS",
            "score": record["score"],
            "native_response_sha256": record["raw_response_sha256"],
            "positive_damage_witnesses": positive,
            "baseline_positive_witnesses_confirmed": common,
            "request_path": request_path.relative_to(outdir).as_posix(),
            "effective_request_path": effective_path.relative_to(outdir).as_posix(),
            "response_path": response_path.relative_to(outdir).as_posix(),
        }
        attempted_builds.append(attempt_record)
        if not common:
            continue

        fixture = {
            "class_name": "ClassDruid",
            "request": candidate,
            "source_path": request_path.relative_to(outdir).as_posix(),
            "source_sha256": request_sha,
            "item_count": len(source_player.get("equipment", {}).get("items", [])),
            "source_type": "NATIVE_VERIFIED_GENERATED_TALENT_CANDIDATE",
            "native_response_sha256": record["raw_response_sha256"],
            "native_positive_damage_witnesses": common,
            "native_score": record["score"],
            "native_iterations": record["iterations"],
            "native_seed": record["seed"],
            "native_rng_mode": record["rng_mode"],
        }
        for identity in common:
            by_witness.setdefault(witness_key(identity), []).append(fixture)
        if any(len(fixtures) >= 2 for fixtures in by_witness.values()):
            break

    supported = [
        (len(fixtures), key, fixtures)
        for key, fixtures in by_witness.items() if len(fixtures) >= 2
    ]
    if not supported:
        summary = {
            "status": "BLOCKED_NO_TWO_NATIVE_VERIFIED_TALENT_DONORS",
            "build_provenance": "p73_talent_search_v2.random_build+encode; native Rust Balanced execution is the sole talent-validity authority",
            "native_iterations": iterations,
            "native_evaluations": native_evaluations,
            "native_failures": native_failures,
            "attempted_builds": attempted_builds,
            "selected_talent_builds": [],
            "common_witnesses": [],
        }
        (donor_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return [], [], summary

    _support, selected_key, candidates = max(
        supported, key=lambda item: (item[0], item[1])
    )
    selected = sorted(
        candidates, key=lambda fixture: player(fixture["request"])["talentsString"]
    )[:2]
    common_keys = set(baseline_keys)
    for fixture in selected:
        common_keys.intersection_update({
            witness_key(identity)
            for identity in fixture["native_positive_damage_witnesses"]
        })
    common_witnesses = [
        copy.deepcopy(identity) for identity in baseline_witnesses
        if witness_key(identity) in common_keys
    ]
    if selected_key not in common_keys or len(selected) != 2 or not common_witnesses:
        raise RuntimeError("Generated Druid donors lost their shared native-positive witness")

    summary = {
        "status": "PASS",
        "build_provenance": "p73_talent_search_v2.random_build+encode; native Rust Balanced execution is the sole talent-validity authority",
        "native_iterations": iterations,
        "native_evaluations": native_evaluations,
        "native_failures": native_failures,
        "attempted_builds": attempted_builds,
        "selected_talent_builds": [
            player(fixture["request"])["talentsString"] for fixture in selected
        ],
        "common_witnesses": common_witnesses,
        "selected_native_response_sha256": [
            fixture["native_response_sha256"] for fixture in selected
        ],
    }
    (donor_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return selected, common_witnesses, summary


def source_bounded_adapter(
    class_key: str, reference: dict, same_class: list[dict],
    items: dict[int, dict], *, donor_fixtures: list[dict] | None = None,
    native_damage_witnesses: list[dict] | None = None,
    native_verified_talent_builds: set[str] | None = None,
) -> tuple[JointCandidateAdapter, dict]:
    """Use exact pinned same-class source requests; the scheduler is unchanged."""
    original = player(reference)
    extra_same_class = [
        fixture for fixture in (donor_fixtures or [])
        if fixture.get("class_name") == original.get("class")
        and isinstance(fixture.get("request"), dict)
    ]
    donor_requests = [fixture["request"] for fixture in extra_same_class]
    source_requests = same_class + donor_requests
    gear = NativeGearAdapter(class_key, reference, source_requests, items)
    if not gear.mutable_indices:
        raise ValueError("BLOCKED_GEAR_POOL: no source-bounded legal alternate item")

    base_gear = copy.deepcopy(original["equipment"]["items"])
    base_apl = copy.deepcopy(original["rotation"]["priorityList"])
    source_talents = set()
    talents = set()
    source_casts_by_talentsString: dict[object, set[str]] = {}

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
        rotation = source_player.get("rotation")
        priority_list = rotation.get("priorityList", []) if isinstance(rotation, dict) else []
        if isinstance(priority_list, list):
            for entry in priority_list:
                action = entry.get("action", {}) if isinstance(entry, dict) else {}
                cast = action.get("castSpell") if isinstance(action, dict) else None
                if isinstance(cast, dict) and cast:
                    source_casts.add(json.dumps(
                        cast, sort_keys=True, separators=(",", ":")
                    ))
        # Missing talentString is a source-observed candidate too. Preserve
        # its absence in the request; only MythicSim can accept or refuse it.
        talents.add(source_talent)
    talents = sorted(talents, key=talent_sort_key)
    original_talents = original["talentsString"]
    if original_talents not in source_talents or len(talents) < 2:
        raise ValueError(
            "BLOCKED_TALENTS: need a source-observed baseline and two "
            "same-class candidate talent strings"
        )

    native_damage_witnesses = [
        copy.deepcopy(identity) for identity in (native_damage_witnesses or [])
        if isinstance(identity, dict) and identity
    ]
    original_source_casts = source_casts_by_talentsString.get(original_talents, set())
    native_witness_keys = []
    for identity in native_damage_witnesses:
        key = json.dumps({"spellId": identity}, sort_keys=True, separators=(",", ":"))
        if key in original_source_casts and key not in native_witness_keys:
            native_witness_keys.append(key)

    # Select the largest source-observed proposal set sharing a baseline-positive
    # cast. Native Rust, not this witness search, decides each build's validity.
    supported_build_sets = []
    for witness_key in native_witness_keys:
        builds = [
            talent for talent in talents
            if witness_key in source_casts_by_talentsString.get(talent, set())
        ]
        if len(builds) >= 2:
            supported_build_sets.append((len(builds), witness_key, builds))
    if not supported_build_sets:
        raise ValueError(
            "BLOCKED_NATIVE_DAMAGE_WITNESS: no baseline-positive source cast "
            "is present in the reference and at least two same-class "
            "source candidate talent strings"
        )
    candidate_talents = set(talents)
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

    common_witnesses = []
    seen_common_witnesses = set()
    for identity in native_damage_witnesses:
        key = json.dumps({"spellId": identity}, sort_keys=True, separators=(",", ":"))
        if key in common_cast_keys and key not in seen_common_witnesses:
            common_witnesses.append(copy.deepcopy(identity))
            seen_common_witnesses.add(key)
    if not common_witnesses:
        raise ValueError(
            "BLOCKED_NATIVE_DAMAGE_WITNESS: selected talent builds have no "
            "common baseline-positive source cast"
        )
    alternate = [t for t in talents if t != original_talents]

    gear_donor_fixtures_scanned = [
        {
            "source_path": fixture["source_path"],
            "source_sha256": fixture["source_sha256"],
            "item_count": fixture["item_count"],
        }
        for fixture in extra_same_class
        if fixture.get("item_count") == len(base_gear)
        and fixture.get("source_type") != "NATIVE_VERIFIED_GENERATED_TALENT_CANDIDATE"
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

    damage_witnesses = common_witnesses

    def cast_identity_key(cast):
        if not isinstance(cast, dict) or not cast:
            return None
        return json.dumps(cast, sort_keys=True, separators=(",", ":"))

    def filter_to_common_source_casts(actions):
        filtered = []
        for entry in actions:
            action = entry.get("action", {}) if isinstance(entry, dict) else {}
            cast = action.get("castSpell") if isinstance(action, dict) else None
            key = cast_identity_key(cast)
            if key is None or key in common_cast_keys:
                filtered.append(copy.deepcopy(entry))
        return filtered

    def apl_cast_identity_keys(actions):
        return {
            key
            for entry in actions if isinstance(entry, dict)
            for action in [entry.get("action", {})]
            if isinstance(action, dict)
            for cast in [action.get("castSpell")]
            if (key := cast_identity_key(cast)) is not None
        }

    candidate_base_apl = filter_to_common_source_casts(base_apl)

    def cold_apl(rng):
        for _ in range(8):
            actions = _ensure_native_damage_action(
                filter_to_common_source_casts(
                    mutate_apl(None, candidate_base_apl, rng, cold=True)
                ),
                damage_witnesses,
                rng,
            )
            if actions != base_apl:
                return actions
        raise ValueError("BLOCKED_APL: no different source-corpus action generated")

    def mutate_apl_axis(current, rng):
        current = filter_to_common_source_casts(current)
        return _ensure_native_damage_action(
            filter_to_common_source_casts(
                mutate_apl(current, candidate_base_apl, rng)
            ),
            damage_witnesses,
            rng,
        )

    def apl_legal(value):
        request = copy.deepcopy(reference)
        player(request)["rotation"]["priorityList"] = copy.deepcopy(value)
        return legal_apl_only_request(reference, request)

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
            json.dumps({"spellId": identity}, sort_keys=True, separators=(",", ":"))
            for identity in damage_witnesses
        }
        has_unconditional_native_witness = any(
            isinstance(entry, dict)
            and isinstance(entry.get("action"), dict)
            and not entry["action"].get("condition")
            and cast_identity_key(entry["action"].get("castSpell")) in eligible_witness_keys
            for entry in candidate_apl
        )
        return (
            candidate_player["class"] == original["class"]
            and gear_legal(candidate_player["equipment"]["items"])
            and talent_legal(talent_string)
            and apl_legal(candidate_apl)
            and has_unconditional_native_witness
        )

    result = JointCandidateAdapter(
        reference,
        gear=CandidateAxis(make_gear, mutate_gear, gear_legal),
        talents=CandidateAxis(cold_talent, mutate_talent, talent_legal),
        apl=CandidateAxis(cold_apl, mutate_apl_axis, apl_legal),
        joint_legal=joint_legal,
    )
    return result, {
        "gear_mutable_slots": list(gear.mutable_indices),
        "talent_builds": [talent_label(value) for value in talents],
        "talent_builds_excluded_for_native_damage_witness": [
            talent_label(value) for value in excluded_talents
        ],
        "source_donor_fixture_count": sum(
            fixture.get("source_type") != "NATIVE_VERIFIED_GENERATED_TALENT_CANDIDATE"
            for fixture in extra_same_class
        ),
        "native_generated_talent_donor_count": sum(
            fixture.get("source_type") == "NATIVE_VERIFIED_GENERATED_TALENT_CANDIDATE"
            for fixture in extra_same_class
        ),
        "native_verified_talent_builds": sorted(native_verified_talent_builds or set()),
        "gear_donor_fixtures_scanned": gear_donor_fixtures_scanned,
        "talent_donor_fixtures": talent_donor_fixtures,
        "source_casts_by_talentsString": {
            talent_label(talent): [
                json.loads(key)
                for key in sorted(source_casts_by_talentsString[talent])
            ]
            for talent in sorted(source_casts_by_talentsString, key=talent_sort_key)
        },
        "common_source_casts": [
            json.loads(key) for key in sorted(common_cast_keys)
        ],
        "native_positive_damage_witnesses_common_to_selected_talent_builds": common_witnesses,
        "talent_validation": "SOURCE_OBSERVED_CANDIDATE_STRINGS_NATIVE_RUST_AUTHORITATIVE",
        "gear_validation": "PINNED_SAME_CLASS_SLOT_NATIVE_DB_PARTIAL_EQUIP_RULES",
        "apl_validation": "CAST_IDENTITIES_BOUND_TO_TALENT_STRING_AND_COMMON_NATIVE_POSITIVE_WITNESS",
    }


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


def execute(profile_id: str, inventory: list, native_items: dict, *,
            binary: Path, engine_src: Path, seconds: float, iterations: int,
            seed: int, outdir: Path,
            donor_fixtures: list[dict] | None = None) -> dict:
    row = {
        "profile_id": profile_id, "status": "BLOCKED_SOURCE",
        "dimensions_requested": ["gear", "talents", "apl"],
        "native_paid": 0, "baseline_paid": 0, "native_paid_total": 0,
        "native_generated_donor_paid": 0, "native_generated_donor_failures": 0,
        "baseline_balanced_score": None,
        "baseline_effective_request_sha256": None,
        "baseline_native_duration_s": None,
        "baseline_rng_mode": None,
        "baseline_iterations": None,
        "baseline_seed": None,
        "baseline_response_sha256": None,
        "three_axis_paid": 0, "process_gate_pass": False,
        "source_scope": "SMOKE_FIXTURE_OR_PINNED_REFERENCE",
        "full_source_legality_certified": False,
        "live_gsim_2d_rust_causality": False,
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

    # The baseline native receipt is the source of truth for damage witnesses.
    # Run it before constructing the adapter, which uses those witnesses to
    # restrict talent-build intersections and require a native-positive APL.
    paid = []
    native_failures = []
    baseline_effective = native_payload(reference, iterations, seed)
    try:
        baseline_record, baseline_raw = native_score_request(
            binary, reference, iterations, seed, "balanced",
            time.monotonic() + 30.0,
        )
    except Exception as exc:
        row["status"] = "BLOCKED_NATIVE_BASELINE"
        row["blocker"] = "Balanced native reference baseline failed: " + str(exc)[-700:]
        failure = _write_native_failure(
            outdir, fingerprint(baseline_effective), baseline_effective, exc
        )
        row["native_failures"] = [{"stage": "baseline", **failure}]
        return row
    native_damage_witnesses = _native_positive_source_casts(
        player(reference)["rotation"]["priorityList"], baseline_raw)
    row["native_positive_damage_apl_witnesses"] = native_damage_witnesses
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

    try:
        try:
            adapter, scope = source_bounded_adapter(
                cls, reference, same_class, native_items,
                donor_fixtures=donor_fixtures,
                native_damage_witnesses=native_damage_witnesses,
            )
        except ValueError as exc:
            can_generate_druid_donors = (
                cls == "druid"
                and any(marker in str(exc) for marker in (
                    "BLOCKED_TALENTS", "BLOCKED_NATIVE_DAMAGE_WITNESS",
                ))
            )
            if not can_generate_druid_donors:
                raise

            existing_talents = {
                player(request_value).get("talentsString")
                for request_value in same_class
                if isinstance(player(request_value).get("talentsString"), str)
            }
            for fixture in donor_fixtures or []:
                request_value = fixture.get("request")
                if isinstance(request_value, dict):
                    value = player(request_value).get("talentsString")
                    if isinstance(value, str):
                        existing_talents.add(value)

            generated_donors, generated_witnesses, generated_summary = (
                _generate_native_druid_talent_donors(
                    binary, reference, native_damage_witnesses, outdir,
                    iterations=iterations, seed=seed,
                    existing_talents=existing_talents,
                )
            )
            row["native_generated_donor_summary"] = generated_summary
            row["native_generated_donor_paid"] = generated_summary.get(
                "native_evaluations", 0
            )
            row["native_generated_donor_failures"] = generated_summary.get(
                "native_failures", 0
            )
            if len(generated_donors) < 2:
                raise ValueError(
                    "BLOCKED_NATIVE_DAMAGE_WITNESS: " +
                    generated_summary.get("status", "generated donor proof incomplete")
                ) from exc

            effective_donors = list(donor_fixtures or []) + generated_donors
            original_talents = player(reference).get("talentsString")
            verified_builds = {
                talent for talent in [
                    original_talents,
                    *[player(fixture["request"]).get("talentsString")
                      for fixture in generated_donors],
                ]
                if isinstance(talent, str)
            }
            adapter, scope = source_bounded_adapter(
                cls, reference, same_class, native_items,
                donor_fixtures=effective_donors,
                native_damage_witnesses=generated_witnesses,
                native_verified_talent_builds=verified_builds,
            )
            scope["native_generated_donor_summary"] = generated_summary
    except Exception as exc:
        row["status"] = "BLOCKED_SOURCE_LEGALITY"
        row["blocker"] = str(exc)[:500]
        row["native_paid_total"] = (
            row["baseline_paid"] + row["native_generated_donor_paid"]
        )
        row["native_failures"] = native_failures
        return row
    row.update(scope)
    deadline = time.monotonic() + seconds
    # One evaluator; no home-made DPS, Go scorer or fake score can enter report.
    def evaluate(candidate, *, iterations, seed, rng_mode):
        effective = native_payload(candidate, iterations, seed)
        key = fingerprint(effective)
        if not adapter.legal(candidate):
            raise ValueError("JOINT_LEGALITY_REJECTED_BEFORE_NATIVE")
        try:
            native_record, raw = native_score_request(
                binary, candidate, iterations, seed, rng_mode, deadline
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
            "score": score, "rng_mode": rng_mode,
            "iterations": iterations, "seed": seed,
            "native_duration_s": elapsed,
            "raw_response_sha256": native_record["raw_response_sha256"],
            "delta_from_reference": delta,
            "item_ids": [x.get("id", 0) for x in player(candidate)["equipment"]["items"]],
            "talents": player(candidate)["talentsString"],
            "apl_sha256": fingerprint(player(candidate)["rotation"]["priorityList"]),
            "source_bounded_legality": True,
            "full_source_legality_certified": False,
        })
        return score

    result = search_joint(
        profile_id=profile_id, adapter=adapter, evaluate=evaluate,
        seconds=seconds, iterations=iterations, seed=seed)
    row["search_status"] = result["status"]
    row["native_paid"] = len(paid)
    row["native_paid_total"] = (
        row["baseline_paid"] + row["native_generated_donor_paid"] + row["native_paid"]
    )
    row["paid_unique"] = result["paid_candidates"]
    row["native_errors"] = result["engine_errors"]
    row["legal_rejections"] = result["legal_rejections"]
    row["search_elapsed_s"] = result["elapsed_s"]
    row["three_axis_paid"] = sum(all(e["delta_from_reference"].values()) for e in paid)
    row["best_balanced_screen"] = result["best_score"]
    row["source_bounded_joint"] = row["three_axis_paid"] > 0
    row["status"] = (
        "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY"
        if row["source_bounded_joint"] else "BLOCKED_NO_PAID_THREE_AXIS_JOINT"
    )
    row["blocker"] = None if row["source_bounded_joint"] else (
        "No legal source-bounded Rust paid candidate changed gear, talents, and APL")
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
                "balanced", time.monotonic() + 30.0,
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
    items = load_native_item_index(args.engine_src)
    donor_inventory = load_source_donor_fixtures(args.engine_src)
    donor_fixtures = donor_inventory["fixtures"]
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, profile in enumerate(args.profile):
        outdir = args.out / profile.replace("/", "__")
        row = execute(
            profile, inventory, items,
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
    # CI must fail if either class did NOT actually score and replay a
    # three-axis-mutated legal source-bounded candidate on the real Rust.
    if not all(r["status"] == "SOURCE_BOUNDED_NATIVE_JOINT_PARTIAL_LEGALITY"
               and r.get("replay_matches") and r["native_paid"] >= 1
               for r in rows):
        raise SystemExit("BLOCKED: No completed two-class Rust JOINT proof; see artifacts")


if __name__ == "__main__":
    main()
