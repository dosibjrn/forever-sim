"""P7.5 real cold joint source gear/talents/APL first contact with native+2D.

The same production engine and source legality generator as P7.2–P7.4 are
used. No M1 DPS-proximity claim is made before a compatible ACCEPTED prior
P7.1–P7.4 winner exists; nor is a bounded 3-fight probe a frozen holdout.
"""
from __future__ import annotations

import copy
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time

from tools.wf_gate_coverage import (P7_FINAL_STOCHASTIC_ITERATIONS,
                                    P7_5_FINAL_DPS_FLOOR_FRACTION,
                                    p7_required_dps,
                                    p7_search_window_completed)
from tools.wf_gate_p7_5_prior import strongest_accepted_prior
# Shared native+2D balanced-finalist scheduling helpers from P7.4.
from tools.wf_gate_p7_4_live import (
    _paid_step_has_budget,
    _p74_early_rerank_due, _next_p74_confirmation,
    _next_p74_deep_confirmation)
from src.engine_client import native_talent_proposals
from tools.wf_gate_p7_1_live import (PINNED_RUST, SAVED_BALANCE_RAW_SHA,
                                      SAVED_FERAL_RAW_SHA,
                                     _executed_p7_runtime_proof,
                                     _source_native_world_parity)
from tools.wf_gate_p7_2_live import _source_module, _pinned_source_runtime


def _cold_joint(base, source, validator, pools, rng, *, elite=None, enchant_pools=None, repair_axes=None):
    """Legal source build: cold discovery or mutation of this search's paid winner.

    The seed for a fresh search is always independent of the reference and of
    P7.1-P7.4 winners. Later elite mutations derive only from candidates that
    this same P7.5 native/world run has actually executed and scored.
    """
    # A cold generator must not be SEEDED with the saved reference or a prior
    # winner. Independently rediscovering any reference gear, talent or APL
    # dimension is legal: excluding matching axes silently removes valid
    # candidates from the joint search space (including the true optimum).
    for _ in range(80):
        try:
            kwargs = ({"enchant_pools": enchant_pools}
                      if enchant_pools is not None else {})
            if elite is None:
                candidate = source.make_candidate(base, pools, rng, **kwargs)
            elif repair_axes is None:
                candidate = source.make_candidate(
                    base, pools, rng, elite=elite, **kwargs)
            else:
                candidate = source.make_candidate(
                    base, pools, rng, elite=elite, repair_axes=repair_axes,
                    **kwargs)
            # A proposal is not a legal build until the selected Rust
            # native_source_control(sim --gate) accepts it. Do not run a
            # second Forever/SQLite item-legality veto before forwarding.
            # Equality with a reference axis is never evidence of seeding.
            return candidate
        except (source.RejectedGear, ValueError, KeyError, TypeError):
            continue
    raise ValueError("NO_SOURCE_LEGAL_INDEPENDENT_COLD_JOINT_ALTERNATIVE")


def _paid_p75_parent(best, finalists, proposal_index, rng, *,
                     balanced_elites=()):
    """Mutate paid builds, not one noisy three-fight leader indefinitely.

    Full P7.5 searches previously used the single highest balanced-screen
    build for every pre-finalist non-restart mutation. In a joint gear/talent/
    rotation search this collapses exploration onto one stochastic outlier.
    Keep the 1/5 independent cold restarts; on every third local proposal,
    draw from the six highest *actually executed* balanced candidates.
    Other local proposals prefer the strongest separately paid balanced
    finalists once available. Never draw from saved or prior gate winners.
    """
    if best is None or proposal_index % 5 == 0:
        return None
    if balanced_elites and proposal_index % 3 == 0:
        return rng.choice(sorted(
            balanced_elites, key=lambda row: row[0], reverse=True
        )[:6])[2]
    if finalists and proposal_index % 3 != 0:
        return rng.choice(sorted(
            finalists, key=lambda row: row[0], reverse=True
        )[:3])[3]
    return best[3]


