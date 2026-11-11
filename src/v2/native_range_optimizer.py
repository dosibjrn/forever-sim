"""One-request source-native class/level-range performance optimizer.

Forever owns the search frontier and objective aggregation, not Warcraft rules.
The supplied evaluator must call the pinned Rust source/native execution path and
return its *observed* receipt for each proposal.  Missing full-resource recovery
or unproved cross-level ancestry is never upgraded to a comparable score.

Sparse checkpoints are samples of an objective, NOT a complete leveling route.
"""
from __future__ import annotations

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
    if parent is not None:
        if row.get("engine_binary_sha256") != parent["engine_binary_sha256"]:
            return "cross-engine path is not comparable"
        if (row.get("native_parent_source_sha256") != parent["source_request_sha256"]
                or row.get("native_continuity_ack") is not True
                or row.get("native_continuity_from_level") != parent["level"]):
            return "native continuing talent/actor edge unproved"
    return None



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
                        "native_elapsed_seconds": row["native_elapsed_seconds"],
                        "terminal_recovery_seconds": row["terminal_recovery_seconds"],
                        "source_request_sha256": row["source_request_sha256"],
                        "engine_binary_sha256": row["engine_binary_sha256"],
                        "receipt": row["receipt"],
                    }
                    total = cost + float(row["native_elapsed_seconds"])
                    identity = row["source_request_sha256"]
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
        "# Native Warlock — best tested level snapshots",
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
        if not receipts:
            lines += ["No paid, fully recovered candidate at this level.", ""]
        for rank, row in enumerate(receipts[:3], 1):
            receipt = row.get("receipt", {})
            labels = receipt.get("native_named_build") or {}
            lines += [
                f"### #{rank} — {row['native_elapsed_seconds']:.3f} s",
                f"- Recovery: {row['terminal_recovery_seconds']:.3f} s "
                "(already included in elapsed)",
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
    if (result.get("status") != "SAMPLED_COMPATIBLE_PATH_RANKED"
            or result.get("sampled_levels_compatible") != levels):
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
        f"**Best compatible sampled score:** "
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
    class_name: str = "warlock", talent_tree: str = "unconstrained",
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
                    "receipt": dict(row),
                }
                key = (row["engine_binary_sha256"], row["source_request_sha256"])
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

    Native Warlock is the first available adapter, not a different optimizer.
    Its source fixture is only an initial request, never a hardcoded route.
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
                    default=Path("fixtures/warlock-l20-native-paid-30s.request.json"),
                    help="Initial native source request (not a route or fixed winner)")
    ap.add_argument("--target-hp", type=float,
                    help="Optional fixed enemy HP override; default uses the "
                         "ordinary-mob scenario HP at each sampled level")
    ap.add_argument("--probe-native-continuity", action="store_true",
                    help="Probe one fresh paid native first-world and same-session "
                         "XP/level transition; never reuse sampled-world cache")
    ap.add_argument("--out", type=Path, help="Optional machine-readable result path")
    ap.add_argument("--guide-out", type=Path,
                    help="Optional player-facing guide for native-paid sampled decisions")
    ap.add_argument("--shortlist-out", type=Path,
                    help="Human-readable per-level top-three exact paid native candidates")
    args = ap.parse_args(argv)
    cls = args.class_name.lower()
    if cls != "warlock":
        ap.error(f"no source-native adapter registered yet for class {cls!r}")
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
        if not args.native_binary.is_file() or not args.source.is_file():
            ap.error("native engine and initial source request must exist")
        from tools.wf_warlock_native_persistent_optimizer import PersistentNativeEvaluator
        # One Rust session and one stable paid cache survive every sampled
        # level and reverse-seeded pass; no per-candidate JSON/prepared shuttle.
        native = PersistentNativeEvaluator(
            args.native_binary, args.source, Path("runs/native-api-paid-cache"),
            target_hp=args.target_hp,
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
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
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
