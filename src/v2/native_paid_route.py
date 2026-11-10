"""Connect *already executed* Warlock native paid receipts in gsim path DP.

This is a source-request/receipt routing adapter. Rust, not this module, is
authoritative for build legality and combat. Connected paid levels are not a
continuous XP, travel, training or full 10-60 journey simulation.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .class_model import ClassModel
from .path_dp import LevelNode, solve_path_dp


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
        candidates[level].append(LevelNode(
            level=level, talents=talents,
            score_s_per_100=float(row["seconds_per_mob"]) * 100.0,
            source="native_paid",
            details={"native_receipt": row},
        ))

    levels = []
    level = first_level
    while candidates.get(level):
        levels.append(level)
        level += 1
    if not levels:
        return {
            "status": "no_native_prepared_paid_start",
            "levels": [], "steps": [],
            "note": "No matching paid native-prepared actor receipts at the starting level.",
        }

    # Different engine binaries are not one homogeneous native route source.
    # Candidate choices remain per-level native-paid observations, not source
    # legality reconstruction or a fabricated cross-engine comparison.
    binaries = {node.details["native_receipt"]["engine_binary_sha256"]
                for node in candidates[first_level]
                if isinstance(node.details["native_receipt"].get("engine_binary_sha256"), str)}
    if not binaries:
        return {"status": "no_native_engine_identity", "levels": [], "steps": []}
    selected_engine = sorted(binaries)[0]
    pools = {}
    for l in levels:
        nodes = [
            node for node in candidates[l]
            if node.details["native_receipt"].get("engine_binary_sha256") == selected_engine
        ]
        if not nodes:
            break
        pools[l] = nodes
    if not pools:
        return {"status": "no_matching_native_engine", "levels": [], "steps": []}

    model = NativeTalentStringModel()
    try:
        # Zero weights intentionally suppress route time selection: the real
        # paid 100-mob elapsed observations are NOT XP-weighted leveling costs.
        path = solve_path_dp(
            pools, model=model, max_respecs=0,
            weights={l: 0.0 for l in pools}, native_paid=True)
    except (ValueError, TypeError) as exc:
        return {
            "status": "not_connected_native_paid",
            "levels": sorted(pools), "steps": [],
            "reason": f"{type(exc).__name__}: {exc}",
        }
    steps = [{
        "level": step.node.level,
        "kind": step.kind,
        "talent_added": step.talent_added,
        "native_observation_id": step.node.details["native_receipt"]["id"],
        "talents": step.node.talents,
    } for step in path.steps]
    return {
        "status": ("connected_native_paid_talent_frontier" if len(steps) > 1
                   else "single_native_paid_level"),
        "engine_binary_sha256": selected_engine,
        "levels": [step["level"] for step in steps],
        "steps": steps,
        "next_unmeasured_or_unconnected_level": steps[-1]["level"] + 1,
        "xp_progression_simulated": False,
        "cumulative_leveling_seconds": None,
        "note": ("Source-native paid 100-target candidate chains with contiguous "
                 "talent identities only; no XP/travel/training, no full replay."),
    }
