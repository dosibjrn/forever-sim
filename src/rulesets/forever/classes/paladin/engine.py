from __future__ import annotations

"""Forever Paladin compatibility facade.

The package owns separate profile/talent/spell/mechanics modules; the engine
facade preserves the module-shaped API expected by the optimizer registry.
"""

from src.rulesets.forever.shared import VERIFIED_LEVEL_CAP
from .profile import (
    RULESET, CLASS_NAME, ENGINE_KIND, FAST_SUPPORTED, MC_SUPPORTED, EXPERIMENTAL,
    DATA_PROVENANCE, DATA_BUILD, DATA_ATTRIBUTION, DATA_QUALITY, MODEL_FIDELITY,
    VALIDATION_CANDIDATE_K,
    TREE_NAMES, PRIMARY_SCHOOL_ENV, PRIMARY_SCHOOLS, normalize_primary_school,
)
from .talents import (
    Talents, TALENT_RULES, tree_points, legal_add, add_point,
    final_allocation, talent_preference_key,
)
from .spells import (
    HOLY_STRIKE, SEAL_FURY, SEAL_RIGHTEOUSNESS, SEAL_COMMAND, CONSECRATION, HOLY_LIGHT, FLASH_OF_LIGHT,
    HAMMER_OF_JUSTICE, BLESSING_OF_PROTECTION, DIVINE_PROTECTION, RETRIBUTION_AURA, DEVOTION_AURA, latest,
)
from .gear import GearSetup, archetypes, gear_snapshot
from .policy import PriorityPolicy, ManaPlan, POLICIES, MANA_PLANS
from .mechanics import experimental_level_score, smooth_pack_score, pull_envelope, marginal_stat_weights, analytic_stat_gradient, item_budget_units
from .event_replay import replay_pack, validate_smooth_row



def _reachable_talents(ranks):
    """Rebuild a legal Paladin allocation from sparse ranks deterministically."""
    want={str(k):int(v) for k,v in dict(ranks or {}).items() if int(v)>0}
    t=Talents()
    for _ in range(sum(want.values())):
        choices=[name for name in sorted(want)
                 if int(getattr(t,name,0))<want[name] and legal_add(t,name)]
        if not choices:
            return None
        t=add_point(t,choices[0])
    got={name:int(getattr(t,name)) for name in t.__dataclass_fields__ if int(getattr(t,name))>0}
    return t if got==want else None


def _one_point_swap_neighbors(t, cap=120):
    """Deterministic legal one-point reallocations around one allocation."""
    base={name:int(getattr(t,name)) for name in t.__dataclass_fields__ if int(getattr(t,name))>0}
    out={}
    dominant=max(TREE_NAMES,key=lambda tree:tree_points(t,tree))
    for drop in sorted(base):
        partial=dict(base); partial[drop]-=1
        if partial[drop]<=0: partial.pop(drop,None)
        for add in sorted(TALENT_RULES):
            if partial.get(add,0)>=int(TALENT_RULES[add][1]):
                continue
            cand=dict(partial); cand[add]=cand.get(add,0)+1
            ct=_reachable_talents(cand)
            if ct is None or ct==t:
                continue
            key=tuple(int(v) for v in ct.__dict__.values())
            out[key]=ct
    rows=list(out.values())
    rows.sort(key=lambda q:(-tree_points(q,dominant),tuple(int(v) for v in q.__dict__.values())))
    return rows[:max(0,int(cap))]


def _validation_candidate(level, t, source):
    score=experimental_level_score(int(level),t,'all')
    return {
        'level':int(level),
        'score_s_per_100':float(score['total_s']),
        'allocation':final_allocation(t),
        'talent_ranks':{name:int(getattr(t,name)) for name in t.__dataclass_fields__ if int(getattr(t,name))>0},
        'combat_profile':score.get('profile','auto'),
        'profile':score.get('profile','auto'),
        'gear':score.get('gear'),
        'gear_stats':score.get('gear_stats'),
        'pull_size':int(score.get('pull_size') or 1),
        'rotation':score.get('rotation'),
        'policy':score.get('rotation'),
        'mobs_per_hour':float(score.get('mobs_per_hour') or 0.0),
        'details':dict(score),
        'source':source,
    }


