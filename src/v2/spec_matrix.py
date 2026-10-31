from __future__ import annotations

"""Enrich one preserved route with per-level stat and rotation decisions."""

import argparse
import json
from pathlib import Path

from src.class_registry import class_names, get_definition

from src import game_context
from .decision_artifacts import read_json, update_scoped
from .stat_weight_model import compute_for_engine
from .decision_stat_weights import scorer_state_fingerprint


def _mature_score(engine, level: int, talents, *, cfg=None, profile: str = "all"):
    """Score one fixed Mage route step through the existing mature analytic kernel.

    Experimental Forever class engines expose ``experimental_level_score``;
    the mature Mage exposes the richer policy optimizer instead.  Keeping this
    adapter here lets the matrix contract stay identical without pretending the
    two backends have the same fidelity.
    """
    if hasattr(engine, "experimental_level_score"):
        score = dict(engine.experimental_level_score(level, talents, profile))
        if score.get("total_s") is None:
            return score, None, None
        total = float(score["total_s"])
        score.setdefault("mobs_per_hour", 360000.0 / total if total > 0 else None)
        score.setdefault("seconds_per_mob", total / 100.0)
        score.setdefault("kill_seconds_per_mob", float(score.get("kill_s", 0)) / 100.0)
        score.setdefault("recovery_seconds_per_mob", float(score.get("recovery_s", 0)) / 100.0)
        score.setdefault("travel_seconds_per_mob", float(score.get("travel_s", 0)) / 100.0)
        score.setdefault("pull_size", 1)
        return score, None, None
    from .analytic_scorer import AnalyticOptions, optimize_policy_analytic
    cfg = cfg or engine.SimConfig(use_best_water=True)
    policy, result = optimize_policy_analytic(
        int(level), talents, cfg,
        options=AnalyticOptions(kill_boundary_model="normal5q"),
    )
    total = float(result["total_s"])
    out = dict(result)
    gear_stats = dict(engine.real_gear_snapshot(int(level)) or {}) if hasattr(engine, "real_gear_snapshot") else {
        "model": "legacy_owl_curve",
        "owl_intensity": float(getattr(cfg, "owl_intensity", 1.0)),
        "bonus_intellect": float(engine.owl_bonus(int(level), float(getattr(cfg, "owl_intensity", 1.0)))[0]),
        "bonus_spirit": float(engine.owl_bonus(int(level), float(getattr(cfg, "owl_intensity", 1.0)))[1]),
        "spell_power": float(getattr(cfg, "gear_bonus_spell_power", 0.0)),
        "weapon_style": "wand",
    }
    out.update({
        "profile": "single_target",
        "combat_profile": "single_target",
        "rotation": engine.policy_desc(policy, int(level)),
        "policy": engine.policy_desc(policy, int(level)),
        "gear": gear_stats.get("provenance", "gear_snapshot"),
        "gear_stats": gear_stats,
        "pull_size": 1,
        "mobs_per_hour": (360000.0 / total) if total > 0 else None,
        "seconds_per_mob": total / 100.0 if total > 0 else None,
        "kill_seconds_per_mob": float(result.get("kill_s", 0.0) or 0.0) / 100.0,
        "recovery_seconds_per_mob": float(result.get("recovery_s", 0.0) or 0.0) / 100.0,
    })
    return out, policy, cfg


def _mature_stat_weights(engine, level: int, talents, score: dict, policy, cfg):
    """Reuse the existing symmetric stat probe for a fixed Mage allocation."""
    from .path_dp import LevelNode
    from .analytic_scorer import AnalyticOptions
    from .stat_weights import probe_node
    node = LevelNode(int(level), talents, float(score["total_s"]), policy, "matrix", score)
    probed = probe_node(node, cfg, options=AnalyticOptions(kill_boundary_model="normal5q"))
    return (probed.details or {}).get("stat_weights")


