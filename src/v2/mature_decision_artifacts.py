from __future__ import annotations

"""Publish the common decision artifacts for a mature analytic backend.

The Forever Mage search predates the experimental Paladin/Druid publisher and
returns ``LevelNode`` pools instead.  This adapter deliberately translates the
already-scored pools; it never launches a second talent search and never
changes the Classic Mage implementation.
"""

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.objective import level_weight_per_100

from .decision_artifacts import MILESTONE_LEVELS, bounded_candidate
from .class_model import CandidateResult, ClassModel, EngineClassModel, Evaluation, LevelFrontier


def _added_talent(parent, child, engine) -> str | None:
    """Return the unique legal +1 talent edge, or ``None``."""
    if int(child.points()) != int(parent.points()) + 1:
        return None
    found = None
    for name in parent.__dataclass_fields__:
        old = int(getattr(parent, name))
        new = int(getattr(child, name))
        if new == old:
            continue
        if new != old + 1 or found is not None:
            return None
        found = name
    if found is None:
        return None
    try:
        return found if engine.add_point(parent, found) == child else None
    except Exception:
        return None


def _gear_stats(engine, level: int, cfg) -> dict:
    """Expose the exact gear snapshot consumed by the mature Mage runtime."""
    if hasattr(engine, "real_gear_snapshot"):
        return dict(engine.real_gear_snapshot(int(level)) or {})
    intensity = float(getattr(cfg, "owl_intensity", 1.0))
    bonus_intellect, bonus_spirit = engine.owl_bonus(int(level), intensity)
    return {
        "model": "legacy_owl_curve",
        "owl_intensity": intensity,
        "bonus_intellect": float(bonus_intellect),
        "bonus_spirit": float(bonus_spirit),
        "spell_power": float(getattr(cfg, "gear_bonus_spell_power", 0.0)),
        "weapon_style": "wand",
    }


def _score_fields(node, engine, cfg) -> dict:
    level = int(node.level)
    details = dict(node.details or {})
    score = float(node.score_s_per_100)
    # 100 mobs / score seconds -> mobs per hour.  Keep the conversion here so
    # mature and experimental cards share one player-facing unit.
    mph = (360000.0 / score) if score > 0 else None
    rotation = engine.policy_desc(node.policy, level) if node.policy is not None else "—"
    rotation_adjudication = None
    # The mature analytic path predates Forever's proc/control rotations. Do
    # not let that approximation erase structural actions that the event/MC
    # kernel can actually execute. Once a build unlocks one of the new Forever
    # rotation mechanics, run the bounded focused event-policy search for that
    # talent family and publish its best executable rotation. Talent/path
    # scoring remains analytic; this only fixes the player-facing policy gap.
    if (getattr(engine, "RULESET", None) == "forever"
            and getattr(engine, "CLASS_NAME", None) == "mage"
            and hasattr(engine, "policy_search")):
        talents = node.talents
        structural_schools = []
        if int(getattr(talents, "ice_lance", 0) or 0) > 0:
            structural_schools.append("frost")
        if int(getattr(talents, "arcane_blast", 0) or 0) > 0:
            structural_schools.append("arcane")
        if (int(getattr(talents, "hot_streak", 0) or 0) > 0
                and int(getattr(talents, "pyroblast", 0) or 0) > 0):
            structural_schools.append("fire")
        if structural_schools:
            # If a hybrid build has multiple structural unlocks, adjudicate the
            # tree in which it has invested the most points. Stable lexical
            # tie-breaking keeps artifacts deterministic.
            tree_points_for_choice = {
                school: int(engine.tree_points(talents, school))
                for school in structural_schools
            }
            school = sorted(structural_schools, key=lambda sc: (-tree_points_for_choice[sc], sc))[0]
            try:
                rotation_adjudication = engine.policy_search(level, talents, cfg, school, n=64, seed=7)
                chosen = dict(rotation_adjudication.get("best_found") or {})
                if chosen.get("rotation"):
                    rotation = str(chosen["rotation"])
            except Exception:
                rotation_adjudication = None
    tree_names = tuple(getattr(engine, "TREE_NAMES", ("frost", "arcane", "fire")))
    tree_points = {name: int(engine.tree_points(node.talents, name)) for name in tree_names}
    ordered = sorted(tree_points.items(), key=lambda item: (-item[1], item[0]))
    top = ordered[0][1] if ordered else 0
    tied = [name for name, value in ordered if value == top and value > 0]
    school = ordered[0][0] if ordered else "mixed"
    family = "+".join(sorted(tied)) if len(tied) >= 2 else f"{school}+{ordered[1][0] if len(ordered) > 1 and ordered[1][1] >= 5 else 'none'}"
    ev = Evaluation.from_raw({**details, "total_s": score})
    timing = ev.published_fields()
    kill_s = float(ev.kill_s_per_100 or 0.0)
    recovery_s = float(ev.recovery_s_per_100 or 0.0)
    gear_stats = _gear_stats(engine, level, cfg)
    return {
        **timing,
        "allocation": engine.final_allocation(node.talents),
        "talent_ranks": {
            name: int(getattr(node.talents, name))
            for name in node.talents.__dataclass_fields__
            if int(getattr(node.talents, name))
        },
        "tree_points": tree_points,
        "talent_family": family,
        "combat_profile": "single_target",
        "kill_share": (kill_s / score) if score > 0 and ev.kill_s_per_100 is not None else None,
        "recovery_share": (recovery_s / score) if score > 0 and ev.recovery_s_per_100 is not None else None,
        "gear": gear_stats.get("provenance", "gear_snapshot"),
        "gear_stats": gear_stats,
        "pull_size": 1,
        "policy": rotation,
        "rotation": rotation,
        "rotation_adjudication": rotation_adjudication,
        "model_fidelity": dict(getattr(engine, "MODEL_FIDELITY", {}) or {}),
        "source": f"forever-mature-{node.source}",
        "details": details,
    }