def expand_event_validation_candidates(level, candidates, *, neighbor_cap=120, total_cap=24, rounds=2, frontier_width=8, seed_width=1):
    """Preserve event-relevant local challengers before deterministic reranking.

    Fast search remains the structural authority.  Starting from its preserved
    leaders, walk a small deterministic legal one-point-swap neighborhood for
    two rounds.  The second round matters at L20: the event-stable Ret winner
    can be two reallocations away from the smooth leader.  Only a bounded smooth
    frontier is expanded and returned, keeping replay cost deterministic.
    """
    pool={}
    scored={}

    def key_of(t):
        return tuple(int(v) for v in t.__dict__.values())

    def add_candidate(candidate):
        t=_reachable_talents(candidate.get('talent_ranks') or {})
        if t is None:
            return None
        k=key_of(t)
        pool.setdefault(k,dict(candidate))
        return t

    if int(level) not in (20,40,60):
        return list(candidates)

    seeds=[]
    for candidate in list(candidates)[:max(1,int(seed_width))]:
        t=add_candidate(candidate)
        if t is not None:
            seeds.append(t)

    # L20 needs two rounds to retain the event-stable challenger found by
    # M47. The falsifying L40 and L60 challengers are already one legal swap
    # away from their smooth winners; a second 8x120 expansion adds large
    # runtime without changing the retained finalist set. Keep target-level
    # replay bounded per validated cell instead of paying the deepest known
    # search everywhere.
    effective_rounds=max(0,int(rounds))
    if int(level) in (40,60):
        effective_rounds=min(effective_rounds,1)

    frontier=list(seeds)
    for rnd in range(effective_rounds):
        for seed in frontier:
            for t in _one_point_swap_neighbors(seed,neighbor_cap):
                k=key_of(t)
                if k not in pool:
                    pool[k]=_validation_candidate(level,t,f'forever-paladin-expanded-one-swap-r{rnd+1}')
        ranked=[]
        for k,candidate in pool.items():
            try:
                score=float(candidate.get('score_s_per_100') or candidate.get('details',{}).get('total_s') or 1e18)
            except (TypeError,ValueError):
                score=1e18
            ranked.append((score,str(candidate.get('allocation') or ''),k,candidate))
        ranked.sort(key=lambda x:(x[0],x[1],x[2]))
        frontier=[]
        for _,_,k,candidate in ranked[:max(1,int(frontier_width))]:
            t=_reachable_talents(candidate.get('talent_ranks') or {})
            if t is not None:
                frontier.append(t)

    rows=list(pool.values())
    rows.sort(key=lambda r:(float(r.get('score_s_per_100') or r.get('details',{}).get('total_s') or 1e18),str(r.get('allocation') or '')))
    return rows[:max(len(candidates),int(total_cap))]

def event_validate_candidates(level, candidates):
    """Re-rank preserved Fast finalists without replacing Fast path authority."""
    from .validation_report import validate_candidate

    validated=[]
    for smooth_rank,candidate in enumerate(candidates,1):
        ranks=dict(candidate.get("talent_ranks") or {})
        details=dict(candidate.get("details") or {})
        if not ranks or not details:
            continue
        result=validate_candidate(int(level),Talents(**ranks),details)
        validated.append((smooth_rank,candidate,result))
    if not validated:
        return {
            "event_validated_best":None,
            "decision_change_kind":"unavailable",
            "event_validation_authority":"deterministic_finalist_validator_only",
        }
    event_ranked=sorted(validated,key=lambda item:(-float(item[2].get("event_adjusted_mobs_per_hour",0.0)),item[0]))
    smooth_rank,candidate,result=event_ranked[0]
    event_best=dict(candidate)
    mph=float(result.get("event_adjusted_mobs_per_hour",0.0))
    event_score=(360000.0/mph if mph>0 else 1e9)
    event_best.update({
        "mobs_per_hour":mph,
        "score_s_per_100":event_score,
        "seconds_per_mob":(event_score/100.0 if mph>0 else None),
        "event_validation":result,
        "smooth_rank":smooth_rank,
        "source":"forever-paladin-deterministic-event-finalist",
        "authority":"hybrid_event_validation_proxy_only",
    })
    # Do not leave smooth timing attached to an event-adjusted throughput row.
    # Validation reports pack seconds; normalize by pull size and fold any
    # cooldown-floor wait into recovery so displayed components reconcile to
    # event cycle time exactly.  Lightweight test stubs may omit these fields.
    try:
        n=max(1,int(result.get("pull_size") or candidate.get("pull_size") or 1))
        combat=float(result["event_combat_s"]); travel=float(result.get("event_travel_s",0.0) or 0.0)
        cycle=float(result["event_cycle_s"])
        if all(x < float("inf") for x in (combat,travel,cycle)):
            recovery=max(0.0,cycle-combat-travel)
            event_best.update({
                "kill_seconds_per_mob":combat/n,
                "recovery_seconds_per_mob":recovery/n,
                "travel_seconds_per_mob":travel/n,
                "seconds_per_mob":cycle/n,
            })
    except (KeyError,TypeError,ValueError,OverflowError):
        pass
    smooth_top=validated[0][1]
    material_keys=("gear","pull_size","combat_profile")
    material_changes=[key for key in material_keys if smooth_top.get(key)!=candidate.get(key)]
    smooth_details=smooth_top.get("details") or {}
    event_details=candidate.get("details") or {}
    for key in ("policy","aura","mana_plan"):
        if smooth_details.get(key)!=event_details.get(key):
            material_changes.append(key)
    talent_changed=smooth_top.get("allocation")!=candidate.get("allocation")
    if material_changes:
        change_kind="playstyle"
    elif talent_changed or smooth_rank!=1:
        change_kind="talent_only"
    else:
        change_kind="none"
    return {
        "event_validated_best":event_best,
        "decision_change_kind":change_kind,
        "material_fields_changed":material_changes,
        "event_validation_candidate_count":len(validated),
        "event_validation_authority":"deterministic_finalist_validator_only",
    }

__all__ = [name for name in globals() if not name.startswith("_")]
