from __future__ import annotations

"""General regret queries over an already-preserved decision frontier."""

import argparse
import json
import shlex
from pathlib import Path

from src.class_registry import class_names

from .decision_artifacts import bounded_candidate, frontier_path, read_json
from .regret import compute_regret


ALLOWED_KEYS = {
    "talent_minimums", "talent_exact", "tree_minimums",
    "talent_family", "combat_profile", "gear", "pull_size",
    "at_level", "at_level_talent_minimums", "at_level_talent_exact",
    "at_level_talent_allocation_exact",
}


def rerun_commands(class_name: str, target_level: int, constraint: dict, *, start_level: int = 10) -> list[str]:
    encoded = shlex.quote(json.dumps(constraint, sort_keys=True, separators=(",", ":")))
    return [
        " ".join((
            "python -m src.v2.runner --ruleset forever", f"--class {shlex.quote(class_name)}",
            f"--start-level {int(start_level)} --end-level {int(target_level)}",
            "--beam-width 24 --family-keep 6 --final-k 20 --no-stat-weights --workers 1 --view smooth",
        )),
        " ".join((
            "python -m src.v2.constrained_routes", f"--class {shlex.quote(class_name)}",
            f"--target {int(target_level)}", f"--constraint-json {encoded}",
        )),
    ]


def normalize_constraint(raw: dict) -> dict:
    unknown=set(raw)-ALLOWED_KEYS
    if unknown:
        raise ValueError("unknown constraint key(s): "+", ".join(sorted(unknown)))
    out={}
    for key in ("talent_minimums","talent_exact","tree_minimums",
                "at_level_talent_minimums","at_level_talent_exact",
                "at_level_talent_allocation_exact"):
        if key in raw:
            if not isinstance(raw[key],dict):
                raise ValueError(f"{key} must be an object")
            vals={str(name):int(value) for name,value in raw[key].items()}
            if any(value<0 for value in vals.values()):
                raise ValueError(f"{key} values must be non-negative")
            out[key]=vals
    for key in ("talent_family","combat_profile","gear"):
        if raw.get(key) is not None:
            out[key]=str(raw[key])
    if raw.get("pull_size") is not None:
        out["pull_size"]=max(1,int(raw["pull_size"]))
    if raw.get("at_level") is not None:
        out["at_level"]=max(1,int(raw["at_level"]))
    if ("at_level_talent_minimums" in out or "at_level_talent_exact" in out or "at_level_talent_allocation_exact" in out) and "at_level" not in out:
        raise ValueError("at_level is required with at_level talent constraints")
    if not out:
        raise ValueError("constraint must contain at least one supported condition")
    return out


def matches(candidate:dict,constraint:dict) -> bool:
    ranks=candidate.get("talent_ranks") or {}
    trees=candidate.get("tree_points") or {}
    if any(int(ranks.get(name,0))<int(value) for name,value in constraint.get("talent_minimums",{}).items()):
        return False
    if any(int(ranks.get(name,0))!=int(value) for name,value in constraint.get("talent_exact",{}).items()):
        return False
    if any(int(trees.get(name,0))<int(value) for name,value in constraint.get("tree_minimums",{}).items()):
        return False
    at_level=constraint.get("at_level")
    if at_level is not None:
        step=next((s for s in candidate.get("steps",()) if int(s.get("level",-1))==int(at_level)),None)
        if step is None:
            return False
        step_ranks=step.get("talent_ranks") or {}
        if any(int(step_ranks.get(name,0))<int(value) for name,value in constraint.get("at_level_talent_minimums",{}).items()):
            return False
        if any(int(step_ranks.get(name,0))!=int(value) for name,value in constraint.get("at_level_talent_exact",{}).items()):
            return False
        exact_allocation=constraint.get("at_level_talent_allocation_exact")
        if exact_allocation is not None:
            actual={str(name):int(value) for name,value in step_ranks.items() if int(value)>0}
            expected={str(name):int(value) for name,value in exact_allocation.items() if int(value)>0}
            if actual != expected:
                return False
    for key in ("talent_family","combat_profile","gear"):
        if key in constraint and str(candidate.get(key))!=constraint[key]:
            return False
    if "pull_size" in constraint and int(candidate.get("pull_size") or 0)!=constraint["pull_size"]:
        return False
    return True