def _step(node, engine, cfg, *, added: str | None) -> dict:
    row = _score_fields(node, engine, cfg)
    row.update({"level": int(node.level), "talent_added": added})
    row.pop("details", None)
    return row


def _frontier_candidate(node, engine, cfg, *, cumulative: float, steps: Sequence[dict]) -> dict:
    row = _score_fields(node, engine, cfg)
    row["level"] = int(node.level)
    row["cumulative_objective_s"] = float(cumulative)
    row["steps"] = list(steps)
    # The endpoint/dual-spec code already bounds its own copies.  Keeping the
    # full steps here is useful for the machine-readable frontier and remains
    # small because only the preserved candidate cap is published.
    row.pop("details", None)
    return row


def build_frontier(class_name: str, pools: Mapping[int, Sequence[object]], engine, cfg,
                   *, start_level: int, end_level: int,
                   candidate_limit: int = 48,
                   verified_level_cap: int | None = None) -> dict:
    """Attach the cheapest preserved no-respec prefix to every reachable node."""
    levels = [int(level) for level in sorted(pools) if int(start_level) <= int(level) <= int(end_level)]
    if not levels or any(b != a + 1 for a, b in zip(levels, levels[1:])):
        raise ValueError("mature decision frontier requires contiguous level pools")

    # A node can have several parents in the bounded repaired pool.  Keep its
    # cheapest prefix and the corresponding complete path steps.
    state: dict[tuple[int, tuple[int, ...]], tuple[float, list[dict]]] = {}
    published: list[dict] = []
    for index, level in enumerate(levels):
        nodes = list(pools[level])
        current: dict[tuple[int, ...], tuple[float, list[dict], object]] = {}
        weight = float(level_weight_per_100(level))
        for node in nodes:
            if index == 0:
                parent_rows = [(0.0, [])]
            else:
                parent_rows = []
                for parent in pools[levels[index - 1]]:
                    added = _added_talent(parent.talents, node.talents, engine)
                    if added is None:
                        continue
                    prior = state.get((levels[index - 1], tuple(parent.talents.__dict__.values())))
                    if prior is not None:
                        parent_rows.append((prior[0], prior[1]))
            if not parent_rows:
                continue
            best_cost, best_steps = min(parent_rows, key=lambda item: item[0])
            added = None
            if index > 0:
                # Reconstruct only the final edge; the previous path already
                # contains its own edge labels.
                for parent in pools[levels[index - 1]]:
                    if _added_talent(parent.talents, node.talents, engine) is not None:
                        prior = state.get((levels[index - 1], tuple(parent.talents.__dict__.values())))
                        if prior is not None and abs(prior[0] - best_cost) <= 1e-9:
                            added = _added_talent(parent.talents, node.talents, engine)
                            break
            steps = list(best_steps)
            steps.append(_step(node, engine, cfg, added=added))
            cost = best_cost + weight * float(node.score_s_per_100)
            key = tuple(node.talents.__dict__.values())
            old = current.get(key)
            if old is None or cost < old[0] - 1e-12:
                current[key] = (cost, steps, node)
        state = {(level, key): (cost, steps) for key, (cost, steps, _node) in current.items()}
        candidates = [
            _frontier_candidate(node, engine, cfg, cumulative=cost, steps=steps)
            for cost, steps, node in sorted(
                current.values(), key=lambda item: (item[0], float(item[2].score_s_per_100), tuple(item[2].talents.__dict__.values()))
            )[: max(3, int(candidate_limit))]
        ]
        published.append({
            "level": level,
            "candidate_count": len(candidates),
            "beam_pool_size": len(nodes),
            "candidates": candidates,
        })
    return {
        "schema_version": 1,
        "ruleset": "forever",
        "class": class_name,
        "start_level": int(start_level),
        "end_level": int(end_level),
        "verified_level_cap": int(verified_level_cap if verified_level_cap is not None else end_level),
        "bounded": True,
        "candidate_limit": max(3, int(candidate_limit)),
        "objective": "cumulative weighted leveling seconds",
        "model_fidelity": dict(getattr(engine, "MODEL_FIDELITY", {}) or {}),
        "authority": "best_preserved_frontier_path",
        "levels": published,
    }




