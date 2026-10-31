from __future__ import annotations

"""G39 canonical bounded Warrior/Rogue routes through native generic Game IR.

Unlike the fully-geared Druid G32 corridor, these frontiers are explicit proxy
combat/recovery scenarios. Talent allocations, executable modifiers, Policy IR,
CombatRuntime, Evaluation, CandidateResult and the canonical solve_routes DP are
real; no legacy scorer, invented talent point, fake named gear, or fake stat
weight is used. API accepts a release snapshot only if code+version+DB match.
"""

from dataclasses import replace
from functools import lru_cache
import hashlib
import json
from math import isfinite
from pathlib import Path
from typing import Any

from src.game.data.forever import build_game_ir_slice
from src.game.data.forever.registry import generic_planning_levels
from src.game.talents import apply_talent_selection, available_talent_points
from src.game.talent_search import search_talent_allocations, talent_candidate_id
from src.game.evaluation import Evaluation
from src.version import SOFTWARE_VERSION
from .class_model import CandidateResult, LevelFrontier
from .generic_frontier import (GenericTalentBuild, GenericTalentRouteModel,
                                ROUTE_AUTHORITY, CANONICAL_ITEM_DB_PATH, PROJECT_ROOT,
                                route_ready_frontiers)
from .decision_result import reports, solve_routes

MELEE_CORRIDORS = {key: generic_planning_levels(key) for key in ("warrior", "rogue")}
MELEE_CACHE_SCHEMA = 1
MELEE_CACHE_PATH = PROJECT_ROOT / "data" / "forever" / "generic_melee_route_publication_v1.json"
_SOURCE_PATHS = ("src/game/talents.py", "src/game/data/forever/registry.py", "src/game/data/forever/warrior.py",
                 "src/game/data/forever/rogue.py", "src/v2/generic_melee_routes.py",
                 "src/v2/generic_backend.py", "src/game/runtime/simulator.py",
                 "src/game/talent_search.py", "src/v2/generic_frontier.py",
                 "src/v2/decision_result.py", "src/game/policy.py",
                 "src/game/policy_search.py", "src/game/policy_threshold_search.py",
                 "src/game/model/ir.py", "src/game/evaluation.py")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint() -> str:
    digest = hashlib.sha256()
    for name in _SOURCE_PATHS:
        digest.update(name.encode())
        digest.update(bytes.fromhex(_sha(PROJECT_ROOT / name)))
    return digest.hexdigest()


def _timed_policy_score(ir_slice, *, level: int):
    """Exactly the generic policy+runtime scorer already used by G19/G37/G38."""
    from .generic_backend import _searched_policy_combat_evaluation
    ev, execution, detail, structure, thresholds, efficiency = _searched_policy_combat_evaluation(
        ir_slice, level=level)
    policy = ((None if thresholds is None else thresholds.selected_policy)
              or (None if structure is None else structure.selected_policy))
    return ev, execution, policy, detail, efficiency


def _exact_sensitivity(ir_slice, *, level: int, policy, baseline_s: float) -> dict[str, float]:
    """Fixed-policy forward differences over explicit proxy attack stats."""
    from .generic_backend import _policy_combat_evaluation
    weights: dict[str, float] = {}
    for key in ("weapon_dps", "attack_power"):
        stats = dict(ir_slice.actor.base_stats)
        stats[key] = float(stats.get(key, 0.0)) + 1.0
        altered = replace(ir_slice, actor=replace(ir_slice.actor, base_stats=stats))
        ev, _, _ = _policy_combat_evaluation(altered, level=level, policy_override=policy)
        if ev is None:
            raise ValueError(f"L{level} {key} scorer sensitivity could not be evaluated")
        weights[key] = float(baseline_s) - float(ev.seconds_per_mob)
    return weights