def _continuation_summary(candidate: dict, *, at_level: int, target_level: int) -> dict:
    steps=[dict(s) for s in candidate.get("steps",()) if s.get("level") is not None]
    steps.sort(key=lambda row:int(row["level"]))
    future=[s for s in steps if int(s["level"])>int(at_level) and int(s["level"])<=int(target_level)]
    next_talent=next((s for s in future if s.get("talent_added")),None)
    watched=("talent_family","combat_profile","gear","pull_size","rotation","policy","aura","mana_plan")
    current=next((s for s in reversed(steps) if int(s["level"])<=int(at_level)),None) or {}
    previous={k:current.get(k) for k in watched}
    next_transition=None
    for step in future:
        changes={}
        for key in watched:
            value=step.get(key)
            if value is not None and value!=previous.get(key):
                changes[key]=value
        if step.get("talent_added"):
            changes["talent_added"]=step.get("talent_added")
        if changes:
            next_transition={"level":int(step["level"]),"allocation":step.get("allocation"),"changes":changes}
            break
        previous.update({k:step.get(k) for k in watched if step.get(k) is not None})
    return {
        "from_level":int(at_level),
        "target_level":int(target_level),
        "next_talent_pick":None if next_talent is None else {
            "level":int(next_talent["level"]),
            "talent_added":next_talent.get("talent_added"),
            "allocation":next_talent.get("allocation"),
        },
        "next_meaningful_decision":next_transition,
        "future_steps":[{
            "level":int(step["level"]),
            "talent_added":step.get("talent_added"),
            "allocation":step.get("allocation"),
            "talent_family":step.get("talent_family"),
            "combat_profile":step.get("combat_profile"),
        } for step in future],
    }


def dual_spec_continuation(dual: dict | None, *, at_level: int, target_level: int) -> dict | None:
    row=dict(dual or {})
    if row.get("status") != "available":
        return None
    unlock=int(row.get("unlock_level") or 0)
    switches=[dict(sw) for sw in row.get("switches",()) if sw.get("level") is not None]
    future=[sw for sw in switches if int(sw["level"])>int(at_level) and int(sw["level"])<=int(target_level)]
    next_switch=future[0] if future else None
    return {
        "status":"available",
        "unlock_level":unlock,
        "switch_model":str(row.get("switch_model") or "level_boundaries_only"),
        "next_switch":next_switch,
        "switch_recommendation":row.get("switch_recommendation"),
        "pair":row.get("pair"),
    }


def analyze_constraint(frontier:dict,target_level:int,raw_constraint:dict) -> dict:
    constraint=normalize_constraint(raw_constraint)
    level_row=next((row for row in frontier.get("levels",()) if int(row.get("level",-1))==int(target_level)),None)
    base={
        "schema_version":1,"ruleset":"forever","class":frontier.get("class"),
        "target_level":int(target_level),"constraint":constraint,
        "authority":"best_preserved_frontier_path",
    }
    if level_row is None:
        return {**base,"status":"not_available_in_frontier"}
    candidates=[c for c in level_row.get("candidates",()) if c.get("cumulative_objective_s") is not None]
    if not candidates:
        return {**base,"status":"no_preserved_candidates"}
    best=min(candidates,key=lambda c:float(c["cumulative_objective_s"]))
    pool=[c for c in candidates if matches(c,constraint)]
    if not pool:
        levels = [int(row.get("level")) for row in frontier.get("levels", ()) if row.get("level") is not None]
        return {
            **base,"status":"not_preserved_requires_constrained_rerun",
            "preserved_candidate_count":len(candidates),
            "note":"The bounded frontier cannot prove this route; no result was invented.",
            "rerun_commands": rerun_commands(str(frontier.get("class") or "mage"), target_level, constraint,
                                               start_level=min(levels) if levels else 10),
        }
    chosen=min(pool,key=lambda c:float(c["cumulative_objective_s"]))
    base_s=float(best["cumulative_objective_s"]); chosen_s=float(chosen["cumulative_objective_s"])
    metric=compute_regret(
        baseline_objective_s=base_s, constrained_objective_s=chosen_s,
        constrained_route="ad_hoc_constraint",
        definition={"kind":"generic_constraint","source":"listener_constraint","label":"Current constraint"},
        authority="best_preserved_frontier_path",
    )
    out={
        **base,**metric.as_dict(),"preserved_candidate_count":len(candidates),
        "matching_candidate_count":len(pool),
        "target_level_mobs_per_hour_delta":float(chosen.get("mobs_per_hour") or 0.0)-float(best.get("mobs_per_hour") or 0.0),
        "path":bounded_candidate(chosen,include_steps=True),
        "unrestricted_path":bounded_candidate(best,include_steps=False),
    }
    at_level=constraint.get("at_level")
    if at_level is not None:
        out["continuation"]=_continuation_summary(chosen,at_level=int(at_level),target_level=int(target_level))
        out["continuation_mode"]="exact_current_allocation_no_respec" if "at_level_talent_allocation_exact" in constraint else "current_constraint"
    return out


def main(argv:list[str]|None=None) -> int:
    ap=argparse.ArgumentParser(description="Query a constrained route against the preserved decision frontier")
    ap.add_argument("--class",dest="class_name",choices=class_names("forever"),required=True)
    ap.add_argument("--target",type=int,required=True)
    ap.add_argument("--constraint-json",required=True,help='JSON object, e.g. {"talent_minimums":{"seal_of_command":1}}')
    args=ap.parse_args(argv)
    frontier=read_json(frontier_path(args.class_name),{}) or {}
    result=analyze_constraint(frontier,args.target,json.loads(args.constraint_json))
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result.get("status")=="available" else 2


if __name__=="__main__":
    raise SystemExit(main())