def _p75_paid_joint_axes(proposal_index: int):
    """Occasionally repair interacting axes from THIS search's paid parent.

    The previous P7.5 local operator mutated only one of gear, talents, APL
    or enchants per proposal. The genuine full paid run #41577577552 fell
    16.90 DPS below its accepted-compatible prior; retain the independent
    1/5 cold restarts and existing one-axis exploitation, but let every
    seventh paid-parent proposal explore a two-axis neighborhood. Never use
    the saved reference or earlier gates' winning builds as parents.
    """
    if proposal_index % 7:
        return None
    pairs = (("gear", "talents"), ("gear", "rotation"),
             ("talents", "rotation"))
    return pairs[(proposal_index // 7 - 1) % len(pairs)]


def _p75_paid_rebuild_axes(proposal_index: int):
    """Escape a paid search basin by rebuilding ONE axis from source.

    The generator already exposes these source-legal rebuild operations, but
    the default paid-parent search previously never requested them: only
    local neighbor edits and simultaneous small axis edits were reachable.
    Keep independent cold starts and seventh-proposal paired mutations.
    Rebuild the named axis while retaining the other two paid-parent axes;
    source/Rust legality and real native+2D payment remain mandatory.
    """
    if proposal_index % 11:
        return None
    axes = ("gear_rebuild", "talents_rebuild", "rotation_rebuild")
    return (axes[(proposal_index // 11 - 1) % len(axes)],)



def _paid_p75_balanced_finalist(production, binary, request, distance, *,
                                seeds=("1955004", "1955047"), native_only=False,
                                 go_rules=False):
    """Rank paid P7.5 candidates only with deterministic balanced RNG.

    Keep a small, reproducible three-fight screen for each independent seed.
    The 1,000 independent stochastic iterations are strictly the *final*
    holdout, after a source-legal winner has been frozen. Both candidate
    scores come from the same selected Rust and real gsim-2D boundary.
    """
    scores = []
    latest_live = None
    for seed in seeds:
        candidate = copy.deepcopy(request)
        candidate["simOptions"]["randomSeed"] = str(seed)
        with tempfile.TemporaryDirectory(prefix="forever_p75_balanced_") as tmp:
            path = Path(tmp) / "paid-balanced-finalist.json"
            path.write_text(json.dumps(candidate))
            native = production.native_source_control(
                binary, path, 3, rng_mode="balanced",
                **({"go_rules": True} if go_rules else {}))
            if native_only:
                if type(native.get("iterations")) is not int or native["iterations"] != 3:
                    raise ValueError("P75_BALANCED_FINALIST_NATIVE_ITERATIONS_INVALID")
                live = native
                score = float(native["native_dps"])
            else:
                live = production.run(
                    binary, path, distance=distance, iterations=3,
                    rng_mode="balanced")
                mismatch = _source_native_world_parity(native, live, 3)
                if mismatch is not None:
                    raise ValueError("P75_BALANCED_FINALIST_NATIVE_WORLD_PARITY:" + mismatch)
                if (live.get("iterations_done") != 3
                        or live.get("native_damage_events", 0) <= 0
                        or live.get("native_world_ticks", 0) <= 0):
                    raise ValueError("P75_BALANCED_FINALIST_WORLD_INCOMPLETE")
                score = float(live["world_mean_dps"])
        if not 0 <= score < float("inf"):
            raise ValueError("P75_BALANCED_FINALIST_DPS_INVALID")
        scores.append(score)
        latest_live = live
    return sum(scores) / len(scores), latest_live


def _freeze_paid_p75_balanced_winner(screen_best, reranked, confirmed=(),
                                     deep_confirmed=()):
    """Freeze the best genuinely paid balanced finalist, never holdout rank."""
    if reranked:
        deep_rows = [row for row in reranked if row[2] in deep_confirmed]
        confirmed_rows = [row for row in reranked if row[2] in confirmed]
        score, live, sha, request, screen_score = max(
            deep_rows or confirmed_rows or reranked, key=lambda row: row[0])
        label = ("paid_6x3_balanced_live_native_deep_confirmed_finalist"
                 if deep_rows else
                 "paid_4x3_balanced_live_native_confirmed_finalist"
                 if confirmed_rows else "paid_2x3_balanced_live_native_finalist")
        return score, live, sha, request, screen_score, label
    score, live, sha, request = screen_best
    return score, live, sha, request, score, "three_balanced_live_screen_only"


def _paid_p75_crossover(candidate, parent, finalists, balanced_elites, source, rng):
    """Combine a paid candidate's gear with a distinct paid talent + APL.

    Use only separately scored parents from THIS independent P7.5 cold search.
    A differently equipped donor with identical talents and rotation does not
    supply a talent/APL crossover: it previously returned True but left both
    axes unchanged, wasting a proposal and suppressing paid balanced donors.
    Preserve both meaningful paid finalist and balanced-elite talent/APL
    donors rather than suppressing the latter as soon as one finalist exists.
    """
    player = source.player(candidate)

    def distinct_paid_pairs(rows, candidate_index, limit):
        eligible = []
        seen_axes = set()
        # Cap AFTER both candidate-eligibility and distinct-axis filtering.
        # Repeated paid gear variants with the same talent/APL must not crowd
        # out a lower-scored, genuinely paid distinct talent/APL donor.
        for row in sorted(rows, key=lambda row: row[0], reverse=True):
            paid = row[candidate_index]
            if paid == parent:
                continue
            donor = source.player(paid)
            axes = (donor["talentsString"],
                    json.dumps(donor["rotation"], sort_keys=True))
            if (donor["talentsString"] == player["talentsString"]
                    and donor["rotation"] == player["rotation"]):
                continue
            if axes in seen_axes:
                continue
            eligible.append(donor)
            seen_axes.add(axes)
            if len(eligible) >= limit:
                break
        return eligible

    # Every donor was actually paid by selected Rust + live 2D in this same
    # search; neither the external reference nor previous P7 gates are donors.
    # A paid finalist must not hide *all* distinct balanced-elite talent/APL
    # combinations. Retain the three strongest eligible of each, deduplicated
    # by the actual axes being copied, so both paid search lineages are reachable.
    finalists_paid = distinct_paid_pairs(finalists, 3, 3)
    balanced_paid = distinct_paid_pairs(balanced_elites, 2, 3)
    donors = []
    seen_axes = set()
    for candidate in finalists_paid + balanced_paid:
        axes = (candidate["talentsString"],
                json.dumps(candidate["rotation"], sort_keys=True))
        if axes not in seen_axes:
            donors.append(candidate)
            seen_axes.add(axes)
    if not donors:
        return False
    donor = rng.choice(donors)
    player["talentsString"] = donor["talentsString"]
    player["rotation"] = copy.deepcopy(donor["rotation"])
    return True


def _paid_p75_apl_crossover(candidate, parent, finalists, balanced_elites, source, rng):
    """Transfer only the APL from a distinct genuinely paid cold-search donor.

    The exact selected-pin P7.5 axis ablation #41633601436 measured a large
    APL-only improvement, whereas a talent-only replacement was worse. The
    existing paid crossover always coupled talents and APL, preventing an
    independently strong policy from moving onto a different paid talent/gear
    background. No saved reference or historical winning build is a donor.
    """
    player = source.player(candidate)

    def distinct_paid_apls(rows, request_index):
        eligible = []
        seen = set()
        for row in sorted(rows, key=lambda row: row[0], reverse=True):
            paid = row[request_index]
            if paid == parent:
                continue
            rotation = source.player(paid)["rotation"]
            if rotation == player["rotation"]:
                continue
            key = json.dumps(rotation, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            eligible.append(rotation)
            if len(eligible) >= 3:
                break
        return eligible

    donors = []
    seen = set()
    for rotation in (distinct_paid_apls(finalists, 3) +
                     distinct_paid_apls(balanced_elites, 2)):
        key = json.dumps(rotation, sort_keys=True)
        if key not in seen:
            donors.append(rotation)
            seen.add(key)
    if not donors:
        return False
    player["rotation"] = copy.deepcopy(rng.choice(donors))
    return True


def _paid_p75_gear_block_crossover(candidate, parent, finalists,
                                    balanced_elites, source, rng):
    """Combine a block of gear/enchants from a distinct, paid cold-search donor.

    This constructs a candidate, not a legality certificate. Forward the
    composite to the selected MythicSim Rust sim --gate, whose VALID/INVALID/
    UNSUPPORTED/error decision is authoritative. No second Python gear veto.
    """
    items = source.player(candidate)["equipment"]["items"]

    def distinct_paid_gear(rows, request_index, limit):
        eligible = []
        for row in sorted(rows, key=lambda row: row[0], reverse=True):
            paid = row[request_index]
            if paid == parent:
                continue
            other = source.player(paid)["equipment"]["items"]
            if len(items) != len(other):
                continue
            different = [i for i in range(len(items))
                         if items[i] != other[i]]
            if len(different) >= 2:
                eligible.append((other, different))
                if len(eligible) >= limit:
                    break
        return eligible

    finalist_donors = distinct_paid_gear(finalists, 3, 3)
    balanced_donors = distinct_paid_gear(balanced_elites, 2, 6)
    if not finalist_donors and not balanced_donors:
        return False
    rng.shuffle(finalist_donors)
    rng.shuffle(balanced_donors)
    donors = finalist_donors + balanced_donors
    # The former first-element choice always picked a finalist when one
    # existed, making all independently paid balanced gear donors unreachable.
    # Shuffle the combined PAID pool so either lineage can propose a block;
    # selected MythicSim Rust remains the sole legality/scoring authority.
    rng.shuffle(donors)
    other, different = donors[0]
    selected = rng.sample(different, min(len(different), rng.randint(2, 5)))
    for i in selected:
        items[i] = copy.deepcopy(other[i])
    return True


def _paid_p75_gear_apl_crossover(candidate, parent, finalists,
                                 balanced_elites, source, rng):
    """Combine gear and APL from two different, genuinely paid candidates.

    Both donor identities must come from this independent cold search. The
    gear donor supplies a multi-slot item/enchant block; a second paid
    candidate supplies a distinct APL. Talents stay on the paid parent.
    This helper does not run Python gear legality: run_live sends the complete
    composite to selected Rust sim --gate before any live 2D score is paid.
    """
    candidate_player = source.player(candidate)
    items = candidate_player["equipment"]["items"]
    current_rotation = copy.deepcopy(candidate_player["rotation"])

    gear_donors = []
    seen_gear = set()

    def collect_gear(rows, candidate_index, sha_index, limit):
        added = 0
        for row in sorted(rows, key=lambda row: row[0], reverse=True):
            paid = row[candidate_index]
            paid_sha = row[sha_index]
            if paid == parent or paid_sha in seen_gear:
                continue
            other = source.player(paid)["equipment"]["items"]
            if len(items) != len(other):
                continue
            different = [i for i in range(len(items)) if items[i] != other[i]]
            if len(different) < 2:
                continue
            gear_donors.append((paid_sha, other, different))
            seen_gear.add(paid_sha)
            added += 1
            if added >= limit:
                break

    # Finalist rows: (score, live, candidate_sha, candidate, screen_score).
    # Elite rows: (score, candidate_sha, candidate).
    collect_gear(finalists, 3, 2, 3)
    collect_gear(balanced_elites, 2, 1, 6)

    apl_donors = []
    seen_apl_sha = set()

    def collect_apl(rows, candidate_index, sha_index, limit):
        added = 0
        for row in sorted(rows, key=lambda row: row[0], reverse=True):
            paid = row[candidate_index]
            paid_sha = row[sha_index]
            if paid == parent or paid_sha in seen_apl_sha:
                continue
            rotation = source.player(paid)["rotation"]
            if rotation == current_rotation:
                continue
            apl_donors.append((paid_sha, rotation))
            seen_apl_sha.add(paid_sha)
            added += 1
            if added >= limit:
                break

    collect_apl(finalists, 3, 2, 3)
    collect_apl(balanced_elites, 2, 1, 3)

    # Explicitly require different paid candidate identities for the two axes.
    pairs = [(gear, apl) for gear in gear_donors for apl in apl_donors
             if gear[0] != apl[0]]
    if not pairs:
        return False
    rng.shuffle(pairs)

    # One proposal yields one composite. The caller's selected Rust
    # native_source_control(sim --gate) is the only legality authority; a
    # native refusal ends this proposal rather than falling back to Python.
    (_, other, different), (_, rotation) = pairs[0]
    selected = rng.sample(
        different, min(len(different), rng.randint(2, 5)))
    mixed = copy.deepcopy(items)
    for i in selected:
        mixed[i] = copy.deepcopy(other[i])
    candidate_player["equipment"]["items"][:] = mixed
    candidate_player["rotation"] = copy.deepcopy(rotation)
    return True

def _p75_crossover_rng(proposal_index: int) -> random.Random:
    """Stable per-proposal randomness, isolated from candidate generation.

    Donor-pool size and crossover shuffle/sample calls must not advance the
    primary search RNG. Adding a paid donor should change only this proposal's
    crossover, not silently perturb every later cold candidate.
    """
    return random.Random(1_000_000 + proposal_index)


def run_live(root: Path, class_key: str, level: int, *,
             spec: str = "unrestricted") -> dict:
    # Approved P7.5 is a stationary native benchmark, not a world-ACK gate.
    # Keep the old Balance diagnostic path unchanged while migrating the
    # checkpoint-critical unrestricted route to direct selected-native calls.
    feral = spec == "feral"
    native_only = spec in ("unrestricted", "feral")
    prepared = (_pinned_source_runtime(
        root, class_key, level, spec, "P7.5", require_world=False)
        if native_only else _pinned_source_runtime(root, class_key, level, spec, "P7.5"))
    if isinstance(prepared, dict):
        return prepared
    base, meta, binary = prepared
    search_mode = os.environ.get("FOREVER_P7_FULL_SOURCE_SEARCH", "0")
    if search_mode not in ("0", "1"):
        return {"status": "BLOCKED",
                "reasons": ["P7_5_INVALID_FULL_SOURCE_SEARCH_MODE"]}
    full_search = search_mode == "1"
    strategy = os.environ.get("FOREVER_P7_SEARCH_STRATEGY", "default")
    if strategy not in ("default", "wf613"):
        return {"status": "BLOCKED",
                "reasons": ["P7_5_INVALID_SEARCH_STRATEGY"]}
    integration = root / "integrations/mythicsim-rust"
    sys.path.insert(0, str(integration))
    try:
        source = _source_module(integration / "p75_joint_search.py",
                                "p75_existing_source_native_joint_search")
    finally:
        sys.path.remove(str(integration))
    production = _source_module(integration / "live_world_probe.py",
                                "p75_production_native_world")
    if feral:
        # Reuse the same cold joint search with native-judged talent strings
        # and opaque Feral APL conditions; never use Balance rank rules.
        source.make_candidate = partial(
            source.make_candidate, talent_proposals=native_talent_proposals,
            preserve_source_conditions=True)
        gear_search = _source_module(integration / "p74_gear_search.py",
                                     "p75_pinned_rust_gear_options")
    # WF613 is a selectable producer policy, not a second simulator/gate.
    # Leave the default production search untouched for A/B comparison.
    wf613 = (_source_module(integration / "wf613_strategy.py",
                            "p75_wf613_paid_archive").WF613Controller()
             if strategy == "wf613" else None)
    upstream = binary.parents[2]
    catalogue = root / "data/forever/catalogue/items_2026-09-29.sqlite"
    items = upstream / "data/items.jsonl"
    enchants = upstream / "data/enchants.jsonl"
    if any(not x.is_file() for x in ((items, enchants) if feral
                                     else (catalogue, items, enchants))):
        return {"status": "BLOCKED",
                "reasons": ["P7_5_SOURCE_OR_PINNED_RUST_ITEM_DATA_MISSING"]}

    if feral:
        # The selected Rust item/enchant tables supply alternatives; native
        # sim --gate alone judges complete Feral gear/talent/APL requests.
        validator = None
    else:
        try:
            source.GearValidator.require_sqlite_catalogue(catalogue)
        except ValueError as exc:
            return {"status": "BLOCKED", "reasons": ["P7_5_" + str(exc)]}
        validator = source.GearValidator(catalogue, items, enchants, base)
    rng = random.Random(670)
    best = None  # three-fight balanced top result, only a diagnostic
    balanced_elites = []  # 24 distinct source-legal paid joint candidates
    balanced_finalists = []  # 2x3 balanced paid native+2D screens
    rerank_seen = set()
    confirmed = set()
    confirmation_attempted = set()
    deep_confirmation_attempted = set()
    deep_confirmed = set()
    rerank_failures = []
    balanced_parent_proposals = 0
    worst_finalist_s = 0.0
    worst_confirmation_s = 0.0
    executed = 0
    proposals = 0
    seen = set()
    failures = []
    search_start = time.monotonic()
    search_deadline = search_start + 300.0
    try:
        # Full search uses every source/Rust-admitted catalogue item per slot,
        # not just the 80 highest heuristic scores. Cold generator explores
        # this pool without seeding the saved build. After the first actually
        # paid winner, use its existing source mutation operator for 4/5 of
        # later proposals and fresh independent cold discovery for 1/5.
        # Enchants and effects remain subject to source verification.
        if feral:
            pools, enchant_pools, _ = gear_search.pinned_rust_candidate_pool(
                items, enchants)
        else:
            pools, _ = source.candidate_pool(
                validator, limit=None if full_search else 15,
                **({"independent_enchants": True} if full_search else {}))
            enchant_pools = (source.source_enchant_pools(validator, pools)
                             if full_search else None)
        distance = source.player(base)["distanceFromTarget"]
        while True:
            elapsed = time.monotonic() - search_start if full_search else 0.0
            if (full_search and elapsed >= 300.0
                    or not full_search and proposals >= 3):
                break
            # Real P7.5 #41565060685 screened 820.66 balanced DPS but
            # froze only 697.32 stochastic DPS. Spend part of the SAME
            # 300s budget on independent balanced native+2D finalist scores.
            if full_search and (elapsed >= 240.0 or
                                _p74_early_rerank_due(
                                    elapsed, len(balanced_finalists))):
                # P7.4 already confirms the strongest paid finalist
                # with 144 independent non-holdout fights. P7.5 formerly
                # stopped at 96, even after a measured 716.30 paid finalist
                # fell to 702.79 in its 1,000-fight frozen holdout.
                # Reuse its bounded two-deep-confirmation schedule with 3-fight
                # balanced paid screens; never select with the frozen holdout.
                next_deep = _next_p74_deep_confirmation(
                    balanced_finalists, confirmed,
                    deep_confirmation_attempted, elapsed)
                confirmation = next_deep or _next_p74_confirmation(
                    balanced_finalists, confirmation_attempted, elapsed)
                if confirmation is not None and _paid_step_has_budget(
                        search_start, max(worst_finalist_s,
                                          worst_confirmation_s)):
                    index, row = confirmation
                    is_deep = next_deep is not None
                    if is_deep:
                        deep_confirmation_attempted.add(row[2])
                    else:
                        confirmation_attempted.add(row[2])
                    started = time.perf_counter()
                    try:
                        second_score, second_live = _paid_p75_balanced_finalist(
                            production, binary, row[3], distance,
                            seeds=(("1955181", "1955207") if is_deep
                                   else ("1955113", "1955139")),
                            **({"native_only": True} if native_only else {}),
                             **({"go_rules": True} if feral else {}))
                        # Initial 6, confirmed 12, deep-confirmed 18
                        # genuine paid balanced fights: weight old 12-fight
                        # mean twice when incorporating the last 6.
                        new_score = ((2 * row[0] + second_score) / 3
                                     if is_deep else
                                     (row[0] + second_score) / 2)
                        balanced_finalists[index] = (
                            new_score, second_live, *row[2:])
                        if is_deep:
                            deep_confirmed.add(row[2])
                        else:
                            confirmed.add(row[2])
                    except (ValueError, RuntimeError, OSError, KeyError,
                            TimeoutError, TypeError, AssertionError,
                            subprocess.SubprocessError) as exc:
                        rerank_failures.append(
                            "CONFIRM:" + type(exc).__name__ + ":" + str(exc)[:160])
                    finally:
                        worst_confirmation_s = max(
                            worst_confirmation_s, time.perf_counter() - started)
                    continue
                pending = next((
                    row for row in balanced_elites
                    if row[1] not in rerank_seen), None)
                if pending is not None and _paid_step_has_budget(
                        search_start, worst_finalist_s):
                    screen_score, candidate_sha, candidate = pending
                    rerank_seen.add(candidate_sha)
                    started = time.perf_counter()
                    try:
                        balanced_score, balanced_live = _paid_p75_balanced_finalist(
                            production, binary, candidate, distance,
                            seeds=("1955004", "1955047"),
                            **({"native_only": True} if native_only else {}),
                             **({"go_rules": True} if feral else {}))
                        balanced_finalists.append((
                            balanced_score, balanced_live, candidate_sha,
                            candidate, screen_score))
                    except (ValueError, RuntimeError, OSError, KeyError,
                            TimeoutError, TypeError, AssertionError,
                            subprocess.SubprocessError) as exc:
                        rerank_failures.append(
                            type(exc).__name__ + ":" + str(exc)[:160])
                    finally:
                        worst_finalist_s = max(
                            worst_finalist_s, time.perf_counter() - started)
                    continue
            # Do not start an indivisible native+2D paid call in the tail
            # when measured subprocess cost would overrun the 300s search.
            if full_search and elapsed >= 290.0 and not _paid_step_has_budget(
                    search_start, worst_finalist_s):
                break
            proposals += 1
            try:
                # Only a winner already evaluated in THIS live 2D cold search
                # can be an elite. Never seed the saved report or P7.1-P7.4.
                if wf613 is not None:
                    elite, axes, family = wf613.propose(rng)
                    candidate = _cold_joint(
                        base, source, validator, pools, rng,
                        elite=elite, repair_axes=axes,
                        enchant_pools=enchant_pools)
                else:
                    elite = (_paid_p75_parent(
                        best, balanced_finalists, proposals, rng,
                        balanced_elites=balanced_elites)
                        if full_search else None)
                    if elite is not None and balanced_finalists and proposals % 3 != 0:
                        balanced_parent_proposals += 1
                    # A real paid elite may need coordinated gear/talent/APL
                    # edits to escape a single-axis local basin. Do not pass
                    # repair axes to independent cold restarts.
                    # Every thirteenth paid-parent proposal recombines
                    # independently PAID axes. Mutate source-legal gear from
                    # one paid parent, then copy the coherent talent+APL pair
                    # from a different paid parent (if one exists). This can
                    # explore combinations unavailable to single-axis edits.
                    crossover = (elite is not None and full_search
                                 and proposals % 13 == 0)
                    # Preserve seventh paired edits, eleventh rebuilds,
                    # thirteenth crossovers and fifth independent restarts.
                    # Other seventeenth proposals can combine intact blocks
                    # of gear from two independently scored PAID parents.
                    gear_crossover = (elite is not None and full_search
                                      and proposals % 17 == 0
                                      and proposals % 7 != 0
                                      and proposals % 11 != 0
                                      and not crossover)
                    # Ablation showed that a strong paid APL must be able to
                    # move independently of a weaker donor talent allocation.
                    # Keep the existing paired/rebuild/gear operators and cold
                    # restarts; never use historical or saved winners as donors.
                    apl_crossover = (elite is not None and full_search
                                     and proposals % 19 == 0
                                     and proposals % 7 != 0
                                     and proposals % 11 != 0
                                     and not crossover and not gear_crossover)
                    # Every twenty-third eligible paid-parent proposal
                    # combines a paid gear block and a distinct paid APL.
                    # No saved reference or previous-gate winner is a donor.
                    gear_apl_crossover = (
                        elite is not None and full_search
                        and proposals % 23 == 0
                        and proposals % 7 != 0 and proposals % 11 != 0
                        and not crossover and not gear_crossover
                        and not apl_crossover)
                    repair_axes = (("rotation",) if apl_crossover
                                   else ("gear",) if (crossover or gear_crossover
                                                       or gear_apl_crossover)
                                   else _p75_paid_joint_axes(proposals)
                                   if elite is not None and full_search else None)
                    if (repair_axes is None and elite is not None
                            and full_search):
                        repair_axes = _p75_paid_rebuild_axes(proposals)
                    candidate = _cold_joint(
                        base, source, validator, pools, rng,
                        elite=elite, enchant_pools=enchant_pools,
                        repair_axes=repair_axes)
                    crossover_rng = _p75_crossover_rng(proposals)
                    if crossover:
                        _paid_p75_crossover(
                            candidate, elite, balanced_finalists,
                            balanced_elites, source, crossover_rng)
                    elif apl_crossover:
                        _paid_p75_apl_crossover(
                            candidate, elite, balanced_finalists,
                            balanced_elites, source, crossover_rng)
                    elif gear_crossover:
                        _paid_p75_gear_block_crossover(
                            candidate, elite, balanced_finalists,
                            balanced_elites, source, crossover_rng)
                    elif gear_apl_crossover:
                        _paid_p75_gear_apl_crossover(
                            candidate, elite, balanced_finalists,
                            balanced_elites, source, crossover_rng)
                candidate_sha = hashlib.sha256(json.dumps(
                    candidate, sort_keys=True).encode()).hexdigest()
                if candidate_sha in seen:
                    continue  # no repeated balanced-RNG paid score
                seen.add(candidate_sha)
                with tempfile.TemporaryDirectory(prefix="forever_p75_live_") as tmp:
                    path = Path(tmp) / "cold-full-source-build.json"
                    path.write_text(json.dumps(candidate))
                    # Composite gear+APL candidates reach the selected Rust
                    # --gate without a second Python legality decision.
                    native = production.native_source_control(
                        binary, path, 3, rng_mode="balanced",
                        **({"go_rules": True} if feral else {}))
                    if native_only:
                        if type(native.get("iterations")) is not int or native["iterations"] != 3:
                            raise ValueError("P7_5_NATIVE_SCREEN_ITERATIONS_INVALID")
                        live = native
                        score = float(native["native_dps"])
                    else:
                        live = production.run(
                            binary, path, distance=distance, iterations=3,
                            rng_mode="balanced")
                        mismatch = _source_native_world_parity(native, live, 3)
                        if mismatch is not None:
                            raise ValueError("P7_5_" + mismatch)
                        if (live.get("iterations_done") != 3
                                or live.get("native_damage_events", 0) <= 0
                                or live.get("native_world_ticks", 0) <= 0):
                            raise ValueError("SOURCE_JOINT_NATIVE_WORLD_EXECUTION_INCOMPLETE")
                        score = float(live["world_mean_dps"])
                if not 0 <= score < float("inf"):
                    raise ValueError("SOURCE_JOINT_NATIVE_WORLD_DPS_INVALID")
                executed += 1
                balanced_elites.append((score, candidate_sha, candidate))
                balanced_elites.sort(key=lambda row: row[0], reverse=True)
                del balanced_elites[24:]
                if wf613 is not None:
                    wf613.observe(candidate, score, family)
                if best is None or score > best[0]:
                    best = (score, live, candidate_sha, candidate)
            except (ValueError, RuntimeError, OSError, KeyError, TimeoutError,
                    TypeError, AssertionError, subprocess.SubprocessError) as exc:
                failures.append(type(exc).__name__ + ":" + str(exc)[:180])
    finally:
        if validator is not None:
            validator.close()
    if full_search and elapsed < 300.0:
        # If a measured paid step cannot fit, complete the original window.
        # No extra clock read when the loop already reached its deadline.
        time.sleep(max(0.0, search_deadline - time.monotonic()))
    search_observed_at = time.monotonic()
    search_wall_s = search_observed_at - search_start
    search_window_met = p7_search_window_completed(
        full_search=full_search, elapsed_seconds=search_wall_s,
    )
    if best is None:
        return {"status": "FAIL",
                "reasons": ["P7_5_NO_SOURCE_LEGAL_JOINT_CANDIDATE_REACHED_NATIVE_WORLD"],
                "production_engine": ("pinned_mythicsim_rust_native" if native_only
                                      else "pinned_mythicsim_rust_gsim_2d"),
                "search_wall_s": search_wall_s,
                "cold_candidate_failures": failures[:4]}

    (score, live, candidate_sha, frozen_winner,
     selected_balanced_score, selected_validation) = _freeze_paid_p75_balanced_winner(
        best, balanced_finalists, confirmed, deep_confirmed)
    complete_search = search_window_met
    final = {}
    if complete_search:
        # Freeze the winning legal request BEFORE independent stochastic
        # native and 2D evaluation, never use holdout to select a winner.
        try:
            with tempfile.TemporaryDirectory(prefix="forever_p75_frozen_") as tmp:
                frozen_path = Path(tmp) / "frozen-joint-winner.json"
                frozen_path.write_text(json.dumps(frozen_winner))
                frozen_sha = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
                n = P7_FINAL_STOCHASTIC_ITERATIONS
                native = production.native_source_control(
                    binary, frozen_path, n, rng_mode="stochastic",
                    **({"go_rules": True} if feral else {}))
                native_dps = float(native["native_dps"])
                if native_only:
                    if (type(native.get("iterations")) is not int
                            or native["iterations"] != n
                            or not 0 <= native_dps < float("inf")):
                        raise ValueError("P7_5_FROZEN_STOCHASTIC_NATIVE_INVALID")
                    reference_only_floor = (P7_5_FINAL_DPS_FLOOR_FRACTION
                                            * float(meta["reference_dps"]))
                    final = {
                        "frozen_request_raw_sha256": frozen_sha,
                        "frozen_stochastic_iterations": n,
                        "frozen_stochastic_native_dps": native_dps,
                        "frozen_stochastic_external_only_floor_met": (
                            native_dps >= reference_only_floor),
                    }
                else:
                    world = production.run(
                        binary, frozen_path, distance=distance, iterations=n,
                        rng_mode="stochastic")
                    mismatch = _source_native_world_parity(
                        native, world, n, expected_raw_sha=frozen_sha)
                    if mismatch is not None:
                        raise ValueError("FROZEN_STOCHASTIC_NATIVE_WORLD_PARITY:" + mismatch)
                    world_dps = float(world["world_mean_dps"])
                    if not (0 <= native_dps < float("inf")
                            and 0 <= world_dps < float("inf")
                            and int(world["native_damage_events"]) > 0
                            and int(world["native_world_ticks"]) > 0):
                        raise ValueError("P7_5_FROZEN_STOCHASTIC_WORLD_INVALID")
                    reference_only_floor = (P7_5_FINAL_DPS_FLOOR_FRACTION
                                            * float(meta["reference_dps"]))
                    final = {
                        "frozen_request_raw_sha256": frozen_sha,
                        "frozen_stochastic_iterations": n,
                        "frozen_stochastic_native_dps": native_dps,
                        "frozen_stochastic_world_dps": world_dps,
                        "frozen_stochastic_world_damage_events": int(world["native_damage_events"]),
                        "frozen_stochastic_world_boundaries": int(world["native_world_ticks"]),
                        "frozen_stochastic_external_only_floor_met": (
                            native_dps >= reference_only_floor
                            and world_dps >= reference_only_floor),
                    }
        except (ValueError, RuntimeError, OSError, KeyError, TimeoutError,
                TypeError, AssertionError, subprocess.SubprocessError) as exc:
            final = {"frozen_stochastic_failure":
                     type(exc).__name__ + ":" + str(exc)[:180]}

    # Compare the independent frozen P7.5 holdout against genuine compatible
    # previously accepted results, never against search-screen estimates.
    # Missing numeric receipts preserve the existing fail-closed BLOCKED state.
    # Resolve the accepted comparator for both bounded light probes and
    # full searches. A light probe needs the same numeric objective floor in
    # its diagnostic receipt; the independent 300s search and 1,000-stochastic
    # holdout requirements below still gate PASS.
    prior = strongest_accepted_prior(
        root, class_key, level, spec,
        engine_revision=meta.get("selected_engine_revision", PINNED_RUST),
        source_sha256=meta.get("source_request_raw_sha256",
                                   SAVED_FERAL_RAW_SHA if feral else SAVED_BALANCE_RAW_SHA),
        reference_dps=float(meta["reference_dps"]))
    prior_dps = prior["dps"] if prior is not None else None
    required = (p7_required_dps(
        "P7.5", float(meta["reference_dps"]),
        strongest_accepted_compatible_prior=(
            prior_dps if prior_dps is not None else float(meta["reference_dps"])))
        if native_only or prior_dps is not None else None)
    # Optional axis stochastic evidence is not a prerequisite. The native
    # unrestricted target uses the pinned reference when none qualifies.
    reasons = ([] if native_only or prior is not None else [
        "P7_5_ACCEPTED_COMPATIBLE_PRIOR_REQUIRED_FOR_FINAL_DPS_FLOOR"])
    if not full_search:
        reasons.append("P7_5_FULL_300S_COLD_SEARCH_AND_1000_STOCHASTIC_HOLDOUT_NOT_EXECUTED")
    elif not search_window_met:
        reasons.append("P7_5_300S_SEARCH_NOT_COMPLETED")
    if "frozen_stochastic_iterations" not in final:
        reasons.append("P7_5_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED")
    elif not final["frozen_stochastic_external_only_floor_met"]:
        reasons.append("P7_5_FROZEN_STOCHASTIC_DPS_BELOW_EXTERNAL_ONLY_FLOOR")
    elif required is not None and (
            final["frozen_stochastic_native_dps"] < required
            or (not native_only and final["frozen_stochastic_world_dps"] < required)):
        reasons.append("P7_5_FROZEN_STOCHASTIC_DPS_BELOW_ACCEPTED_PRIOR_FLOOR")
    # An unestablished accepted-compatible prior is a missing *comparison*,
    # not evidence that combat/search failed. Label a genuine full-run budget,
    # final-holdout or external-DPS failure as FAIL; otherwise remain BLOCKED.
    # This does not confer PASS without the required approved prior.
    failed_execution = full_search and any(reason in {
        "P7_5_300S_SEARCH_NOT_COMPLETED",
        "P7_5_SEARCH_BUDGET_OVERRUN",
        "P7_5_1000_STOCHASTIC_HOLDOUT_NOT_VERIFIED",
        "P7_5_FROZEN_STOCHASTIC_DPS_BELOW_EXTERNAL_ONLY_FLOOR",
        "P7_5_FROZEN_STOCHASTIC_DPS_BELOW_ACCEPTED_PRIOR_FLOOR",
    } for reason in reasons)
    # Preserve the actual independently paid frozen winner in the production
    # result. A SHA alone cannot reveal which gear/talents/APL caused a measured
    # failure, and a later heavy rerun must not be needed just to inspect it.
    # This is diagnostics only: neither candidate selection nor gate predicates
    # change, and no reference/prior winning build is used as a search seed.
    selected_player = source.player(frozen_winner)
    frozen_source_build = {
        "equipment": selected_player["equipment"],
        "talentsString": selected_player["talentsString"],
        "rotation": selected_player["rotation"],
    }
    return {
        "status": ("FAIL" if failed_execution else
                   "BLOCKED" if reasons else "PASS"),
        "reasons": reasons,
        "production_engine": ("pinned_mythicsim_rust_native" if native_only
                              else "pinned_mythicsim_rust_gsim_2d"),
        "production_component": "integrations/mythicsim-rust/live_world_probe.py",
        "native_source_revision": meta.get("selected_engine_revision", PINNED_RUST),
        "source_request_raw_sha256": meta.get(
            "source_request_raw_sha256", SAVED_FERAL_RAW_SHA if feral else SAVED_BALANCE_RAW_SHA),
        "native_rules": "go_reference" if feral else "forever",
        "reference_profile": meta.get("selected_reference_profile"),
        "checkpoint_spec": spec,
        "saved_reference_dps": float(meta["reference_dps"]),
        **({"joint_cold_native_dps": score} if native_only
           else {"joint_cold_world_dps": score}),
        "cold_balanced_screen_best_dps": best[0],
        "selected_balanced_screen_dps": selected_balanced_score,
        "paid_joint_balanced_finalists": len(balanced_finalists),
        "paid_joint_balanced_confirmed": len(confirmed),
        "paid_joint_balanced_deep_confirmed": len(deep_confirmed),
        "balanced_parent_proposals": balanced_parent_proposals,
        "balanced_finalist_failures": rerank_failures[:4],
        "external_reference_only_floor": (P7_5_FINAL_DPS_FLOOR_FRACTION
                                          * float(meta["reference_dps"])),
        "final_required_dps": required,
        "strongest_accepted_compatible_prior_dps": prior_dps,
        "accepted_compatible_prior_gates": (
            prior["compatible_gates"] if prior is not None else []),
        "accepted_compatible_prior_run_urls": (
            prior["run_urls"] if prior is not None else []),
        # The best cold three-fight screen and the selected paid balanced
        # finalist can be different builds. Both fingerprints use canonical
        # JSON; frozen_request_raw_sha256 separately hashes the exact 1,000-
        # fight request bytes for native↔world provenance.
        "cold_winner_request_sha256": best[2],
        "selected_balanced_request_sha256": candidate_sha,
        "frozen_source_build": frozen_source_build,
        "search_wall_s": search_wall_s,
        "independent_300s_search_requested": full_search,
        "independent_300s_search_completed": complete_search,
        "search_window_met": search_window_met,
        "search_deadline_observed_elapsed_s": round(search_wall_s, 6),
        "cold_unique_source_requests": len(seen),
        **final,
        **(_executed_p7_runtime_proof(
            "P7.5", final["frozen_request_raw_sha256"],
            engine_revision=meta.get("selected_engine_revision", PINNED_RUST))
           if complete_search and not reasons and "frozen_request_raw_sha256" in final else {}),
        **({} if native_only else {
            "world_damage_events": int(live["native_damage_events"]),
            "world_boundaries": int(live["native_world_ticks"])}),
        "source_legal_joint_candidates_paid": executed,
        "search_strategy": strategy,
        **(wf613.diagnostics() if wf613 is not None else {}),
        "cold_candidate_failures": failures[:4],
        "selected_validation": selected_validation,
        "search_rng_mode": "balanced",
        "coverage_scope_complete": False,
    }