def build_melee_level_frontier(class_name: str, level: int) -> LevelFrontier:
    cls = str(class_name).lower()
    if cls not in MELEE_CORRIDORS or int(level) not in MELEE_CORRIDORS[cls]:
        raise ValueError(f"{class_name} L{level} outside fully executable G39 corridor")
    ir = build_game_ir_slice(class_key=cls, level=level)
    if ir is None or not ir.talents:
        raise ValueError(f"{cls} L{level} has no executable talent source")
    scored: dict[str, tuple] = {}

    def evaluate(selection):
        cid = talent_candidate_id(selection)
        talented, application = apply_talent_selection(ir, selection, level=level)
        ev, execution, policy, detail, efficiency = _timed_policy_score(talented, level=level)
        if ev is None or policy is None or execution is None:
            return None, {"reason": "generic_policy_did_not_kill_target"}
        scored[cid] = (talented, application, ev, execution, policy, efficiency)
        return ev.seconds_per_mob, {"policy_id": policy.id, "policy_candidate_id": policy.id}

    result = search_talent_allocations(ir, level=level, evaluate=evaluate, max_candidates=64)
    if result.truncated:
        raise ValueError(f"{cls} L{level} talent enumeration truncated: fail closed")
    candidates = []
    tree_map = {t.id: t.tree_key for t in ir.talents}
    for entry in result.candidates:
        if not entry.valid or entry.candidate_id not in scored:
            continue
        talented, app, ev, execution, policy, efficiency = scored[entry.candidate_id]
        build = GenericTalentBuild.from_candidate(entry.as_dict(),
            available_points=available_talent_points(level),
            executable_talent_ids=result.executable_talent_ids, talent_tree_by_id=tree_map)
        # Score every represented budget point. Under-spent candidates are kept
        # for diagnostics but must never enter route DP.
        weights = _exact_sensitivity(talented, level=level, policy=policy,
                                     baseline_s=float(ev.seconds_per_mob))
        action_names = {a.id:a.name for a in talented.actions}
        performed = [str(x['action_id']) for x in execution.selected_actions]
        unique_actions = list(dict.fromkeys(performed))
        seconds = float(ev.seconds_per_mob)
        talent_actions = {str(x['action_id']) for x in app.applied_modifiers}
        talent_effect_executed = bool(talent_actions.intersection(performed))
        warnings = ["scenario_proxy_weapon_and_base_stats", "no_named_gear",
                    "hit_crit_table_and_travel_unresolved"]
        if build.spent_points and not talent_effect_executed:
            warnings.append("allocated_talent_effect_not_executed_in_selected_combat")
        row = {
            "level": level, "allocation": build.candidate_id,
            "talent_ranks": {k:int(v) for k,v in build.ranks},
            "tree_points": {k:int(v) for k,v in build.tree_points},
            "talent_family": max(build.tree_points, key=lambda x:x[1])[0] if build.tree_points else None,
            "score_s_per_100": 100.0*seconds, "seconds_per_mob":seconds,
            "mobs_per_hour":3600.0/seconds if seconds>0 else None,
            "rotation": " → ".join(action_names.get(a,a) for a in unique_actions) or "Autoattack only",
            "rotation_steps": [{"label":action_names.get(a,a)} for a in unique_actions],
            "policy": policy.id, "policy_ir": policy.as_dict(),
            "gear_stats": {"slots":{}, "selection_method":"explicit_scenario_proxy_not_named_gear",
                           "aggregate_stats":dict(talented.actor.base_stats)},
            "stat_weights": {"method":"native_generic_fixed_policy_proxy_scenario_forward_difference",
                             "stats":{k:{"seconds_saved_per_100_per_point":100.0*v,"status":"measured_on_proxy"}
                                      for k,v in weights.items()}},
            "combat_profile":"melee", "score_profile":"melee",
            "talent_points_contract_ok":build.spent_points==build.available_points,
            "talent_effect_executed":talent_effect_executed,
            "stat_weights_contract_ok":True,
            "quality_warnings":warnings,
            "decision_contract":{"backend":{"id":"generic"},"schema_version":1},
            "source":ROUTE_AUTHORITY, "legacy_fallback":False,
        }
        candidates.append(CandidateResult(level=level, build=build,
            loadout={"slots":{},"selection_method":"explicit_scenario_proxy_not_named_gear"},
            policy={"candidate_id":policy.id,"policy_id":policy.id}, evaluation=ev,
            stat_weights=weights,
            metadata={"source":"native_generic_melee_policy_runtime",
                      "candidate_id":entry.candidate_id,
                      "talent_candidate_id":build.candidate_id,
                      "publication_row":row, "route_ready":build.spent_points==build.available_points,
                      "talent_application":app.as_dict(), "legacy_fallback":False}))
    if not candidates:
        raise ValueError(f"{cls} L{level} has no executable candidate")
    return LevelFrontier(level=level, candidates=tuple(candidates))


@lru_cache(maxsize=2)
def solve_generic_melee_routes(class_name: str):
    cls = str(class_name).lower()
    levels = MELEE_CORRIDORS[cls]
    frontiers = route_ready_frontiers(tuple(build_melee_level_frontier(cls, level) for level in levels))
    result = solve_routes(frontiers, model=GenericTalentRouteModel(),
                          class_name=cls, targets=(levels[-1],),
                          unconstrained_max_respecs=0, constrained_max_respecs=0)
    if result.targets[levels[-1]]["unconstrained"].status != "available":
        raise ValueError(f"{cls} route continuity failed closed")
    return replace(result, authority=ROUTE_AUTHORITY)