def build_matrix(engine, route_path: dict, *, class_name: str, route: str, target: int, cache: dict | None = None, score_profile: str = "all", publication_profile: str | None = None) -> dict:
    cache = cache if cache is not None else {}
    rows = []
    for step in route_path.get("steps", ()):
        ranks = dict(step.get("talent_ranks") or {})
        if not ranks:
            continue
        level = int(step["level"])
        key = (level, tuple(sorted(ranks.items())), str(score_profile))
        if key in cache:
            score, policy, weights, error, cfg = cache[key]
        else:
            talents = engine.Talents(**ranks)
            score, policy, cfg = _mature_score(engine, level, talents, profile=score_profile)
            weights = None
            error = None
            try:
                def _legacy_probe():
                    return _mature_stat_weights(engine, level, talents, score, policy, cfg)
                weights = compute_for_engine(
                    engine, level, talents, baseline=score, policy=policy, cfg=cfg,
                    profile=score_profile, legacy_probe=(None if hasattr(engine, "experimental_level_score") else _legacy_probe),
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            cache[key] = (score, policy, weights, error, cfg)
        talents = engine.Talents(**ranks)
        if not isinstance(weights, dict) or not weights:
            reason = error or "canonical scorer returned no stat weights"
            raise RuntimeError(f"stat-weight contract failed for {class_name} {route} L{level}: {reason}")
        row = {
            "level": level,
            "allocation": engine.final_allocation(talents),
            "talent_ranks": ranks,
            "talent_family": step.get("talent_family"),
            "combat_profile": publication_profile or score.get("combat_profile", score.get("profile")),
            "gear": score.get("gear"),
            "gear_stats": score.get("gear_stats"),
            "pull_size": score.get("pull_size"),
            # Publish the scorer objective explicitly.  Endpoint paths may carry
            # a different gameplay profile for the same talent route; without
            # this field a dashboard merge could accidentally retain that stale
            # endpoint objective and corrupt the stat-weight fingerprint/baseline.
            "score_s_per_100": score.get("score_s_per_100", score.get("total_s")),
            "mobs_per_hour": score.get("mobs_per_hour"),
            "seconds_per_mob": score.get("seconds_per_mob"),
            "kill_seconds_per_mob": score.get("kill_seconds_per_mob"),
            "recovery_seconds_per_mob": score.get("recovery_seconds_per_mob"),
            "travel_seconds_per_mob": score.get("travel_seconds_per_mob"),
            "rotation": score.get("rotation") or (engine.policy_desc(policy, level) if policy is not None else None),
            "policy": score.get("policy") or (engine.policy_desc(policy, level) if policy is not None else None),
            "aura": score.get("aura"),
            "mana_plan": score.get("mana_plan"),
            "stat_weights": weights,
            "stat_weights_error": error,
            "source": "spec_matrix_precomputed",
            "data_sources": ["endpoint_path", "route_specific_fixed_route_scorer"],
            "score_profile": score_profile,
        }
        fp = scorer_state_fingerprint(class_name, row, profile=score_profile)
        row["stat_weight_fingerprint"] = fp
        row["stat_weights"] = dict(weights)
        row["stat_weights"]["scorer_state_fingerprint"] = fp
        row["stat_weights"]["decision_stat_weight_source"] = "spec_matrix_precomputed"
        row["stat_weights_contract_ok"] = True
        rows.append(row)
    cap = int(getattr(engine, "VERIFIED_LEVEL_CAP", target) or target)
    above_cap = bool(cap and int(target) > cap)
    return {
        "schema_version": 1,
        "ruleset": "forever",
        "class": class_name,
        "route": route,
        "target_level": int(target),
        "verified_level_cap": cap,
        "verification_status": "provisional_above_verified_cap" if above_cap else "verified_range",
        "uses_unverified_levels": above_cap,
        "unverified_from_level": (cap + 1) if above_cap else None,
        "status": "available" if rows else "route_steps_unavailable",
        "rows": rows,
        "score_profile": score_profile,
        "publication_profile": publication_profile,
        "note": "fixed preserved talent route; gameplay/profile re-optimized per level; no talent search rerun",
    }


def _generate_one(engine, endpoints: dict, class_name: str, target: int, route: str, cache: dict) -> dict:
    cls = (endpoints.get("classes") or {}).get(class_name, {})
    target_row = (cls.get("targets") or {}).get(str(int(target)), {})
    route_row = (target_row.get("routes") or {}).get(route, {})
    if route_row.get("status") != "available":
        return {
            "schema_version": 2, "ruleset": "forever", "class": class_name,
            "route": route, "target_level": int(target), "status": route_row.get("status", "route_not_available"), "rows": [],
        }
    definition = dict(get_definition("forever", class_name).route_definitions.get(route) or {})
    return build_matrix(
        engine, route_row.get("path") or {}, class_name=class_name, route=route, target=int(target), cache=cache,
        score_profile=str(definition.get("score_profile") or "all"),
        publication_profile=(str(definition["publication_profile"]) if definition.get("publication_profile") else None),
    )


def generate(class_name: str, target: int, route: str, *, project_root: Path | str = ".") -> tuple[Path, dict]:
    game_context.configure("forever", class_name)
    from src.engine_registry import get_engine, reset_engine_cache
    reset_engine_cache()
    engine = get_engine()
    root = Path(project_root).resolve()
    decision_root = game_context.base_state_root(root) / "decisions" / "forever"
    endpoints = read_json(decision_root / "endpoint_paths.json", {}) or {}
    payload = _generate_one(engine, endpoints, class_name, target, route, {})
    path = decision_root / "spec_matrix.json"
    current = read_json(path, {}) or {}
    old = (current.get("classes") or {}).get(class_name, {})
    matrices = dict(old.get("matrices") or {}) if isinstance(old, dict) else {}
    matrices[f"{int(target)}:{route}"] = payload
    update_scoped(path, class_name, {"schema_version": 2, "class": class_name, "matrices": matrices})
    return path, payload


def generate_all(class_name: str, targets: list[int], *, project_root: Path | str = ".") -> tuple[Path, dict]:
    game_context.configure("forever", class_name)
    from src.engine_registry import get_engine, reset_engine_cache
    reset_engine_cache(); engine = get_engine()
    root = Path(project_root).resolve()
    decision_root = game_context.base_state_root(root) / "decisions" / "forever"
    endpoints = read_json(decision_root / "endpoint_paths.json", {}) or {}
    cls = (endpoints.get("classes") or {}).get(class_name, {})
    definitions = list((cls.get("definitions") or {}).keys())
    cache: dict = {}; matrices: dict[str, dict] = {}
    for target in targets:
        routes = ["unconstrained", *definitions]
        for route in routes:
            payload = _generate_one(engine, endpoints, class_name, target, route, cache)
            if payload.get("status") == "available":
                matrices[f"{int(target)}:{route}"] = payload
    class_payload = {"schema_version": 2, "class": class_name, "matrices": matrices}
    path = decision_root / "spec_matrix.json"
    update_scoped(path, class_name, class_payload)
    return path, class_payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build per-level stats/rotation matrix for a preserved route")
    ap.add_argument("--class", dest="class_name", choices=class_names("forever"), required=True)
    ap.add_argument("--target", type=int, required=True)
    ap.add_argument("--route")
    ap.add_argument("--all-routes", action="store_true")
    ap.add_argument("--targets", help="comma-separated targets; implies --all-routes")
    ap.add_argument("--project-root", default=".")
    args = ap.parse_args(argv)
    if args.all_routes or args.targets:
        targets = [int(x) for x in args.targets.split(",")] if args.targets else [args.target]
        path, payload = generate_all(args.class_name, targets, project_root=args.project_root)
        print(json.dumps({"path": str(path), "matrices": len(payload["matrices"])}, sort_keys=True))
    else:
        if not args.route:
            ap.error("--route is required unless --all-routes/--targets is used")
        path, payload = generate(args.class_name, args.target, args.route, project_root=args.project_root)
        print(json.dumps({"path": str(path), "status": payload["status"], "rows": len(payload.get("rows", ()))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
