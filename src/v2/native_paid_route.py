"""Connect *already executed* Warlock native paid receipts in gsim path DP.

This is a source-request/receipt routing adapter. Rust, not this module, is
authoritative for build legality and combat. Connected paid levels are not a
continuous XP, travel, training or full 10-60 journey simulation.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .class_model import ClassModel
from .path_dp import LevelNode, solve_path_dp, _is_paid_native_level_node


class NativeTalentStringModel(ClassModel):
    """Opaque source talentString identity/difference, not talent legality."""

    name = "native-warlock-talents"

    def evaluate(self, ctx):
        raise RuntimeError("native paid results, not Python evaluation, score this frontier")

    def build_key(self, build):
        return str(build)

    def build_points(self, build):
        return sum(int(c) for tree in str(build).split("-") for c in tree)

    def legal_one_point_transition(self, parent, child):
        # Both endpoints were *already* native-prepared and paid. Detect only
        # whether serialized allocations have one more point; no talent
        # prerequisites, ranks or class rules are evaluated here.
        a, b = str(parent).split("-"), str(child).split("-")
        if len(a) != 3 or len(b) != 3:
            return None
        differences = []
        for tree_index, (old, new) in enumerate(zip(a, b)):
            for index in range(max(len(old), len(new))):
                before = int(old[index]) if index < len(old) else 0
                after = int(new[index]) if index < len(new) else 0
                if after != before:
                    differences.append((tree_index, index, after - before))
        if len(differences) == 1 and differences[0][2] == 1:
            ti, index, _ = differences[0]
            return f"native_source_tree_{ti}_slot_{index}"
        return None


def connected_native_paid_frontier(observations: Sequence[Mapping[str, Any]],
                                   *, first_level: int = 20) -> dict[str, Any]:
    """Find an observed no-respec adjacent talent path from paid chain rows.

    This is a feasibility/lineage trace only: no XP, combat, travel or
    level-up time is inferred. Refused/prepared-only rows cannot be nodes.
    """
    candidates: dict[int, list[LevelNode]] = defaultdict(list)
    for row in observations:
        if not isinstance(row, Mapping):
            continue
        level = row.get("level")
        actor = row.get("native_actor")
        talents = row.get("talents")
        if (type(level) is not int or level < first_level
                or not isinstance(actor, Mapping)
                or actor.get("class") != "ClassWarlock"
                or actor.get("level") != level
                or not isinstance(talents, str)
                or len(talents.split("-")) != 3
                or not all(t.isascii() and t.isdigit()
                           for t in talents.split("-"))
                or row.get("status") != "measured_native_chain"):
            continue
        node = LevelNode(
            level=level, talents=talents,
            score_s_per_100=float(row["seconds_per_mob"]) * 100.0,
            source="native_paid",
            details={"native_receipt": row},
        )
        # A historical manifest may contain an incomplete paid observation
        # alongside a fully attributable one at the same level. Filter at the
        # publisher boundary using the DP's own strict receipt predicate:
        # rejecting one unqualified node must not erase genuine paid lineage.
        if _is_paid_native_level_node(node, level):
            candidates[level].append(node)

    # Legacy L20 paid receipts may lack a prepared-actor identity while
    # later levels independently have real native-prepared paid observations.
    # Expose that interior segment, never a fabricated L20 -> L21 link.
    observed_start = first_level
    if not candidates.get(observed_start):
        eligible_later = sorted(l for l in candidates if l > first_level)
        if eligible_later:
            observed_start = eligible_later[0]
    levels = []
    level = observed_start
    while candidates.get(level):
        levels.append(level)
        level += 1
    if not levels:
        return {
            "status": "no_native_prepared_paid_start",
            "levels": [], "steps": [],
            "note": "No matching paid native-prepared actor receipts at the starting level.",
        }

    # A mixed historical manifest may contain several independently paid
    # native binaries. Choose the longest *connected* single-binary prefix,
    # not the lexicographically first SHA (which can lose paid observations).
    # This is only receipt lineage: zero weights prohibit invented XP-time
    # comparisons across different level/scenario observations.
    binaries = sorted({
        node.details["native_receipt"]["engine_binary_sha256"]
        for node in candidates[observed_start]
        if isinstance(node.details["native_receipt"].get("engine_binary_sha256"), str)
    })
    if not binaries:
        return {"status": "no_native_engine_identity", "levels": [], "steps": []}

    model = NativeTalentStringModel()
    selected_engine = None
    path = None
    last_error = None
    for engine in binaries:
        pools = {}
        for level in levels:
            nodes = [
                node for node in candidates[level]
                if node.details["native_receipt"].get("engine_binary_sha256") == engine
            ]
            if not nodes:
                break
            pools[level] = nodes
            try:
                # A paid level can be native-valid yet unable to follow its
                # predecessor without a respec. Retain the proven prefix;
                # never bridge the discontinuity or use another binary.
                candidate_path = solve_path_dp(
                    pools, model=model, max_respecs=0,
                    weights={l: 0.0 for l in pools}, native_paid=True)
            except (ValueError, TypeError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                break
            if path is None or len(candidate_path.steps) > len(path.steps):
                path = candidate_path
                selected_engine = engine
    if path is None:
        return {
            "status": "not_connected_native_paid",
            "levels": sorted(candidates), "steps": [],
            "reason": last_error or "No valid native-paid starting level",
        }
    steps = [{
        "level": step.node.level,
        "kind": step.kind,
        "talent_added": step.talent_added,
        "native_observation_id": step.node.details["native_receipt"]["id"],
        "talents": step.node.talents,
    } for step in path.steps]
    return {
        "status": ("interior_native_paid_talent_frontier" if observed_start > first_level and len(steps) > 1
                   else "single_interior_native_paid_level" if observed_start > first_level
                   else "connected_native_paid_talent_frontier" if len(steps) > 1
                   else "single_native_paid_level"),
        "requested_start_level": first_level,
        "observed_start_level": observed_start,
        "missing_preceding_levels": list(range(first_level, observed_start)),
        "engine_binary_sha256": selected_engine,
        "levels": [step["level"] for step in steps],
        "steps": steps,
        "next_unmeasured_or_unconnected_level": steps[-1]["level"] + 1,
        "xp_progression_simulated": False,
        "cumulative_leveling_seconds": None,
        "note": ("Source-native paid 100-target candidate chains with contiguous "
                 "talent identities only; no XP/travel/training, no full replay."
                 + (f" No native-prepared paid transition from requested L{first_level} "
                    f"to observed L{observed_start} is established."
                    if observed_start > first_level else "")),
    }