def build_generic_melee_route_publication() -> dict[str, Any]:
    """Live authority: real CandidateResult frontiers -> shared route DP."""
    classes = {}
    for cls, levels in MELEE_CORRIDORS.items():
        result = solve_generic_melee_routes(cls)
        endpoint, regret = reports(result, verified_level_cap=levels[-1])
        target_routes = result.targets[levels[-1]]
        route_rows = {}
        for name, route in target_routes.items():
            if route.status != "available" or route.path is None:
                route_rows[name] = {"status":"unavailable", "reason":route.reason, "rows":[]}
                continue
            rows = []
            for step in route.path.steps:
                candidate = step.node.details.get("candidate_result")
                if not isinstance(candidate, CandidateResult):
                    raise ValueError(f"{cls} L{step.node.level}: missing native CandidateResult")
                row = dict(candidate.metadata["publication_row"])
                if abs(row["score_s_per_100"]-float(step.node.score_s_per_100))>1e-7:
                    raise ValueError(f"{cls} L{step.node.level}: route score diverged from runtime")
                if not row["stat_weights"]["stats"] or not row["talent_points_contract_ok"]:
                    raise ValueError(f"{cls} L{step.node.level}: native weights/points absent")
                rows.append({**row, "talent_added":step.talent_added,
                             "respecs_used":step.respecs_used,
                             "cumulative_objective_s":step.cumulative_s})
            route_rows[name] = {"status":"available", "reason":None,
                                "rows":rows,"source":ROUTE_AUTHORITY,"legacy_fallback":False}
        baseline = target_routes["unconstrained"].path
        if baseline is None:
            raise ValueError(f"{cls}: canonical route reported available without native path")
        classes[cls] = {
            "authority":ROUTE_AUTHORITY, "class_name":cls,
            "levels":list(levels), "target_level":levels[-1], "route_solving":True,
            "route_scope":"fully_executable_early_talent_budget_with_explicit_weapon_proxy",
            "path":dict(endpoint["targets"][str(levels[-1])]["routes"]["unconstrained"].get("path") or {}),
            "regret":dict(regret["targets"][str(levels[-1])]["routes"].get("unconstrained") or {}),
            "endpoint_report":endpoint, "regret_report":regret,
            "route_rows":{str(levels[-1]):{"routes":route_rows}},
            "named_routes":{k:{"status":v.status,"reason":v.reason} for k,v in target_routes.items() if k!="unconstrained"},
            "normal_route_selectable":bool(route_rows["unconstrained"]["status"]=="available"),
            "normal_route_step_count":len(route_rows["unconstrained"]["rows"]),
            "route_blocker_above_level":levels[-1],
            "route_blocker":"additional earned talent points not fully represented; no opaque continuation points",
            "quality_warnings":["proxy_weapon_and_primary_stats", "no_named_gear", "no_travel_or_full_attack_table"],
            "legacy_fallback":False,
        }
    return {"schema_version":MELEE_CACHE_SCHEMA,"software_version":SOFTWARE_VERSION,
            "ruleset":"forever","route_authority":ROUTE_AUTHORITY,
            "levels":{k:list(v) for k,v in MELEE_CORRIDORS.items()},
            "canonical_item_db_sha256":_sha(CANONICAL_ITEM_DB_PATH),
            "source_code_fingerprint":_fingerprint(),"classes":classes}


def write_generic_melee_route_publication_cache(path: Path | str = MELEE_CACHE_PATH) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(build_generic_melee_route_publication(),indent=2,sort_keys=True)+"\n",
                      encoding="utf-8")
    return target


def generic_melee_route_publication(path: Path | str = MELEE_CACHE_PATH) -> tuple[dict[str,Any],dict[str,Any]]:
    target = Path(path)
    reason = "cache_missing"
    if target.is_file():
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            checks = {
                "schema_version":payload.get("schema_version")==MELEE_CACHE_SCHEMA,
                "software_version":payload.get("software_version")==SOFTWARE_VERSION,
                "ruleset":payload.get("ruleset")=="forever",
                "route_authority":payload.get("route_authority")==ROUTE_AUTHORITY,
                "levels":payload.get("levels")=={k:list(v) for k,v in MELEE_CORRIDORS.items()},
                "canonical_item_db_sha256":payload.get("canonical_item_db_sha256")==_sha(CANONICAL_ITEM_DB_PATH),
                "source_code_fingerprint":payload.get("source_code_fingerprint")==_fingerprint(),
                "classes":set(payload.get("classes",{}))==set(MELEE_CORRIDORS),
            }
            if all(checks.values()):
                return dict(payload["classes"]),{"status":"validated_release_snapshot","checks":checks,
                                                     "legacy_fallback":False}
            reason = "cache_fingerprint_mismatch:"+",".join(k for k,ok in checks.items() if not ok)
        except (OSError,ValueError,TypeError) as exc:
            reason = f"cache_invalid:{type(exc).__name__}"
    result = build_generic_melee_route_publication()
    return dict(result["classes"]), {"status":"live_canonical_solve","reason":reason,
                                     "legacy_fallback":False}
