"""One-request source-native class/level-range performance optimizer.

Forever owns the search frontier and objective aggregation, not Warcraft rules.
The supplied evaluator must call the pinned Rust source/native execution path and
return its *observed* receipt for each proposal.  Missing full-resource recovery
or unproved cross-level ancestry is never upgraded to a comparable score.

Sparse checkpoints are samples of an objective, NOT a complete leveling route.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any


def sampled_levels(start_level: int, end_level: int, level_stride: int) -> tuple[int, ...]:
    if (type(start_level) is not int or type(end_level) is not int
            or type(level_stride) is not int or not 10 <= start_level <= end_level <= 60
            or level_stride < 1):
        raise ValueError("invalid 10..60 level range/stride")
    levels = list(range(start_level, end_level + 1, level_stride))
    if levels[-1] != end_level:
        levels.append(end_level)
    return tuple(levels)


def _positive_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        ch in "0123456789abcdef" for ch in value
    )


def _receipt_error(
    row: Mapping[str, Any], *, level: int, parent: Mapping[str, Any] | None,
    mob_count: int, rng_mode: str, iterations: int,
) -> str | None:
    """Validate Forever transport/objective completeness, never Rust legality."""
    # The native scorer explicitly classifies fully paid success. A refusal or
    # missing status must not become a ranked performance result merely because
    # another transport layer happened to retain positive ACK/resource fields.
    if row.get("status") != "MEASURED_NATIVE_FULLY_RECOVERED":
        return "native measured full-recovery status missing"
    if row.get("native_prepared") is not True or row.get("native_world_ack") is not True:
        return "native prepare/world ACK missing"
    if (row.get("level") != level or row.get("mob_count") != mob_count
            or row.get("targets_killed") != mob_count
            or row.get("rng_mode") != rng_mode or row.get("iterations") != iterations):
        return "native scenario/target/seed contract mismatch"
    if not (_sha(row.get("source_request_sha256"))
            and _sha(row.get("engine_binary_sha256"))):
        return "native source/binary identity missing"
    if (row.get("native_full_recovery_paid") is not True
            or row.get("recover_to_full") is not True):
        return "native terminal full recovery not paid"
    for name in ("terminal_hp", "terminal_max_hp", "terminal_mana", "terminal_max_mana"):
        value = row.get(name)
        if type(value) not in (int, float) or not math.isfinite(value):
            return "native terminal resources missing"
    if row["terminal_max_hp"] <= 0 or row["terminal_max_mana"] <= 0:
        return "native resource maxima missing"
    if (abs(row["terminal_hp"] - row["terminal_max_hp"]) > 1e-6
            or abs(row["terminal_mana"] - row["terminal_max_mana"]) > 1e-6):
        return "native terminal HP and mana not both full"
    elapsed = row.get("elapsed_seconds")
    recovery = row.get("terminal_recovery_seconds")
    if (not _positive_number(elapsed)
            or type(recovery) not in (int, float) or not math.isfinite(recovery)
            or recovery < 0 or recovery > elapsed):
        return "native charged elapsed/recovery clock missing"
    policy = row.get("native_world_policy")
    if isinstance(policy, Mapping) and policy.get("pull_mode") == "rolling":
        if (row.get("native_world_apl") != policy.get("world_apl")
                or row.get("native_world_overlap_verified") is not True
                or not isinstance(row.get("native_world_overlap"), Mapping)):
            return "rolling World-APL lacks source-applied two-live-target ACK evidence"
        kills = row.get("native_world_kills")
        overlap = row["native_world_overlap"]
        if (overlap.get("max_concurrent_alive_targets") != 2
                or type(overlap.get("old_target_dot_ticks_after_switch_acked"))
                   is not int
                or overlap["old_target_dot_ticks_after_switch_acked"] < 1
                or overlap.get("first_b_source_hit_while_old_a_alive") is not True):
            return "native two-live-target first-hit/old-target DoT ACK missing"
        if (not isinstance(kills, list) or len(kills) != 2
                or any(not isinstance(kill, Mapping) for kill in kills)):
            return "rolling World-APL distinct world kills/ACK IDs missing"
        target_ids = [kill.get("target_id") for kill in kills]
        ack_ids = [kill.get("ack_sha256") for kill in kills]
        if (any(not isinstance(value, str) or not value
                for value in (*target_ids, *ack_ids))
                or len(set(target_ids)) != 2 or len(set(ack_ids)) != 2):
            return "rolling World-APL distinct world kills/ACK IDs missing"
        # Two deaths and an aggregate DoT-tick count do not establish that
        # native damage was routed to the same two gsim world targets.
        # Require the exact source-emitted live IDs and causal ID map before
        # charging a rolling-policy result or ranking it as measured overlap.
        live_ids = overlap.get("simultaneously_alive_world_target_ids")
        mapping = overlap.get("native_target_to_world_id")
        if (not isinstance(live_ids, list) or len(live_ids) != 2
                or any(not isinstance(value, str) or not value
                       for value in live_ids)
                or set(live_ids) != set(target_ids)
                or not isinstance(mapping, Mapping) or len(mapping) != 2
                # Only the two requested native 0/1 slots can be bound to
                # the two living gsim targets, not arbitrary numeric keys.
                or set(mapping) != {"0", "1"}
                or any(not isinstance(value, str) or not value
                       for value in mapping.values())
                or set(mapping.values()) != set(target_ids)):
            return "rolling World-APL native/world causal ID map missing"
    if parent is not None:
        if row.get("engine_binary_sha256") != parent["engine_binary_sha256"]:
            return "cross-engine path is not comparable"
        if (row.get("native_parent_source_sha256") != parent["source_request_sha256"]
                or row.get("native_continuity_ack") is not True
                or row.get("native_continuity_from_level") != parent["level"]):
            return "native continuing talent/actor edge unproved"
    return None




def measured_world_rest_head_to_head(result: Mapping[str, Any], *, level: int) -> dict[str, Any]:
    """Compare only two paid rest policies on one identical native-prepared build.

    The usual ranked path may legitimately contain just a full-rest baseline.
    That is not evidence that the opt-in 30% policy was executable or faster.
    Rust/gsim owns the actual rest decision and threshold acknowledgement.
    """
    rows = result.get("independent_level_rankings", {}).get(str(level), [])
    accepted: dict[tuple[float, float], list[Mapping[str, Any]]] = {
        (1.0, 1.0): [], (0.3, 0.3): [],
    }
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        receipt = row.get("receipt")
        policy = row.get("native_world_policy")
        if not isinstance(receipt, Mapping) or not isinstance(policy, Mapping):
            continue
        thresholds = (policy.get("rest_when_health_below"),
                      policy.get("rest_when_mana_below"))
        if thresholds not in accepted or policy != receipt.get("native_world_policy"):
            continue
        if (_receipt_error(
                receipt, level=level, parent=None, mob_count=result["mob_count"],
                rng_mode=result["rng_mode"], iterations=result["iterations"]
            ) is not None or any(
                row.get(field) != receipt.get(field)
                for field in ("source_request_sha256", "engine_binary_sha256",
                              "talents", "gear", "apl", "pet")
            ) or any(
                row.get(projection) != receipt.get(original)
                for projection, original in (
                    ("native_elapsed_seconds", "elapsed_seconds"),
                    ("terminal_recovery_seconds", "terminal_recovery_seconds"),
                )
            ) or not _sha(receipt.get("native_raw_receipt_sha256"))
                or not receipt.get("native_raw_receipt_file")):
            continue
        accepted[thresholds].append(row)

    def identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (row["source_request_sha256"], row["engine_binary_sha256"],
                json.dumps([row.get(field) for field in
                            ("talents", "gear", "apl", "pet")],
                           sort_keys=True, separators=(",", ":")))

    pairs = [(full, thirty) for full in accepted[(1.0, 1.0)]
             for thirty in accepted[(0.3, 0.3)]
             if identity(full) == identity(thirty)]
    refusals = [
        row for row in result.get("rejected_native_attempts", [])
        if isinstance(row, Mapping) and row.get("level") == level
        and (row.get("proposal_axis") == "world_rest_30pct"
             or (isinstance(row.get("native_world_policy"), Mapping)
                 and row["native_world_policy"].get("rest_when_health_below") == 0.3
                 and row["native_world_policy"].get("rest_when_mana_below") == 0.3))
    ]
    summary: dict[str, Any] = {
        "status": "NATIVE_REST_HEAD_TO_HEAD_INCOMPLETE",
        "level": level, "mob_count": result["mob_count"],
        "balanced_rng": result["rng_mode"] == "balanced",
        "full_rest_paid_candidates": len(accepted[(1.0, 1.0)]),
        "thirty_percent_paid_candidates": len(accepted[(0.3, 0.3)]),
        "thirty_percent_refusals": refusals,
        "winner": None,
        "baseline": None, "thirty_percent": None,
        "full_minus_thirty_elapsed_seconds": None,
    }
    if not pairs:
        return summary

    full, thirty = min(pairs, key=lambda pair: (
        min(pair[0]["native_elapsed_seconds"], pair[1]["native_elapsed_seconds"]),
        pair[0]["source_request_sha256"]))
    def evidence(row: Mapping[str, Any]) -> dict[str, Any]:
        paid = row["receipt"]
        return {
            "source_request_sha256": row["source_request_sha256"],
            "engine_binary_sha256": row["engine_binary_sha256"],
            "native_raw_receipt_sha256": paid["native_raw_receipt_sha256"],
            "native_raw_receipt_file": paid["native_raw_receipt_file"],
            "charged_elapsed_seconds": paid["elapsed_seconds"],
            "terminal_recovery_seconds": paid["terminal_recovery_seconds"],
            "terminal_hp": paid["terminal_hp"],
            "terminal_max_hp": paid["terminal_max_hp"],
            "terminal_mana": paid["terminal_mana"],
            "terminal_max_mana": paid["terminal_max_mana"],
            "reused_exact_native_paid_receipt": paid.get(
                "reused_exact_native_paid_receipt", False),
        }
    full_seconds = float(full["native_elapsed_seconds"])
    thirty_seconds = float(thirty["native_elapsed_seconds"])
    summary.update({
        "status": "MEASURED_NATIVE_REST_HEAD_TO_HEAD",
        "winner": ("thirty_percent" if thirty_seconds < full_seconds
                   else "full_rest" if full_seconds < thirty_seconds else "tie"),
        "baseline": evidence(full),
        "thirty_percent": evidence(thirty),
        "full_minus_thirty_elapsed_seconds": full_seconds - thirty_seconds,
    })
    return summary


def measured_world_rolling_head_to_head(
        result: Mapping[str, Any], *, level: int) -> dict[str, Any]:
    """Rank only source-ACKed simultaneous worlds against an identical serial build.

    A newly requested 50%-HP switch is not evidence of two live enemies;
    serial receipts and unacknowledged native policies remain unranked.
    """
    rows = result.get("independent_level_rankings", {}).get(str(level), [])
    accepted = {"serial": [], "rolling": []}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        paid = row.get("receipt")
        policy = row.get("native_world_policy")
        if (not isinstance(paid, Mapping) or not isinstance(policy, Mapping)
                or policy != paid.get("native_world_policy")
                or _receipt_error(
                    paid, level=level, parent=None, mob_count=result["mob_count"],
                    rng_mode=result["rng_mode"], iterations=result["iterations"]
                ) is not None
                or not _sha(paid.get("native_raw_receipt_sha256"))
                or not paid.get("native_raw_receipt_file")
                or not _positive_number(paid.get("native_world_target_hp"))
                or row.get("native_elapsed_seconds") != paid.get("elapsed_seconds")
                or row.get("terminal_recovery_seconds")
                   != paid.get("terminal_recovery_seconds")
                or any(row.get(field) != paid.get(field)
                       for field in ("source_request_sha256", "engine_binary_sha256",
                                     "talents", "gear", "apl", "pet"))):
            continue
        # Isolate pull scheduling: do not compare a rolling 30%-rest result
        # against the full-rest serial control and attribute the gap to DoTs.
        rest_matched = (
            policy.get("rest_when_health_below") == 1.0
            and policy.get("rest_when_mana_below") == 1.0
            and policy.get("rest_until") == "full_when_triggered"
            and policy.get("terminal_full_hp_and_mana") is True
        )
        mode = policy.get("pull_mode")
        if (mode == "serial" and rest_matched and "world_apl" not in policy
                and paid.get("native_world_apl") is None
                and paid.get("native_world_overlap_verified") is not True
                and paid.get("native_world_overlap") is None):
            accepted["serial"].append(row)
        elif (mode == "rolling" and rest_matched
                and policy.get("world_apl") == {
                    "pull_mode": "rolling",
                    "switch_trigger": {
                        "type": "current_target_hp_fraction_at_most",
                        "fraction": 0.5,
                    },
                    "max_live_targets": 2,
                }
                and paid.get("native_world_overlap_verified") is True
                and paid.get("native_world_apl") == policy.get("world_apl")):
            accepted["rolling"].append(row)

    def build_key(row):
        return (row["source_request_sha256"], row["engine_binary_sha256"],
                json.dumps([row.get(field) for field in
                            ("talents", "gear", "apl", "pet")],
                           sort_keys=True, separators=(",", ":")))

    pairs = [(serial, rolling)
             for serial in accepted["serial"]
             for rolling in accepted["rolling"]
             if (build_key(serial) == build_key(rolling)
                 # Prepared actor identity alone cannot establish the same
                 # hostile HP: world target HP is supplied outside Rust
                 # prepare by the paid 2D scenario.
                 and serial["receipt"]["native_world_target_hp"]
                     == rolling["receipt"]["native_world_target_hp"]
                 # One raw native run cannot be reused/relabelled as both
                 # independently executed policies.
                 and serial["receipt"]["native_raw_receipt_sha256"]
                     != rolling["receipt"]["native_raw_receipt_sha256"])]
    refusals = [row for row in result.get("rejected_native_attempts", [])
                if isinstance(row, Mapping) and row.get("level") == level
                and row.get("proposal_axis") == "world_rolling_50pct"]
    summary = {
        "status": "NATIVE_ROLLING_WORLD_APL_INCOMPLETE",
        "level": level, "mob_count": result["mob_count"],
        "serial_paid_candidates": len(accepted["serial"]),
        "rolling_overlap_paid_candidates": len(accepted["rolling"]),
        "rolling_refusals": refusals,
        "winner": None, "baseline": None, "rolling": None,
        "serial_minus_rolling_elapsed_seconds": None,
    }
    if not pairs:
        return summary

    serial, rolling = min(pairs, key=lambda pair: (
        min(pair[0]["native_elapsed_seconds"], pair[1]["native_elapsed_seconds"]),
        pair[0]["source_request_sha256"]))
    def evidence(row):
        paid = row["receipt"]
        return {
            "source_request_sha256": paid["source_request_sha256"],
            "engine_binary_sha256": paid["engine_binary_sha256"],
            "native_raw_receipt_file": paid["native_raw_receipt_file"],
            "native_raw_receipt_sha256": paid["native_raw_receipt_sha256"],
            "native_world_target_hp": paid["native_world_target_hp"],
            "native_world_policy": paid["native_world_policy"],
            "charged_elapsed_seconds": paid["elapsed_seconds"],
            "terminal_recovery_seconds": paid["terminal_recovery_seconds"],
            "reused_exact_native_paid_receipt": paid.get(
                "reused_exact_native_paid_receipt", False),
            "terminal_hp": paid["terminal_hp"],
            "terminal_max_hp": paid["terminal_max_hp"],
            "terminal_mana": paid["terminal_mana"],
            "terminal_max_mana": paid["terminal_max_mana"],
            "native_world_overlap": paid.get("native_world_overlap"),
            "native_world_kills": paid.get("native_world_kills"),
        }
    serial_time, rolling_time = (
        float(serial["native_elapsed_seconds"]),
        float(rolling["native_elapsed_seconds"]),
    )
    summary.update({
        "status": "MEASURED_NATIVE_ROLLING_WORLD_APL_HEAD_TO_HEAD",
        "winner": ("rolling" if rolling_time < serial_time
                   else "serial" if serial_time < rolling_time else "tie"),
        "baseline": evidence(serial),
        "rolling": evidence(rolling),
        "serial_minus_rolling_elapsed_seconds": serial_time - rolling_time,
    })
    return summary


def _retained_native_paid_axis_breadth(
    result: Mapping[str, Any], level: int,
) -> tuple[int, dict[str, int]] | None:
    """Describe observed axis breadth, not source legality or an optimum.

    Include only native-prepared, fully recovered independent candidates
    whose original paid receipt agrees with the ranked build fields.
    Refusals, rejected attempts and unmeasured proposals never count.
    """
    import json

    rankings = result.get("independent_level_rankings")
    rows = rankings.get(str(level)) if isinstance(rankings, Mapping) else None
    if not isinstance(rows, list):
        return None
    paid = []
    fields = ("source_request_sha256", "engine_binary_sha256",
              "talents", "gear", "apl", "pet")
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        receipt = row.get("receipt")
        if (not isinstance(receipt, Mapping)
                or _receipt_error(
                    receipt, level=level, parent=None,
                    mob_count=result["mob_count"], rng_mode=result["rng_mode"],
                    iterations=result["iterations"],
                ) is not None
                or any(row.get(field) != receipt.get(field)
                       for field in fields)):
            continue
        paid.append(row)
    if not paid:
        return None
    return len(paid), {
        field: len({json.dumps(row.get(field), sort_keys=True,
                               separators=(",", ":")) for row in paid})
        for field in ("talents", "gear", "apl", "pet")
    }


def _talent_ranks(serialized: Any) -> tuple[tuple[int, ...], ...] | None:
    """Read a native-request talent allocation; do not judge Warcraft legality."""
    if not isinstance(serialized, str):
        return None
    parts = serialized.split("-")
    if len(parts) != 3 or not all(p.isascii() and p.isdigit() for p in parts):
        return None
    return tuple(tuple(int(x) for x in p) for p in parts)


def _no_respec_successor(before: Any, after: Any) -> bool:
    """A sampled allocation can retain or add ranks without deleting old ranks.

    This is the requested no-respec route constraint, NOT a claim of legal
    intermediate talent spends or a substitute for source-native prepare.
    """
    old, new = _talent_ranks(before), _talent_ranks(after)
    if old is None or new is None:
        return False
    return all(
        all((a[i] if i < len(a) else 0) <= (b[i] if i < len(b) else 0)
            for i in range(max(len(a), len(b))))
        for a, b in zip(old, new)
    )


def _optimize_compatible_samples(
    start_level: int, end_level: int, level_stride: int, mob_count: int,
    budget: int, *, evaluate: Callable[..., Sequence[Mapping[str, Any]]],
    beam_width: int, rng_mode: str, iterations: int,
    class_name: str, talent_tree: str, backend: str,
) -> dict[str, Any]:
    """Select one coherent no-respec allocation from native-paid sparse anchors.

    Only sampled levels execute combat. The candidate builds must be source-
    prepared at their sampled levels; no infill simulations, historical route
    JSON, free respec, or unsupported intermediate-world claim is introduced.
    """
    levels = sampled_levels(start_level, end_level, level_stride)
    # Reserve part of a normal paid budget for later-level winner ancestry.
    # With tiny budgets, preserve at least two root probes per sampled level.
    # Native attempts (including refusals) are still charged exactly once.
    initial_budget = (
        budget if budget <= 2 * len(levels)
        else max(2 * len(levels), int(budget * 0.6))
    )
    # Later samples must also try actual native-paid *earlier* build
    # families, not merely disconnected L20 seed-tree mutations. Retain
    # each parent from the real scored evaluator; no skipped-level combat,
    # inferred actor continuation or Python Warcraft legality is asserted.
    from inspect import Parameter, signature
    try:
        parameters = signature(evaluate).parameters
        supports_hints = ("candidate_hints" in parameters or any(
            parameter.kind is Parameter.VAR_KEYWORD
            for parameter in parameters.values()))
    except (TypeError, ValueError):
        supports_hints = False
    paid_by_level: dict[int, list[Mapping[str, Any]]] = {}

    def forward_seeded_evaluator(**request):
        idx = levels.index(request["level"])
        previous = paid_by_level.get(levels[idx - 1], []) if idx else []
        if previous and supports_hints:
            request["candidate_hints"] = [{
                "talents": row["talents"], "from_level": levels[idx - 1],
                "source_request_sha256": row["source_request_sha256"],
            } for row in sorted(previous, key=lambda r: (
                r["elapsed_seconds"], r["source_request_sha256"]))
                if _talent_ranks(row.get("talents")) is not None][
                    :max(beam_width * 2, 6)]
        rows = evaluate(**request)
        if (isinstance(rows, Sequence)
                and not isinstance(rows, (str, bytes))):
            paid_by_level.setdefault(request["level"], []).extend(
                row for row in rows if isinstance(row, Mapping)
                and _receipt_error(
                    row, level=request["level"], parent=None,
                    mob_count=mob_count, rng_mode=rng_mode,
                    iterations=iterations) is None)
        return rows

    measured = optimize(
        start_level, end_level, level_stride, mob_count, initial_budget,
        evaluate=forward_seeded_evaluator, beam_width=beam_width,
        rng_mode=rng_mode, iterations=iterations,
        recover_to_full=True, mode="independent",
    )

    def compatible_frontier():
        # Score all source-prepared samples, not just the locally fastest
        # candidate. A slow early ancestor can win the cumulative route.
        # These sampled rank extensions are NOT simulated skipped-level play.
        frontier: list[tuple[float, list[dict[str, Any]]]] = [(0.0, [])]
        matched: list[int] = []
        for level in levels:
            candidates = measured["independent_level_rankings"].get(str(level), [])
            next_frontier: dict[str, tuple[float, list[dict[str, Any]]]] = {}
            for row in candidates:
                if _talent_ranks(row.get("talents")) is None:
                    continue
                for cost, steps in frontier:
                    if steps and (row["engine_binary_sha256"]
                                  != steps[-1]["engine_binary_sha256"]
                                  or not _no_respec_successor(
                                      steps[-1]["talents"], row["talents"])):
                        continue
                    step = {
                        "level": level, "talents": row["talents"],
                        "apl": row.get("apl"), "gear": row.get("gear"),
                        "pet": row.get("pet"),
                        "native_world_policy": row.get("native_world_policy"),
                        "native_elapsed_seconds": row["native_elapsed_seconds"],
                        "terminal_recovery_seconds": row["terminal_recovery_seconds"],
                        "source_request_sha256": row["source_request_sha256"],
                        "engine_binary_sha256": row["engine_binary_sha256"],
                        "receipt": row["receipt"],
                    }
                    total = cost + float(row["native_elapsed_seconds"])
                    identity = (row["source_request_sha256"],
                                json.dumps(row.get("native_world_policy"),
                                           sort_keys=True))
                    previous = next_frontier.get(identity)
                    if previous is None or total < previous[0]:
                        next_frontier[identity] = (total, [*steps, step])
            if not next_frontier:
                break
            frontier = sorted(next_frontier.values(), key=lambda pair: (
                pair[0], pair[1][-1]["source_request_sha256"]))
            matched.append(level)
        ranked = [
            {"sampled_cumulative_seconds": score, "steps": steps,
             "terminal_source_request_sha256": steps[-1]["source_request_sha256"]}
            for score, steps in frontier[:beam_width]
        ] if matched == list(levels) else []
        return matched, ranked

    matched_levels, ranked = compatible_frontier()
    final_rankings = measured["independent_level_rankings"].get(str(levels[-1]), [])
    ranked_terminal_sources = {
        path["terminal_source_request_sha256"] for path in ranked
    }
    # A late strong family absent from the compatible frontier deserves a
    # bounded backward proposal. A locally fast L20 build is not an excuse to
    # discard a globally superior Demonology/other-tree ancestor.
    missed_late_family = any(
        row["source_request_sha256"] not in ranked_terminal_sources
        for row in final_rankings[:beam_width]
    )
    seeded_levels: list[int] = []
    seeded_attempts = 0
    # The backseed pass is optional; without native hint support it would
    # re-pay unrelated candidates or crash on an unexpected keyword argument.
    # Keep completed real native samples rather than making hints a fake gate.
    if (supports_hints and len(levels) > 1 and (not ranked or missed_late_family)
            and measured["native_candidates_examined"] < budget):
        # Feed exact talents from *paid, source-prepared* later samples to
        # the native producer. It uses Rust options to propose earlier ranks
        # and Rust prepare/ACK to accept/refuse them; no Python talent legality,
        # inferred transition, free respec, or unmeasured elapsed is created.
        for index in range(len(levels) - 2, -1, -1):
            remaining = budget - measured["native_candidates_examined"]
            if remaining <= 0:
                break
            level = levels[index]
            hints: list[dict[str, Any]] = []
            seen: set[str] = set()
            for later in reversed(levels[index + 1:]):
                for row in measured["independent_level_rankings"].get(str(later), [])[
                        :max(beam_width * 2, 6)]:
                    talents = row.get("talents")
                    if _talent_ranks(talents) is None or talents in seen:
                        continue
                    seen.add(talents)
                    hints.append({
                        "talents": talents, "from_level": later,
                        "source_request_sha256": row["source_request_sha256"],
                    })
            if not hints:
                continue
            # Reserve one native attempt for each still-unvisited ancestor;
            # never overspend the top-level budget or replay already-paid
            # equivalent candidates outside the scorer's exact-input cache.
            level_budget = max(1, remaining // (index + 1))
            def seeded_evaluator(**request):
                return evaluate(**request, candidate_hints=hints)
            attempt = optimize(
                level, level, 1, mob_count, level_budget,
                evaluate=seeded_evaluator, beam_width=beam_width,
                rng_mode=rng_mode, iterations=iterations,
                recover_to_full=True, mode="independent",
            )
            consumed = attempt["native_candidates_examined"]
            measured["native_candidates_examined"] += consumed
            seeded_attempts += consumed
            seeded_levels.append(level)
            key = str(level)
            measured["native_attempts_by_level"][key] = (
                measured["native_attempts_by_level"].get(key, 0) + consumed
            )
            measured["rejected_native_attempts"].extend(
                attempt["rejected_native_attempts"]
            )
            original = measured["independent_level_rankings"].setdefault(key, [])
            existing = {row["source_request_sha256"] for row in original}
            selected_engine = measured["native_engine_binary_sha256"]
            for row in attempt["independent_level_rankings"].get(key, []):
                if selected_engine is not None and (
                        row["engine_binary_sha256"] != selected_engine):
                    measured["rejected_native_attempts"].append({
                        "level": level, "candidate_id": row["receipt"].get("candidate_id"),
                        "source_request_sha256": row["source_request_sha256"],
                        "reason": "native engine binary differs within optimization request",
                    })
                    continue
                if row["source_request_sha256"] in existing:
                    continue
                if selected_engine is None:
                    selected_engine = row["engine_binary_sha256"]
                    measured["native_engine_binary_sha256"] = selected_engine
                existing.add(row["source_request_sha256"])
                original.append(row)
            original.sort(key=lambda row: (
                row["native_elapsed_seconds"], row["source_request_sha256"]))
            measured["competing_qualified_paths_by_level"][key] = len(original)
        measured["sampled_levels_completed"] = [
            level for level in levels
            if measured["independent_level_rankings"].get(str(level))
        ]
        matched_levels, ranked = compatible_frontier()

    measured.update({
        "status": ("SAMPLED_COMPATIBLE_PATH_RANKED" if len(ranked) >= 2
                   else "SAMPLED_COMPATIBLE_PATH_PROVISIONAL" if ranked
                   else "NO_COMPLETE_COMPATIBLE_SAMPLED_PATH"),
        "candidate_budget": budget,
        "backward_seeded_native_attempts": seeded_attempts,
        "backward_seeded_levels": seeded_levels,
        "search_mode": "compatible",
        "class": class_name, "tree": talent_tree, "backend": backend,
        "sampled_levels_compatible": matched_levels,
        "ranked_alternatives": ranked,
        "no_respec_within_sampled_path": bool(ranked),
        "intermediate_level_simulations_run": False,
        "intermediate_talent_legality_proven": False,
        "full_10_60_continuous_leveling_route_proven": False,
        "independent_sample_sum_is_route_time": False,
        "scope": "native-prepared sampled allocations with nondecreasing ranks; "
                 "not proof of skipped-level gameplay, XP, travel or training",
    })
    # A search can have many paid candidates while never varying a source
    # request's gear, pet or APL. Expose verified request-axis diversity to
    # downstream consumers without introducing a new acceptance gate or
    # mistaking requested choices for effective trained/native actor ranks.
    paid_axis_breadth: dict[str, dict[str, Any]] = {}
    for level in levels:
        observed = _retained_native_paid_axis_breadth(measured, level)
        paid_count, distinct = (
            observed if observed is not None
            else (0, {axis: 0 for axis in ("talents", "gear", "apl", "pet")})
        )
        paid_axis_breadth[str(level)] = {
            "verified_native_paid_requests": paid_count,
            "distinct_requested_talent_allocations": distinct["talents"],
            "distinct_requested_gear_sets": distinct["gear"],
            "distinct_requested_apls": distinct["apl"],
            "distinct_requested_pet_values": distinct["pet"],
            "uncompared_axes": [
                axis for axis in ("talents", "gear", "apl", "pet")
                if distinct[axis] < 2
            ],
        }
    measured["native_paid_request_axis_breadth_by_level"] = paid_axis_breadth
    return measured



def render_native_paid_level_shortlist(result: Mapping[str, Any]) -> str:
    """Report genuine per-level top 3 with native-source names when available.

    This renders existing paid receipts only. No extra mechanics, legality,
    heuristic best-in-slot selection or world evaluations are introduced.
    """
    import json
    from collections import Counter

    levels = result.get("sampled_levels_requested", [])
    ranked = result.get("independent_level_rankings", {})
    rejected = result.get("rejected_native_attempts", [])
    lines = [
        f"# Native {str(result.get('class') or 'Unspecified class').title()} — best tested level snapshots",
        "",
        "**Scope:** independently native-prepared and fully recovered world "
        "observations; these are NOT a global optimum, compatible equipment "
        "acquisition plan, or continuous XP/travel/training route.",
        f"**Objective:** {result.get('mob_count')} hostile mob(s), "
        f"{result.get('rng_mode')} RNG; movement, 2D lethal ACK and "
        "native paid terminal full HP and mana counted in elapsed time.",
        "",
    ]
    for level in levels:
        receipts = ranked.get(str(level), [])
        refused = [row for row in rejected if row.get("level") == level]
        axes = Counter(row.get("receipt", {}).get("proposal_axis", "unknown")
                       for row in receipts)
        attempted_axes = axes + Counter(row.get("proposal_axis") or "unknown"
                                        for row in refused)
        prepared_axes = axes + Counter(row.get("proposal_axis") or "unknown"
                                       for row in refused
                                       if row.get("native_prepared") is True)
        lines += [f"## Level {level}", "",
                  f"**Native paid qualified:** {len(receipts)}; "
                  f"**refused/unscored:** {len(refused)}; "
                  f"**attempts:** {result.get('native_attempts_by_level', {}).get(str(level), 0)}.",
                  "**Observed axis counts, proposed/prepared/paid:** "
                  + (", ".join(f"{axis}={attempted_axes[axis]}/"
                               f"{prepared_axes[axis]}/{axes[axis]}"
                               for axis in sorted(attempted_axes))
                     if attempted_axes else "none"),
                  ""]
        # Axis labels count *attempts*, not actual different successful values.
        # Reuse the sampled-guide's receipt-verified paid-breadth calculation:
        # no Python equipment/pet/spell legality rules or new acceptance gate.
        breadth = _retained_native_paid_axis_breadth(result, level)
        if breadth is None:
            lines.append("**Distinct verified native-paid choices:** none (no paid comparison).")
        else:
            paid_count, distinct = breadth
            lines.append(
                f"**Distinct verified native-paid choices ({paid_count} receipts):** "
                f"gear sets={distinct['gear']}; pet values={distinct['pet']}; "
                f"APLs={distinct['apl']}; talent allocations={distinct['talents']}."
            )
            single = [axis for axis in ("gear", "pet", "apl", "talents")
                      if distinct[axis] == 1]
            if single:
                lines.append(
                    "**One observed paid value, not optimized:** "
                    + ", ".join(single) + "."
                )
        lines.append("")
        if not receipts:
            lines += ["No paid, fully recovered candidate at this level.", ""]
        for rank, row in enumerate(receipts[:3], 1):
            receipt = row.get("receipt", {})
            labels = receipt.get("native_named_build") or {}
            lines += [
                f"### #{rank} — {row['native_elapsed_seconds']:.3f} s",
                f"- Recovery: {row['terminal_recovery_seconds']:.3f} s "
                "(already included in elapsed)",
                f"- World pull/rest policy (native measured): "
                f"{json.dumps(receipt.get('native_world_policy') or {'pull_mode': 'serial', 'rest_when_health_below': 1.0, 'rest_when_mana_below': 1.0}, sort_keys=True)}",
                f"- Summon: {row.get('pet') or 'NoSummon / unspecified'} "
                f"(axis {receipt.get('proposal_axis', 'unknown')})",
                f"- Talents: {row.get('talents')} — "
                + (", ".join(f"{x.get('name') or 'native slot'} "
                             f"{x.get('rank')}/{x.get('max_rank')}"
                             for x in labels.get("talent_names", [])) or
                   "names unavailable in native options"),
                "- Equipped native items:",
            ]
            items = labels.get("equipped_item_names_ids", [])
            lines += [
                f"  - Slot {item.get('position')}: "
                f"{item.get('name') or 'source name unavailable'} "
                f"(ID {item.get('item_id')})"
                for item in items if item.get("item_id") not in (None, 0)
            ] or ["  - no named/equipped items in native request"]
            lines.append("- Ordered APL (source-request actions; native prepare paid):")
            lines += [
                f"  - {spell.get('priority')}. "
                f"{spell.get('name') or 'source name unavailable'} "
                f"({spell.get('rank') or 'rank unverified'}, "
                f"spell ID {spell.get('spell_id')}), "
                f"condition {json.dumps(spell.get('condition'), sort_keys=True)}"
                for spell in labels.get("ordered_apl_spells", [])
            ] or ["  - no named source APL"]
            lines += [
                f"- Source protobuf SHA256: {row['source_request_sha256']}",
                f"- Exact engine binary SHA256: {row['engine_binary_sha256']}",
                f"- Original paid receipt: {receipt.get('native_raw_receipt_file')}",
                "",
            ]
        for attempt in refused[:8]:
            lines.append(f"- Native refusal ({attempt.get('proposal_axis') or 'unknown'}; "
                         f"prepared={attempt.get('native_prepared')}; "
                         f"code={attempt.get('native_refusal_code')}): "
                         f"{attempt.get('native_refusal') or attempt.get('reason')}")
        if refused:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n\n"


def render_sampled_build_guide(result: Mapping[str, Any]) -> str:
    """Explain a measured sampled path without inventing continuous leveling.

    This presents already-scored native receipts: no candidate selection,
    game-rule validation, extrapolation or paid replay is performed.
    """
    import json

    ranked = result.get("ranked_alternatives")
    if not isinstance(ranked, list) or not ranked:
        raise ValueError("cannot publish a guide without a measured compatible path")
    best = ranked[0]
    steps = best["steps"]
    levels = result["sampled_levels_requested"]
    if [step["level"] for step in steps] != levels:
        raise ValueError("cannot publish an incomplete sampled path as a full guide")
    if (result.get("status") not in (
            "SAMPLED_COMPATIBLE_PATH_RANKED",
            "SAMPLED_COMPATIBLE_PATH_PROVISIONAL",
        ) or result.get("sampled_levels_compatible") != levels):
        raise ValueError("cannot publish a guide without completed compatible native samples")
    # These original paid receipts are the reason the guide can call the
    # displayed numbers measured.  Reject edited/mixed JSON rather than
    # silently publishing a plausible-looking, uncharged build path.
    for path in ranked:
        path_steps = path.get("steps")
        if not isinstance(path_steps, list) or [
            step.get("level") for step in path_steps
        ] != levels:
            raise ValueError("cannot publish an incomplete sampled alternative")
        measured_total = 0.0
        for step in path_steps:
            receipt = step.get("receipt")
            if not isinstance(receipt, dict):
                raise ValueError("cannot publish a guide without original native paid receipts")
            refusal = _receipt_error(
                receipt, level=step["level"], parent=None,
                mob_count=result["mob_count"], rng_mode=result["rng_mode"],
                iterations=result["iterations"],
            )
            if refusal is not None:
                raise ValueError(f"cannot publish unpaid or refused native receipt: {refusal}")
            for field in ("source_request_sha256", "engine_binary_sha256",
                          "talents", "gear", "apl", "pet"):
                if receipt.get(field) != step.get(field):
                    raise ValueError(f"native guide step/receipt disagreement: {field}")
            if (not math.isclose(receipt["elapsed_seconds"],
                                 step["native_elapsed_seconds"], abs_tol=1e-6)
                    or not math.isclose(receipt["terminal_recovery_seconds"],
                                        step["terminal_recovery_seconds"], abs_tol=1e-6)):
                raise ValueError("native guide elapsed/recovery disagrees with paid receipt")
            measured_total += receipt["elapsed_seconds"]
        if not math.isclose(measured_total, path["sampled_cumulative_seconds"],
                            rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("native guide cumulative score disagrees with paid receipts")
    title = str(result.get("class", "character")).capitalize()
    score_label = ("Best compatible sampled score" if len(ranked) > 1
                   else "Only measured compatible sampled score")
    lines = [
        f"# {title} — source-native sampled build guide",
        "",
        f"**Measured scope:** {len(steps)} sampled level(s), "
        f"L{levels[0]}–L{levels[-1]}; {result['mob_count']} hostile mob(s) "
        f"per level; {result['rng_mode']} RNG, {result['iterations']} iteration(s).",
        "",
        "**Not a continuous leveling route.** Scores include actual native "
        "combat, movement and paid terminal recovery to full HP and mana "
        "at each sample. XP, travel between levels, training, acquisition "
        "and intervening gameplay are not measured. Talent rank deltas below "
        "are comparisons of native-prepared snapshots, not prescribed "
        "intermediate training decisions.",
        "",
        "**Search scope:** Best means fastest among the observed compatible "
        "native-paid candidates, not a proven joint gear × talents × APL × "
        "pet optimum. A single paid value for an axis means no comparison "
        "on that axis.",
        "",
        ("**Competition:** Only one compatible native-paid path retained; "
         "this is a provisional measured baseline, not an optimized winner."
         if len(ranked) == 1 else
         f"**Competition:** {len(ranked)} compatible measured paths retained."),
        "",
        f"**{score_label}:** "
        f"{best['sampled_cumulative_seconds']:.3f} s "
        f"(among {len(ranked)} retained compatible path(s)).",
        "",
        "## Source-native level decisions",
    ]
    previous = None
    for step in steps:
        level = step["level"]
        lines += [
            "",
            f"### Level {level}",
            f"- Native talents: {step['talents']}",
            f"- Measured elapsed: {step['native_elapsed_seconds']:.3f} s "
            f"(terminal recovery: {step['terminal_recovery_seconds']:.3f} s)",
        ]
        breadth = _retained_native_paid_axis_breadth(result, level)
        if breadth is not None:
            paid_count, counts = breadth
            lines.append(
                "- Native-paid candidate breadth: "
                f"{paid_count}; talent allocations {counts['talents']}, "
                f"gear sets {counts['gear']}, APLs {counts['apl']}, "
                f"pet values {counts['pet']}."
            )
            fixed = [label for field, label in (
                ("talents", "talents"), ("gear", "gear"),
                ("apl", "APL"), ("pet", "pet")
            ) if counts[field] == 1]
            if fixed:
                lines.append(
                    "- Limited axes (one paid value): "
                    + ", ".join(fixed)
                    + ". No joint-axis optimum is established."
                )
        # A limited paid axis can mean it was never tried or that Rust
        # refused the actual proposed alternative. Disclose that distinction
        # without ever counting refusals as native-paid measurements.
        refused = result.get("rejected_native_attempts")
        refused_by_axis: dict[tuple[str, str | None], int] = {}
        if isinstance(refused, list):
            for rejected in refused:
                if (not isinstance(rejected, Mapping)
                        or rejected.get("level") != level
                        or rejected.get("native_status")
                        != "NATIVE_API_CANDIDATE_REFUSED"):
                    continue
                axis = rejected.get("proposal_axis")
                if not isinstance(axis, str) or not axis:
                    continue
                code = rejected.get("native_refusal_code")
                code = code if isinstance(code, str) and code else None
                key = (axis, code)
                refused_by_axis[key] = refused_by_axis.get(key, 0) + 1
        if refused_by_axis:
            lines.append(
                "- Refused native proposals (not paid or ranked): "
                + ", ".join(
                    f"{axis}: {count} ({code or 'no structured code'})"
                    for (axis, code), count in sorted(
                        refused_by_axis.items(),
                        key=lambda item: (item[0][0], item[0][1] or ""),
                    )
                )
                + "."
            )
        before = _talent_ranks(previous["talents"]) if previous else None
        after = _talent_ranks(step["talents"])
        if before is not None and after is not None:
            deltas = [
                f"tree {tree_index}, slot {slot+1}: +{new-old}"
                for tree_index, (old_tree, new_tree) in enumerate(
                    zip(before, after), 1)
                for slot in range(max(len(old_tree), len(new_tree)))
                for old, new in [(
                    old_tree[slot] if slot < len(old_tree) else 0,
                    new_tree[slot] if slot < len(new_tree) else 0)]
                if new > old
            ]
            lines.append("- Ranks added since previous sample: "
                         + (", ".join(deltas) if deltas else "none"))
        for field, label in (("gear", "Native item IDs"),
                             ("pet", "Native summon"),
                             ("apl", "Native APL")):
            if previous is None or step.get(field) != previous.get(field):
                lines.append(f"- {label}: "
                             + json.dumps(step.get(field), sort_keys=True,
                                          separators=(",", ":")))
        lines.append("- Source request SHA256: "
                     + str(step["source_request_sha256"]))
        previous = step
    if len(ranked) > 1:
        lines += ["", "## Measured alternative sampled scores"]
        lines += [
            f"- Alternative {n}: {path['sampled_cumulative_seconds']:.3f} s"
            for n, path in enumerate(ranked[1:], 2)
        ]
    return "\n".join(lines) + "\n"


def optimize(
    start_level: int, end_level: int, level_stride: int, mob_count: int,
    budget: int, *,
    evaluate: Callable[..., Sequence[Mapping[str, Any]]],
    beam_width: int = 3, rng_mode: str = "balanced", iterations: int = 1,
    recover_to_full: bool = True, mode: str = "independent",
    class_name: str = "unspecified", talent_tree: str = "unconstrained",
    backend: str = "native",
) -> dict[str, Any]:
    """Rank real native candidates in a continuing path or independent samples.

    Independent samples use parent=None at *every* level and never claim
    a continuous route or add unrelated sample costs. Continuing mode retains
    the native source-linked ancestry requirement.

    evaluate(level=, parent=, mob_count=, budget=, rng_mode=, iterations=,
             recover_to_full=) must return at most budget distinct native
    attempts. parent is the exact previous native receipt, or None at start.
    Every returned attempt, including refusals, consumes the search budget.
    The evaluator owns native get_options/proposals, preparation, execution,
    native terminal restoration and exact-compatible paid receipt reuse.

    No Python talent, item, spell or resource mechanics are implemented here.
    """
    if mode == "compatible":
        if (recover_to_full is not True or type(beam_width) is not int
                or beam_width < 1 or type(budget) is not int or budget < 1
                or type(mob_count) is not int or not 1 <= mob_count <= 100
                or type(iterations) is not int or iterations < 1):
            raise ValueError("invalid compatible sampled optimizer configuration")
        return _optimize_compatible_samples(
            start_level, end_level, level_stride, mob_count, budget,
            evaluate=evaluate, beam_width=beam_width, rng_mode=rng_mode,
            iterations=iterations, class_name=class_name,
            talent_tree=talent_tree, backend=backend,
        )
    levels = sampled_levels(start_level, end_level, level_stride)
    if (type(mob_count) is not int or mob_count < 1
            or type(budget) is not int or budget < 1
            or type(beam_width) is not int or beam_width < 1
            or type(iterations) is not int or iterations < 1
            or not isinstance(rng_mode, str) or not rng_mode
            or recover_to_full is not True or mode not in ("continuing", "independent")):
        raise ValueError("mob_count/budget/beam_width/RNG/terminal recovery invalid")

    # State: cumulative observed time, latest native source, sampled path.
    frontier: list[tuple[float, Mapping[str, Any] | None, list[dict[str, Any]]]] = [
        (0.0, None, [])
    ]
    examined = 0
    rejected: list[dict[str, Any]] = []
    covered: list[int] = []
    competing: dict[str, int] = {}
    last_frontier: list[tuple[float, Mapping[str, Any] | None, list[dict[str, Any]]]] = []
    native_attempts_by_level: dict[str, int] = {}
    # One optimizer request compares costs only under a single exact native
    # engine executable, including the independent sampled-level mode. A
    # different engine can produce a legitimate receipt but not a comparable
    # winner against the first source-native scorer identity.
    selected_engine_sha: str | None = None
    independent_rankings: dict[str, list[dict[str, Any]]] = {}
    for level_index, level in enumerate(levels):
        if mode == "independent":
            # Anchor scores are comparable only within their own level.
            # Never feed a scored L20 root to the L30 anchor as a legal parent.
            frontier = [(0.0, None, [])]
        # Budget the entire request, not just the first sample. A scorer may
        # spend up to its allotted candidate count but cannot starve every
        # later requested level by using the whole remaining global budget.
        levels_left = len(levels) - level_index
        level_budget = max(1, (budget - examined) // levels_left)
        level_attempts = 0
        next_paths: dict[tuple[str, str], tuple[float, Mapping[str, Any], list[dict[str, Any]]]] = {}
        at_level = 0
        for parent_index, (base_cost, parent, history) in enumerate(frontier):
            remaining = min(budget - examined, level_budget - level_attempts)
            if remaining <= 0:
                break
            parent_count_left = len(frontier) - parent_index
            parent_budget = max(1, remaining // parent_count_left)
            evaluator_request = dict(
                level=level, parent=parent, mob_count=mob_count, budget=parent_budget,
                rng_mode=rng_mode, iterations=iterations, recover_to_full=True,
            )
            if mode == "independent":
                evaluator_request["search_mode"] = "independent"
            receipts = evaluate(**evaluator_request)
            if not isinstance(receipts, Sequence) or isinstance(receipts, (str, bytes)):
                raise TypeError("native evaluator must return a sequence of receipts")
            if len(receipts) > parent_budget:
                raise ValueError("native evaluator exceeded candidate budget")
            for row in receipts:
                examined += 1
                level_attempts += 1
                at_level += 1
                if not isinstance(row, Mapping):
                    rejected.append({"level": level, "reason": "non-mapping native receipt"})
                    continue
                error = _receipt_error(
                    row, level=level, parent=parent, mob_count=mob_count,
                    rng_mode=rng_mode, iterations=iterations,
                )
                if error is None and selected_engine_sha is not None:
                    if row["engine_binary_sha256"] != selected_engine_sha:
                        error = "native engine binary differs within optimization request"
                if error:
                    rejected.append({
                        "level": level, "source_request_sha256": row.get("source_request_sha256"),
                        "candidate_id": row.get("candidate_id"),
                        "reason": error, "native_status": row.get("status"),
                        "native_refusal": row.get("native_refusal"),
                        "native_refusal_code": row.get("native_refusal_code"),
                        "native_prepared": row.get("native_prepared"),
                        "proposal_axis": row.get("proposal_axis"),
                        "native_world_policy": row.get("native_world_policy"),
                    })
                    continue
                if selected_engine_sha is None:
                    selected_engine_sha = row["engine_binary_sha256"]
                cost = base_cost + float(row["elapsed_seconds"])
                step = {
                    "level": level, "source_request_sha256": row["source_request_sha256"],
                    "engine_binary_sha256": row["engine_binary_sha256"],
                    "native_elapsed_seconds": float(row["elapsed_seconds"]),
                    "terminal_recovery_seconds": float(row["terminal_recovery_seconds"]),
                    "sampled_cumulative_seconds": cost,
                    "native_parent_source_sha256": row.get("native_parent_source_sha256"),
                    "talents": row.get("talents"), "pet": row.get("pet"),
                    "gear": row.get("gear"), "apl": row.get("apl"),
                    "native_world_policy": row.get("native_world_policy"),
                    "receipt": dict(row),
                }
                key = (row["engine_binary_sha256"],
                       row["source_request_sha256"] + ":" +
                       json.dumps(row.get("native_world_policy"), sort_keys=True))
                old = next_paths.get(key)
                if old is None or cost < old[0]:
                    next_paths[key] = (cost, row, [*history, step])
        native_attempts_by_level[str(level)] = level_attempts
        competing[str(level)] = len(next_paths)
        if not next_paths:
            if mode == "independent":
                independent_rankings[str(level)] = []
                continue
            break
        covered.append(level)
        last_frontier = sorted(
            next_paths.values(), key=lambda p: (p[0], p[1]["source_request_sha256"])
        )
        if mode == "independent":
            independent_rankings[str(level)] = [
                {"source_request_sha256": row["source_request_sha256"],
                 "engine_binary_sha256": row["engine_binary_sha256"],
                 "native_elapsed_seconds": cost,
                 "terminal_recovery_seconds": row["terminal_recovery_seconds"],
                 "talents": row.get("talents"), "pet": row.get("pet"),
                 "gear": row.get("gear"), "apl": row.get("apl"),
                 "native_world_policy": row.get("native_world_policy"),
                 "receipt": dict(row), "continuity_unverified": True}
                for cost, row, _ in last_frontier
            ]
        else:
            frontier = last_frontier[:beam_width]
        # A single remaining-budget shortfall cannot be disguised as a result
        # for the unvisited samples. Preserve the completed prefix instead.
        if examined >= budget:
            break

    ranked = ([
        {"sampled_cumulative_seconds": cost, "steps": steps,
         "source_request_sha256": source["source_request_sha256"]}
        for cost, source, steps in last_frontier
    ] if mode == "continuing" else [])
    complete = covered == list(levels)
    independently_competitive = (complete and all(
        len(independent_rankings.get(str(level), [])) >= 2 for level in levels
    ))
    return {
        "status": (("INDEPENDENT_NATIVE_ANCHORS_RANKED" if independently_competitive
                    else "INDEPENDENT_NATIVE_ANCHORS_PARTIAL" if covered
                    else "NO_COMPARABLE_NATIVE_ANCHORS") if mode == "independent"
                   else "SAMPLED_NATIVE_PATH_RANKED" if complete and len(ranked) >= 2
                   else "SAMPLED_NATIVE_PREFIX_ONLY" if covered
                   else "NO_COMPARABLE_NATIVE_PATH"),
        "search_mode": mode,
        "class": class_name,
        "continuity_unverified": mode == "independent",
        "independent_level_rankings": independent_rankings,
        "independent_sample_winner_elapsed_sum_seconds": (
            sum(independent_rankings[str(level)][0]["native_elapsed_seconds"]
                for level in levels)
            if complete and mode == "independent" else None),
        "independent_sample_sum_is_route_time": False,
        "sampled_levels_requested": list(levels),
        "sampled_levels_completed": covered,
        "mob_count": mob_count, "rng_mode": rng_mode, "iterations": iterations,
        "recover_to_full": True, "candidate_budget": budget,
        "native_candidates_examined": examined, "beam_width": beam_width,
        "native_engine_binary_sha256": selected_engine_sha,
        "native_attempts_by_level": native_attempts_by_level,
        "competing_qualified_paths_by_level": competing,
        "ranked_alternatives": ranked,
        "rejected_native_attempts": rejected,
        "full_10_60_continuous_leveling_route_proven": False,
        "scope": "sampled native combat+movement+charged terminal recovery only; not XP/travel/training/acquisition",
    }



def guide_main(argv: list[str] | None = None) -> int:
    """Render an already measured optimizer result without opening Rust/payments."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(prog="native-guide",
        description="Publish a prior native-paid sampled result without replay")
    parser.add_argument("--in", dest="source", type=Path, required=True,
                        help="Saved --out JSON from the existing optimizer")
    parser.add_argument("--out", dest="output", type=Path, required=True,
                        help="Human-readable Markdown destination")
    args = parser.parse_args(argv)
    if args.source.resolve() == args.output.resolve():
        parser.error("--out cannot overwrite the original native receipt result")
    result = json.loads(args.source.read_text())
    guide = render_sampled_build_guide(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(guide)
    print(f"Published existing sampled build decisions to {args.output}")
    return 0


def main(argv: list[str] | None = None, *, evaluate=None) -> int:
    """Generic optimizer CLI. Class and search density are runtime settings.

    Class-specific native evaluators are selected by a plugin registry.
    The optimizer, paid receipt scorer and HTML publisher are shared.
    """
    import argparse
    import json
    import sys
    from pathlib import Path

    ap = argparse.ArgumentParser(prog="optimize",
        description="Source-native sampled compatible build optimization")
    ap.add_argument("--class", dest="class_name", required=True)
    ap.add_argument("--tree", "--talent-tree", default="unconstrained")
    ap.add_argument("--start-level", type=int, required=True)
    ap.add_argument("--end-level", type=int, required=True)
    ap.add_argument("--level-stride", type=int, default=1)
    ap.add_argument("--n-mobs", "--mob-count", type=int, default=2)
    ap.add_argument("--rng", "--rng-backend", default="balanced")
    ap.add_argument("--backend", default="rust")
    ap.add_argument("--recover-at-end", "--recover-to-full",
                    choices=("true",), default="true")
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--budget", type=int, default=100)
    ap.add_argument("--beam-width", type=int, default=3)
    ap.add_argument("--native-binary", type=Path,
                    default=Path("integrations/mythicsim-rust/target/release/forever-engine"))
    ap.add_argument("--source", type=Path,
                    help="Initial class-native source request; defaults to the "
                         "selected class adapter fixture when available")
    ap.add_argument("--target-hp", type=float,
                    help="Optional fixed enemy HP override; default uses the "
                         "ordinary-mob scenario HP at each sampled level")
    ap.add_argument("--compare-world-rest-30", action="store_true",
                    help="Compare native serial full-rest baseline against "
                         "HP<30%% OR mana<30%% rest-until-full; refuse unless "
                         "Rust explicitly acknowledges applied thresholds")
    ap.add_argument("--compare-world-rolling-50", action="store_true",
                    help="Compare a serial native world against a source-ACKed "
                         "two-live-target policy switching at 50%% current "
                         "target HP; refuse until real overlap is observed")
    ap.add_argument("--probe-native-continuity", action="store_true",
                    help="Probe one fresh paid native first-world and same-session "
                         "XP/level transition; never reuse sampled-world cache")
    ap.add_argument("--out", type=Path, help="Optional machine-readable result path")
    ap.add_argument("--guide-out", type=Path,
                    help="Optional player-facing guide for native-paid sampled decisions")
    ap.add_argument("--shortlist-out", type=Path,
                    help="Human-readable per-level top-three exact paid native candidates")
    ap.add_argument("--html-out-dir", type=Path,
                    help="Output folder for offline standalone BiS-style native-paid HTML pages; "
                         "default is <JSON output parent>/html")
    args = ap.parse_args(argv)
    from .native_class_adapters import normalize_class_name
    try:
        cls = normalize_class_name(args.class_name)
    except ValueError as exc:
        ap.error(str(exc))
    if args.tree != "unconstrained":
        ap.error("the current native adapter supports --tree unconstrained only")
    if args.backend != "rust" or args.rng != "balanced" or args.iterations != 1:
        ap.error("the current native adapter supports rust/balanced/one iteration")
    output = args.out or Path("runs") / (
        (f"native_continuity_{cls}_L{args.start_level}-{args.end_level}"
         f"_mobs{args.n_mobs}.json")
        if args.probe_native_continuity else
        (f"optimize_{cls}_L{args.start_level}-{args.end_level}"
         f"_stride{args.level_stride}_mobs{args.n_mobs}.json")
    )
    if args.guide_out and args.guide_out.resolve() == output.resolve():
        ap.error("--guide-out must differ from --out")
    if args.shortlist_out and (args.shortlist_out.resolve() == output.resolve()
                               or (args.guide_out and args.shortlist_out.resolve()
                                   == args.guide_out.resolve())):
        ap.error("--shortlist-out must differ from JSON and guide outputs")
    if args.compare_world_rest_30 and (
            args.start_level != args.end_level or args.budget < 2):
        ap.error("--compare-world-rest-30 requires one level and budget >= 2")
    if args.compare_world_rolling_50 and (
            args.compare_world_rest_30 or args.probe_native_continuity
            or args.start_level != args.end_level or args.budget < 2
            or args.n_mobs != 2):
        ap.error("--compare-world-rolling-50 needs one level, two hostile "
                 "targets, budget >= 2 and no competing probe")
    if args.probe_native_continuity:
        if args.end_level != args.start_level + 1:
            ap.error("--probe-native-continuity needs exactly one level transition")
        if args.guide_out:
            ap.error("a retained-actor probe cannot publish a sampled build guide")
        if args.shortlist_out:
            ap.error("a retained-actor probe cannot publish a native shortlist")
        if args.n_mobs < 2:
            ap.error("native world bridge requires at least two hostile targets")
    if evaluate is None:
        from .native_class_adapters import (
            NativeAdapterUnavailable, resolve_native_class_adapter,
        )
        try:
            adapter = resolve_native_class_adapter(cls)
        except NativeAdapterUnavailable as exc:
            ap.error(str(exc))
        source = args.source or adapter.default_source
        if source is None:
            ap.error(f"native {cls} adapter needs an explicit --source request")
        if not args.native_binary.is_file() or not source.is_file():
            ap.error("native engine and selected class source request must exist")
        # Every class adapter supplies a source-native evaluator with this
        # protocol; no Warcraft legality or search algorithm is duplicated.
        native = adapter.evaluator_factory(
            args.native_binary, source, Path("runs/native-api-paid-cache"),
            target_hp=args.target_hp,
            **({"compare_world_rest_30": True}
               if args.compare_world_rest_30 else {}),
            **({"compare_world_rolling_50": True}
               if args.compare_world_rolling_50 else {}),
        )
        try:
            if args.probe_native_continuity:
                result = native.probe_native_level_transition(
                    from_level=args.start_level, to_level=args.end_level,
                    mob_count=args.n_mobs, candidate_budget=args.budget)
            else:
                result = optimize(
                    args.start_level, args.end_level, args.level_stride,
                    args.n_mobs, args.budget, evaluate=native,
                    beam_width=args.beam_width, rng_mode=args.rng,
                    iterations=args.iterations, mode="compatible",
                    class_name=cls, talent_tree=args.tree, backend=args.backend,
                )
        finally:
            native.close()
    else:
        if args.probe_native_continuity:
            if not callable(getattr(evaluate, "probe_native_level_transition", None)):
                raise ValueError("NATIVE_CONTINUITY_PROBE_NEEDS_SESSION_EVALUATOR")
            result = evaluate.probe_native_level_transition(
                from_level=args.start_level, to_level=args.end_level,
                mob_count=args.n_mobs, candidate_budget=args.budget)
        else:
            result = optimize(
                args.start_level, args.end_level, args.level_stride,
                args.n_mobs, args.budget, evaluate=evaluate,
                beam_width=args.beam_width, rng_mode=args.rng,
                iterations=args.iterations, mode="compatible",
                class_name=cls, talent_tree=args.tree, backend=args.backend,
            )
    if args.compare_world_rest_30:
        result["world_rest_head_to_head"] = measured_world_rest_head_to_head(
            result, level=args.start_level)
    if args.compare_world_rolling_50:
        result["world_rolling_head_to_head"] = measured_world_rolling_head_to_head(
            result, level=args.start_level)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    # Publish only verified native-paid candidates. The offline HTML generator
    # refuses mocked/provisional/unpaid rows and never performs new world work.
    if not args.probe_native_continuity:
        from tools.wf_native_paid_html import write_native_paid_html_reports
        html_dir = args.html_out_dir or (output.parent / "html")
        write_native_paid_html_reports(result, html_dir)
    if args.probe_native_continuity:
        print(f"Native same-session L{args.start_level}->L{args.end_level} "
              f"continuity: {result['status']}; "
              f"continuous_leveling_proven={result['continuous_leveling_proven']}")
        return 0 if result["status"] == "NATIVE_RETAINED_LEVEL_ADVANCED" else 2
    if args.guide_out and result["ranked_alternatives"]:
        args.guide_out.parent.mkdir(parents=True, exist_ok=True)
        args.guide_out.write_text(render_sampled_build_guide(result))
    if args.shortlist_out:
        args.shortlist_out.parent.mkdir(parents=True, exist_ok=True)
        args.shortlist_out.write_text(render_native_paid_level_shortlist(result))
    if args.compare_world_rest_30:
        comparison = result["world_rest_head_to_head"]
        print("Native World-APL rest-policy head-to-head: "
              + comparison["status"])
        if comparison["status"] != "MEASURED_NATIVE_REST_HEAD_TO_HEAD":
            print("No native head-to-head winner: inspect paid refusals in --out.")
            return 2
        print("Policy winner: " + comparison["winner"]
              + "; full minus 30%-rest charged seconds: "
              + f"{comparison['full_minus_thirty_elapsed_seconds']:.3f}")
    if args.compare_world_rolling_50:
        comparison = result["world_rolling_head_to_head"]
        print("Native rolling World-APL head-to-head: " + comparison["status"])
        if comparison["status"] != "MEASURED_NATIVE_ROLLING_WORLD_APL_HEAD_TO_HEAD":
            print("No two-live-target winner: inspect native refusals in --out.")
            return 2
        print("Rolling policy winner: " + comparison["winner"])
    if result["ranked_alternatives"]:
        best = result["ranked_alternatives"][0]
        print(f"{cls}: sampled compatible build path, "
              f"{best['sampled_cumulative_seconds']:.3f}s recovered sample score")
        for step in best["steps"]:
            print(f"L{step['level']} talents={step['talents']} "
                  f"gear={json.dumps(step['gear'], sort_keys=True)} "
                  f"apl={json.dumps(step['apl'], sort_keys=True)} "
                  f"pet={step['pet']} "
                  f"recovered_seconds={step['native_elapsed_seconds']:.3f}")
        print("Sparse sample only; skipped levels have no simulated fights.")
    else:
        print(f"No fully compatible measured sampled path: {result['status']}")
    return 0 if result["ranked_alternatives"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