def publish_mature_class_decisions(class_name: str, pools: Mapping[int, Sequence[object]], engine, cfg,
                                   *, start_level: int, end_level: int,
                                   dual_spec_unlock_level: int = 40,
                                   candidate_limit: int = 48,
                                   max_respecs: int = 0,
                                   model: ClassModel | None = None) -> dict:
    """Write shared decision artifacts for a mature Forever search strategy.

    Presentation-frontier construction remains backend-shaped, but route solving
    and publication use the same generic ``decision_pipeline`` as continuity-beam
    classes. Canonical DecisionResult is the sole route authority.
    """
    frontier = build_frontier(
        class_name, pools, engine, cfg, start_level=start_level, end_level=end_level,
        candidate_limit=candidate_limit,
        verified_level_cap=int(getattr(engine, "VERIFIED_LEVEL_CAP", end_level)),
    )

    route_model = model or EngineClassModel(engine)
    canonical_frontiers = []
    for level in sorted(pools):
        if not (int(start_level) <= int(level) <= int(end_level)):
            continue
        candidates=[]
        for node in pools[level]:
            details=dict(node.details or {})
            details['total_s']=float(node.score_s_per_100)
            row=_score_fields(node,engine,cfg)
            row['level']=int(level)
            candidates.append(CandidateResult(
                level=int(level), build=node.talents, loadout=row.get('gear_stats'), policy=node.policy,
                evaluation=Evaluation.from_raw(details),
                metadata={'source':f"forever-mature-{node.source}",'publication_row':row},
            ))
        canonical_frontiers.append(LevelFrontier(int(level),tuple(candidates)))
    targets=sorted(set(
        [int(level) for level in MILESTONE_LEVELS if int(start_level) <= int(level) <= int(end_level)] + [int(end_level)]
    ))

    from .decision_pipeline import publish_decisions
    decisions=publish_decisions(
        class_name=class_name, canonical_frontiers=canonical_frontiers, model=route_model,
        presentation_frontier=frontier,
        verified_level_cap=int(getattr(engine, 'VERIFIED_LEVEL_CAP', end_level)),
        targets=targets, target_level=int(end_level),
        dual_spec_unlock_level=int(dual_spec_unlock_level),
        unconstrained_max_respecs=max(0,int(max_respecs)), constrained_max_respecs=0,
    )
    return {
        "decision_frontier_json": decisions["decision_frontier_json"],
        "endpoint_paths_json": decisions["endpoint_paths_json"],
        "spec_regret_json": decisions["spec_regret_json"],
        "dual_spec_json": decisions["dual_spec_json"],
        "dual_spec": decisions["dual_spec"],
        "frontier": frontier,
        "decision_authority": decisions["decision_authority"],
    }
