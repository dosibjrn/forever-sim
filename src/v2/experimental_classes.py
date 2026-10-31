from __future__ import annotations

"""Continuity-preserving search adapter for non-Mage Forever class backends.

Per-level candidate expansion/evaluation is owned by the generic search kernel.
This module now mainly preserves the existing beam-retention and publication
contracts while class-specific mechanics remain behind ClassModel/engine hooks.
The mature Mage search is migrated separately.
"""

from .class_model import CandidateResult, Evaluation, LevelFrontier, active_class_model
from .search_kernel import SearchParent, search_level
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor
import csv
import multiprocessing as mp
import time
from typing import Any

from src.engine_registry import eng
from src.class_registry import get_definition
from src import game_context
from src.objective import search_level_weight_per_100
from .runtime_state import publish, STATE_DIR
from .decision_artifacts import MILESTONE_LEVELS, bounded_candidate
from .stat_weight_model import compute_for_engine
from .runtime_progress import emit_runtime_progress


@dataclass
class _BeamRow:
    talents: Any
    cumulative_s: float
    score: dict
    path: tuple[dict,...]




def _key(t) -> tuple[int,...]:
    return tuple(int(v) for v in t.__dict__.values())


def _family(t) -> str:
    pts={tree:int(eng.tree_points(t,tree)) for tree in eng.TREE_NAMES}
    m=max(pts.values()) if pts else 0
    winners=[k for k,v in pts.items() if v==m]
    return winners[0] if len(winners)==1 else 'mixed'


def _tree_points(t) -> dict[str,int]:
    return {tree:int(eng.tree_points(t,tree)) for tree in eng.TREE_NAMES}


def _allocation(t) -> str:
    return eng.final_allocation(t)


def _mobs_per_hour(score: dict) -> float | None:
    """Return one display metric for both experimental scorer contracts.

    Paladin's pack scorer publishes ``mobs_per_hour`` directly.  The Druid
    single-target proxy publishes its canonical ``total_s`` instead, so derive
    the equivalent 100-mob rate here rather than letting the dashboard show a
    blank card next to a populated throughput curve.
    """
    value = score.get('mobs_per_hour')
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    try:
        total = float(score.get('total_s') or 0.0)
    except (TypeError, ValueError):
        total = 0.0
    return (360000.0 / total) if total > 0.0 else None


def _gear_label(score: dict) -> str | None:
    """Return only a real gear label carried by the scorer.

    Gear authority now lives in the canonical SQLite catalogue for every
    implemented Forever class.  Do not synthesize a presentation fallback
    such as ``baseline_level_curve`` when a backend forgets to publish gear;
    that would make the listener look more complete than the scorer output.
    """
    label = score.get('gear')
    if label:
        return str(label)
    gear = score.get('gear_stats')
    if isinstance(gear, dict):
        return gear.get('name') or gear.get('provenance')
    return None


def _pull_size(score: dict) -> int:
    try:
        return max(1, int(score.get('pull_size') or 1))
    except (TypeError, ValueError):
        return 1




def _stat_mix_guidance(sw:dict|None) -> list[str]:
    sw=sw or {}
    explicit=sw.get('stat_mix_guidance_rank')
    if explicit:
        return list(explicit)
    stats=sw.get('stats') or {}
    ranked=[]
    for name,row in stats.items():
        try: value=float((row or {}).get('seconds_saved_per_100_per_point',0.0) or 0.0)
        except (TypeError,ValueError): value=0.0
        if value>0: ranked.append((value,str(name)))
    ranked.sort(reverse=True)
    return [name for _,name in ranked]


def _merge_event_winner(rich: dict, event_best: dict) -> dict:
    """Overlay replay-authoritative fields without erasing rich scorer metadata."""
    out=dict(rich or {})
    protected={
        "stat_weights","stat_weights_error","stat_mix_guidance",
        "gear","gear_stats","gear_fixed_point","details",
    }
    for key,value in dict(event_best or {}).items():
        if key not in protected and value is not None:
            out[key]=value
    return out


def _candidate_json(row:_BeamRow, level:int, *, include_stat_weights:bool=True,
                    include_envelope:bool=True) -> dict:
    s=row.score
    details=dict(s)
    if include_envelope and hasattr(eng,'pull_envelope'):
        try:
            details['pull_envelope']=eng.pull_envelope(int(level),row.talents,s.get('profile','auto'))
        except Exception as exc:
            details['pull_envelope_error']=f'{type(exc).__name__}: {exc}'
    # All classes use the same stat-weight dispatcher.  A backend can expose a
    # smooth analytic gradient, a legacy finite-difference diagnostic, or no stat
    # model yet.  This stays outside beam expansion so gearing derivatives never
    # become a combinatorial search dimension.
    if include_stat_weights:
        try:
            weights = compute_for_engine(
                eng, int(level), row.talents, baseline=s,
                profile=s.get('profile','auto'),
            )
            if weights is not None:
                details['stat_weights'] = weights
        except Exception as exc:
            details['stat_weights_error']=f'{type(exc).__name__}: {exc}'
    ev=Evaluation.from_raw(s)
    timing=ev.published_fields()
    return {
        'level':int(level),
        **timing,
        'min_per_100':float(ev.score_s_per_100)/60.0,
        'allocation':_allocation(row.talents),
        'talent_ranks':{name:int(getattr(row.talents,name)) for name in row.talents.__dataclass_fields__ if int(getattr(row.talents,name))!=0},
        'family':_family(row.talents),
        'talent_family':_family(row.talents),
        'combat_profile':s.get('profile','auto'),
        'tree_points':_tree_points(row.talents),
        'policy':s.get('rotation','—'),
        'rotation':s.get('rotation','—'),
        'profile':s.get('profile','auto'),
        'gear':_gear_label(s),
        'gear_stats':s.get('gear_stats'),
        # Publish the converged fixed-point diagnostics on the listener-facing
        # row itself.  Keeping this only inside details made it too easy for
        # downstream path serializers to silently drop the actual gear loop.
        'gear_fixed_point':s.get('gear_fixed_point'),
        'pull_size':_pull_size(s),
        # Listener-facing timing contract. Experimental pack scorers publish
        # kill/recovery/travel in seconds per 100 mobs; normalize them here so
        # every per-level row renders the same human-scale breakdown as Mage.
        'stat_weights':details.get('stat_weights'),
        'stat_weights_error':details.get('stat_weights_error'),
        'stat_mix_guidance':_stat_mix_guidance(details.get('stat_weights')),
        'details':details,
        'model_fidelity':dict(getattr(eng,'MODEL_FIDELITY',{}) or {}),
        'source':'forever-experimental-fast',
    }



def _ensure_summary_best_stat_weights(summary: dict, level: int) -> dict:
    """Publication-boundary contract for experimental-class winner rows.

    Event validation and compatibility serializers may manipulate the selected
    winner after the initial rich candidate row has been built.  Before a
    completed viewer is published, guarantee that the canonical winner carries
    stat weights (or an explicit diagnostic) from the same fixed talent row.
    This is intentionally a final safety net; the normal path should already
    have populated the fields in ``_candidate_json``.
    """
    best=dict((summary or {}).get('best') or {})
    if not best:
        return summary
    if best.get('stat_weights') is not None:
        return summary
    details=dict(best.get('details') or {})
    if details.get('stat_weights') is not None:
        best['stat_weights']=details['stat_weights']
        summary['best']=best
        return summary
    # A previous serializer may have stored an error. Do not accept that as a
    # completed publication: retry from the fixed winner state below.
    best.pop('stat_weights_error', None)
    details.pop('stat_weights_error', None)
    try:
        ranks=dict(best.get('talent_ranks') or {})
        if not ranks:
            raise ValueError('winner has no talent_ranks for stat-weight rehydration')
        talents=eng.Talents(**ranks)
        profile=best.get('combat_profile') or best.get('profile') or 'all'
        score=eng.experimental_level_score(int(level),talents,profile)
        rich=_candidate_json(_BeamRow(talents,0.0,score,tuple()),int(level),include_stat_weights=True,include_envelope=False)
        if rich.get('stat_weights') is not None:
            best['stat_weights']=rich['stat_weights']
            best['stat_mix_guidance']=rich.get('stat_mix_guidance')
            best.setdefault('gear_fixed_point',rich.get('gear_fixed_point'))
            details=dict(best.get('details') or {})
            details['stat_weights']=rich['stat_weights']
            best['details']=details
        else:
            raise RuntimeError(rich.get('stat_weights_error') or 'stat-weight rehydration returned no weights')
    except Exception as exc:
        raise RuntimeError(f'publication stat-weight contract failed at L{int(level)}: {type(exc).__name__}: {exc}') from exc
    if not best.get('stat_weights'):
        raise RuntimeError(f'publication stat-weight contract failed at L{int(level)}: empty weights')
    summary['best']=best
    return summary

def _frontier_candidate(row:_BeamRow, level:int, *, include_steps:bool=False) -> dict:
    """Compact preserved path candidate for endpoint/regret analysis."""
    score=row.score
    candidate={
        'level':int(level),
        'allocation':_allocation(row.talents),
        'talent_ranks':{name:int(getattr(row.talents,name)) for name in row.talents.__dataclass_fields__ if int(getattr(row.talents,name))!=0},
        'tree_points':_tree_points(row.talents),
        'talent_family':_family(row.talents),
        'combat_profile':score.get('profile','auto'),
        'gear':_gear_label(score),'gear_stats':score.get('gear_stats'),
        'pull_size':_pull_size(score),'policy':score.get('policy'),
        'rotation':score.get('rotation'),'aura':score.get('aura'),
        'mana_plan':score.get('mana_plan'),'mobs_per_hour':_mobs_per_hour(score),
        'score_s_per_100':float(score['total_s']),
        'seconds_per_mob':float(score['total_s'])/100.0,
        'kill_seconds_per_mob':float(score.get('kill_s',0.0) or 0.0)/100.0,
        'recovery_seconds_per_mob':float(score.get('recovery_s',0.0) or 0.0)/100.0,
        'travel_seconds_per_mob':float(score.get('travel_s',0.0) or 0.0)/100.0,
        'cumulative_objective_s':float(row.cumulative_s),
        'source':'forever-experimental-fast-preserved-frontier',
        'model_fidelity':dict(getattr(eng,'MODEL_FIDELITY',{}) or {}),
    }
    if include_steps:
        candidate['steps']=list(row.path)
    return bounded_candidate(candidate,include_steps=include_steps)


def _write_level_decisions_csv(summaries:list[dict]) -> str|None:
    """Publish the playable per-level decisions for experimental classes.

    The best current-level candidate is intentionally separate from the final
    no-respec path: this table answers "what works at this level?" and exposes
    the assumed gear plus local stat direction used for gearing decisions.
    """
    rows=[]
    stat_names=("strength","stamina","intellect","spirit","mp5","spell_power","spell_damage","healing",
                "weapon_dps","armor","shield_armor","block_value")
    gear_names=("strength_bonus","stamina_bonus","intellect_bonus","spirit_bonus","mp5_bonus",
                "spell_damage_bonus","healing_bonus","weapon_dps","weapon_speed",
                "item_armor","shield_armor","shield_block_value")
    for summary in summaries:
        best=summary.get("best") or {}
        if not best: continue
        details=best.get("details") or {}
        gear=best.get("gear_stats") or details.get("gear_stats") or {}
        sw=best.get("stat_weights") or details.get("stat_weights") or {}
        weights=sw.get("weights") or sw.get("stats") or {}
        sens=sw.get("curve_sensitivity") or {}
        row={
            "level":summary.get("level"),"allocation":best.get("allocation"),
            "family":best.get("family"),"talent_family":best.get("talent_family",best.get("family")),
            "profile":best.get("profile"),"combat_profile":best.get("combat_profile",best.get("profile")),
            "gear":best.get("gear"),"weapon_style":gear.get("weapon_style"),
            "pull_size":best.get("pull_size"),"mobs_per_hour":best.get("mobs_per_hour"),
            "seconds_per_mob":best.get("seconds_per_mob"),
            "kill_seconds_per_mob":best.get("kill_seconds_per_mob"),
            "recovery_seconds_per_mob":best.get("recovery_seconds_per_mob"),
            "travel_seconds_per_mob":best.get("travel_seconds_per_mob"),
            "policy":details.get("policy"),"aura":details.get("aura"),
            "mob_raw_dps_per_mob":details.get("mob_raw_dps_per_mob"),
            "mob_landed_swings_per_s":details.get("mob_landed_swings_per_s"),
            "mob_weighted_swing_s":details.get("mob_weighted_swing_s"),
            "stat_mix_guidance":">".join(best.get("stat_mix_guidance") or []),
        }
        for name in gear_names:
            row[f"gear_{name}"]=gear.get(name)
        for name in stat_names:
            w=weights.get(name) or {}
            c=sens.get(name) or {}
            row[f"weight_{name}_mph_per_unit"]=w.get("per_unit_mobs_per_hour")
            row[f"weight_{name}_seconds_saved_per_100_per_point"]=w.get("seconds_saved_per_100_per_point")
            row[f"sensitivity_{name}_pct"]=c.get("relative_percent")
        rows.append(row)
    if not rows: return None
    path=STATE_DIR/'level_decisions.csv'
    path.parent.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0])
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    return str(path)


def _select_diverse(rows:list[_BeamRow], width:int, family_keep:int=2) -> list[_BeamRow]:
    if not rows: return []
    width=max(1,int(width)); family_keep=max(1,int(family_keep))
    cumulative=sorted(rows,key=lambda r:(r.cumulative_s,float(r.score['total_s']),eng.talent_preference_key(r.talents),_key(r.talents)))
    current=sorted(rows,key=lambda r:(float(r.score['total_s']),r.cumulative_s,eng.talent_preference_key(r.talents),_key(r.talents)))
    keep=[]; seen=set()

    def add(pool, limit):
        n=0
        for r in pool:
            k=_key(r.talents)
            if k in seen: continue
            keep.append(r); seen.add(k); n+=1
            if n>=limit: break

    # 1) Deep commitment corridors first.  A route may need to be intentionally
    # mediocre for several levels before a tier unlock makes it competitive.
    for tree in eng.TREE_NAMES:
        deepest=max((eng.tree_points(r.talents,tree) for r in rows),default=0)
        lane=[r for r in current if eng.tree_points(r.talents,tree)==deepest]
        add(lane,family_keep)

    # 2) Current-level leaders keep sudden crossovers visible.
    for fam in (*eng.TREE_NAMES,'mixed'):
        add([r for r in current if _family(r.talents)==fam],family_keep)

    # 3) Registry-declared endpoint corridors. Some routes are defined by a
    # specific unlock rather than merely deepest tree points (Paladin Protection
    # improved_seal_of_fury / Retribution seal_of_command). Preserve those
    # candidates intentionally so named routes cannot vanish just because a
    # bounded performance beam considered them temporarily mediocre.
    definitions=dict(get_definition("forever", str(eng.CLASS_NAME)).route_definitions or {})
    for _route, definition in definitions.items():
        kind=str(definition.get("kind") or "")
        minimum=int(definition.get("minimum",1) or 1)
        if kind == "talent":
            talent=str(definition.get("talent") or "")
            lane=[r for r in current if int(getattr(r.talents,talent,0) or 0) >= minimum]
        elif kind == "tree_points":
            tree=str(definition.get("tree") or "")
            lane=[r for r in current if int(eng.tree_points(r.talents,tree)) >= minimum]
        else:
            lane=[]
        add(lane,family_keep)

    # 4) Cumulative leaders preserve the actual no-respec leveling objective.
    for fam in (*eng.TREE_NAMES,'mixed'):
        add([r for r in cumulative if _family(r.talents)==fam],family_keep)

    # 5) Fill the remaining global beam by cumulative objective.
    target=max(width,3*family_keep*len(eng.TREE_NAMES))
    add(cumulative,target)
    return keep[:target]


def _publish_spec_matrices(start:int, end:int, args) -> tuple[str|None,int,str|None]:
    """Publish route-specific stat matrices for normal experimental runs.

    Current-level beam leaders already carry stat weights, but the Decisions
    listener renders preserved endpoint routes.  Those are different objects,
    so a normal Paladin/Druid run must also publish the fixed-route matrix or
    the focused route legitimately has no weights to display.
    """
    if not bool(getattr(args,'stat_weights',True)):
        return None,0,None
    try:
        from .spec_matrix import generate_all
        targets=[level for level in MILESTONE_LEVELS if int(start) <= int(level) <= int(end)]
        if not targets:
            targets=[int(end)]
        matrix_file,matrix=generate_all(str(eng.CLASS_NAME),targets)
        return str(matrix_file),len(matrix.get('matrices',{})),None
    except Exception as exc:
        return None,0,f'{type(exc).__name__}: {exc}'


def _per_level_best_path(summaries:list[dict], *, respec_seconds:float=1.0) -> dict:
    """Build the fresh-respec-each-level comparison from searched leaders."""
    from src.objective import level_weight_per_100
    steps=[]; objective_s=0.0; respec_levels=[]; previous=None
    for summary in summaries:
        # summary['best'] is the canonical rich winner.  Event validation may
        # also leave the raw event row in event_validated_best for diagnostics,
        # but during enrichment we deliberately replace best with a row that
        # carries the same winner identity plus converged gear/stat-weight data.
        # Prefer that rich row or the per-level path can regress to stale/minimal
        # gear metadata even though the optimizer itself produced the new result.
        best=dict(summary.get('best') or summary.get('event_validated_best') or {})
        if not best:
            continue
        level=int(summary['level']); allocation=best.get('allocation')
        changed=previous is not None and allocation != previous
        if changed:
            objective_s += float(respec_seconds); respec_levels.append(level)
        objective_s += float(level_weight_per_100(level))*float(best['score_s_per_100'])
        best.update({'level':level,'kind':'respec' if changed else ('start' if previous is None else 'point_or_same'),
                     'respec_seconds':float(respec_seconds) if changed else 0.0})
        steps.append(best); previous=allocation
    return {
        'mode':'per_level_best','label':'Per-level best spec',
        'hours':objective_s/3600.0,'respec_seconds':float(respec_seconds),
        'respecs_used':len(respec_levels),'respec_levels':respec_levels,
        'resolved_through_level':int(steps[-1]['level']) if steps else 0,'steps':steps,
        'final_allocation':steps[-1].get('allocation','') if steps else '',
        'final_policy':steps[-1].get('rotation') or steps[-1].get('policy','') if steps else '',
        'authority':'best searched current-level candidate; independent across levels',
        'bounded':True,
    }


def run(args, *, model=None) -> dict:
    start=max(10,int(args.start_level)); end=int(args.end_level)
    profile=str(getattr(args,'school','all') or 'all').lower()
    if profile in ('frost','fire','arcane'): profile='all'
    model = model or active_class_model()
    base=eng.Talents()
    beam=[_BeamRow(base,0.0,eng.experimental_level_score(10,base,profile),tuple())]
    summaries=[]
    frontier_levels=[]
    canonical_frontiers=[]
    started=time.time()
    snap={
        'version':1,
        'engine':'v2-forever-experimental-class',
        'game':game_context.describe(),
        'running':True,
        'started_at':started,
        'phase':'searching',
        'message':f'Experimental {eng.CLASS_NAME} continuity search',
        'config':{
            'start_level':start,'end_level':end,'beam_width':int(args.beam_width),'family_keep':int(args.family_keep),
            'workers':max(1,int(args.workers)),'parallelism':'candidate_pool','max_respecs':0,'requested_max_respecs':int(args.max_respecs),
            'profile':profile,'ruleset':eng.RULESET,'class':eng.CLASS_NAME,
        },
        'capabilities':{
            'fast':bool(eng.FAST_SUPPORTED),'mc':bool(eng.MC_SUPPORTED),
            'respec_path_search':False,'per_level_best_respec_mode':True,'respec_seconds':1.0,'experimental':True,
            'verified_level_cap':int(eng.VERIFIED_LEVEL_CAP),
            'model_fidelity':dict(getattr(eng,'MODEL_FIDELITY',{}) or {}),
        },
        'data':(eng.DATA_PROVENANCE.as_dict() if hasattr(eng,'DATA_PROVENANCE') else {'build':eng.DATA_BUILD,'attribution':eng.DATA_ATTRIBUTION}),
        'views':{},
    }
    publish(snap)

    emit_runtime_progress(
        force=True, phase="searching", stage="starting", started_at=started,
        levels_done=0, levels_total=max(1,end-start+1), level=start,
        message=f"Starting {eng.CLASS_NAME} L{start}→{end}",
    )

    # Talent point 1 arrives at level 10. Build all continuity states from there
    # even if the user requests output starting at a later level. Enumerate each
    # level's unique children before scoring so runtime progress has an exact
    # candidate denominator without changing first-parent-wins search semantics.
    #
    # Experimental classes depend on the previous level's beam, so parallelizing
    # levels would be false concurrency. Instead reuse one spawn-safe process pool
    # for the independent candidates *inside* each level. Never nest pools.
    worker_count=max(1,int(getattr(args,'workers',1) or 1))
    executor=(ProcessPoolExecutor(max_workers=worker_count, mp_context=mp.get_context('spawn'))
              if worker_count>1 else None)
    try:
      for level in range(10,end+1):
        levels_done=max(0,min(end-start+1, level-start))

        def on_search_progress(current:int,total:int):
            if total <= 0:
                return
            stage="candidate_pool" if executor is not None and total>1 else "candidate"
            emit_runtime_progress(
                force=(current in (0,total)), phase="searching", stage=stage, started_at=started,
                levels_done=levels_done, levels_total=max(1,end-start+1), level=level,
                candidate_current=current, candidate_total=total,
                message=f"L{level} · {current}/{total} candidates · workers {worker_count}",
            )

        level_search=search_level(
            model, level,
            [SearchParent(r.talents,r.cumulative_s,r) for r in beam],
            level_weight=max(.01,float(search_level_weight_per_100(level))),
            metadata={"profile":profile},
            executor=executor, derive_stat_weights=False, progress=on_search_progress,
        )
        generated={}
        for found in level_search.candidates:
            parent=found.parent.payload
            child=found.result.build
            name=found.transition_label
            score=dict(found.result.evaluation.diagnostics or {})
            step={'level':level,'talent_added':name,'allocation':_allocation(child),
                  'talent_ranks':{n:int(getattr(child,n)) for n in child.__dataclass_fields__ if int(getattr(child,n))!=0},
                  'tree_points':_tree_points(child),'talent_family':_family(child),
                  'profile':score.get('profile'),'combat_profile':score.get('profile'),
                  'policy':score.get('policy'),'rotation':score.get('rotation'),
                  'aura':score.get('aura'),'mana_plan':score.get('mana_plan'),
                  'score_s_per_100':float(found.result.evaluation.score_s_per_100),
                  'gear':_gear_label(score),'gear_stats':score.get('gear_stats'),
                  'pull_size':_pull_size(score),'mobs_per_hour':_mobs_per_hour(score)}
            generated[model.build_key(child)]=_BeamRow(
                child,float(found.cumulative_s),score,parent.path+(step,)
            )
        if not generated:
            raise RuntimeError(f'no legal experimental talent states at level {level}')
        beam=_select_diverse(list(generated.values()),int(args.beam_width),int(args.family_keep))
        if level>=start:
            # Canonical retained frontier: route solving consumes the complete
            # retained beam, not the smaller JSON/presentation frontier below.
            canonical_frontiers.append(LevelFrontier(
                int(level),
                tuple(CandidateResult(
                    level=int(level), build=r.talents, loadout=r.score.get('gear_stats'),
                    policy=r.score.get('rotation') or r.score.get('policy'),
                    evaluation=Evaluation.from_raw(r.score),
                    metadata={
                        'source':'forever-generic-search-retained',
                        'publication_row':_frontier_candidate(r,level,include_steps=False),
                    },
                ) for r in beam),
            ))
            leaders=sorted(beam,key=lambda r:(float(r.score['total_s']),r.cumulative_s))
            visible_k=max(3,int(args.final_k))
            stat_weights_enabled=bool(getattr(args,'stat_weights',True))
            requested_sw_top_k=int(getattr(args,'stat_weight_top_k',0) or 0)
            sw_top_k=(visible_k if requested_sw_top_k <= 0 else min(visible_k, requested_sw_top_k)) if stat_weights_enabled else 0
            cand=[_candidate_json(r,level,include_stat_weights=(i < sw_top_k))
                  for i,r in enumerate(leaders[:visible_k])]
            validation_k=max(0,int(getattr(eng,'VALIDATION_CANDIDATE_K',0) or 0))
            validation_candidates=[]
            if validation_k:
                validation_candidates=[
                    _candidate_json(r,level,include_stat_weights=False,include_envelope=False)
                    for r in leaders[:max(visible_k,validation_k)]
                ]
            summary={'level':level,'candidates':cand,'best':cand[0] if cand else None,
                     'fast_best':cand[0] if cand else None,'pool_size':len(beam)}
            if validation_candidates:
                summary['validation_candidates']=validation_candidates
                summary['validation_candidate_k']=len(validation_candidates)
            if validation_candidates and hasattr(eng,'event_validate_candidates'):
                try:
                    replay_candidates=validation_candidates
                    if level==end and hasattr(eng,'expand_event_validation_candidates'):
                        replay_candidates=eng.expand_event_validation_candidates(level,validation_candidates)
                        summary['event_validation_expanded_candidate_k']=len(replay_candidates)
                        summary['event_validation_scope']='target_end_level'
                    validation_summary=eng.event_validate_candidates(level,replay_candidates)
                    summary.update(validation_summary)
                    # For classes with a deterministic finalist validator, the
                    # published per-level decision is the reranked winner. Keep
                    # the smooth leader separately as fast_best for diagnostics.
                    event_best=validation_summary.get('event_validated_best')
                    if event_best:
                        # Rehydrate the event winner through the normal rich row
                        # builder so the published decision keeps named gear and
                        # stat-weight contracts. Overlay event timing/throughput
                        # afterwards; never publish the smooth row under an event
                        # winner's allocation.
                        published=dict(event_best)
                        try:
                            winner_t=eng.Talents(**dict(event_best.get('talent_ranks') or {}))
                            winner_score=eng.experimental_level_score(level,winner_t,event_best.get('combat_profile','all'))
                            rich=_candidate_json(_BeamRow(winner_t,0.0,winner_score,tuple()),level,include_stat_weights=True)
                            # Replay decides winner identity and event timing, but the
                            # rich scorer owns gearing/stat-weight metadata. Legacy
                            # replay rows contain explicit None placeholders for fields
                            # they never computed; blindly update() used to erase real
                            # Paladin stat weights here. Overlay only event-authoritative
                            # non-null fields and never replace the rich gear contract.
                            published=_merge_event_winner(rich,event_best)
                        except Exception as enrich_exc:
                            published['event_enrichment_error']=f'{type(enrich_exc).__name__}: {enrich_exc}'
                        summary['best']=published
                        summary['selection_authority']='deterministic_event_reranked_expanded_finalists'
                except Exception as exc:
                    summary['event_validation_error']=f'{type(exc).__name__}: {exc}'
            summary=_ensure_summary_best_stat_weights(summary,level)
            summaries.append(summary)
            frontier_pool=sorted(beam,key=lambda r:(r.cumulative_s,float(r.score['total_s']),_key(r.talents)))
            frontier_k=max(24,visible_k,validation_k)
            include_steps=level in MILESTONE_LEVELS or level==end
            frontier_levels.append({
                'level':level,
                'candidate_count':min(len(frontier_pool),frontier_k),
                'beam_pool_size':len(beam),
                'candidates':[_frontier_candidate(r,level,include_steps=include_steps) for r in frontier_pool[:frontier_k]],
            })
            emit_runtime_progress(
                force=True, phase="searching", stage="level_complete", started_at=started,
                levels_done=len(summaries), levels_total=max(1,end-start+1), level=level,
                progress={"mode":"determinate","current":len(summaries),"total":max(1,end-start+1),
                          "fraction":min(1.0,len(summaries)/max(1,end-start+1)),"unit":"levels"},
                message=f"Level {level} complete · {len(summaries)}/{max(1,end-start+1)} levels",
            )
            if level==start or level==end or level%5==0:
                snap['views']['experimental']={'status':'searching','levels_done':len(summaries),
                    'levels_total':end-start+1,'current_level':level,'level_summaries':summaries,
                    'message':f'Level {level} complete'}
                publish(snap)

    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    decision_csv=_write_level_decisions_csv(summaries)
    frontier={
        'schema_version':1,'ruleset':eng.RULESET,'class':eng.CLASS_NAME,
        'start_level':start,'end_level':end,
        'verified_level_cap':int(eng.VERIFIED_LEVEL_CAP),
        'bounded':True,'candidate_limit':max(24,int(args.final_k),int(getattr(eng,'VALIDATION_CANDIDATE_K',0) or 0)),
        'objective':'cumulative weighted leveling seconds',
        'model_fidelity':dict(getattr(eng,'MODEL_FIDELITY',{}) or {}),
        'levels':frontier_levels,
    }
    from .decision_pipeline import publish_decisions
    route_targets=sorted(set(
        [int(level) for level in MILESTONE_LEVELS if int(start) <= int(level) <= int(end)] + [int(end)]
    ))
    decisions=publish_decisions(
        class_name=str(eng.CLASS_NAME), canonical_frontiers=canonical_frontiers, model=model,
        presentation_frontier=frontier, verified_level_cap=int(eng.VERIFIED_LEVEL_CAP),
        targets=route_targets, target_level=end,
        dual_spec_unlock_level=int(getattr(args,'dual_spec_unlock_level',40)),
        unconstrained_max_respecs=0, constrained_max_respecs=0,
    )
    frontier_file=decisions['decision_frontier_json']
    endpoint_file=decisions['endpoint_paths_json']
    regret_file=decisions['spec_regret_json']
    dual_file=decisions['dual_spec_json']
    matrix_file,matrix_count,matrix_error=_publish_spec_matrices(start,end,args)
    best=min(beam,key=lambda r:r.cumulative_s)
    visible_steps=[s for s in best.path if int(s['level'])>=start]
    path={
        'hours':float(best.cumulative_s)/3600.0,
        'respecs_used':0,
        'respec_levels':[],
        'resolved_through_level':end,
        'steps':visible_steps,
        'final_allocation':_allocation(best.talents),
        'final_policy':best.score.get('rotation','—'),
        'experimental':True,
    }
    per_level_best=_per_level_best_path(summaries,respec_seconds=1.0)
    snap['views']['experimental']={'status':'complete','level_summaries':summaries,
        'paths':{'0':path,'per_level_best':per_level_best},'best_path':path,
        'per_level_best_path':per_level_best,'decision_report_csv':decision_csv,
        'decision_frontier_json':str(frontier_file),'endpoint_paths_json':str(endpoint_file),
        'decision_authority':decisions['decision_authority'],
        'spec_regret_json':str(regret_file),'dual_spec_json':str(dual_file),
        'spec_matrix_json':matrix_file,
        'spec_matrix_count':matrix_count,'spec_matrix_error':matrix_error,
        'message':'Experimental no-respec Fast path complete'}
    snap.setdefault('capabilities',{}).update({
        'decision_artifacts':True,
        'endpoint_paths':True,
        'stat_matrix':bool(matrix_count),
    })
    snap['best_analytic']={'view':'experimental',**path}
    snap['running']=False; snap['phase']='complete'
    snap['message']=f'Forever {eng.CLASS_NAME} experimental Fast search complete; MC disabled.'
    snap['total_seconds']=time.time()-started
    emit_runtime_progress(
        force=True, phase="complete", stage="complete", started_at=started,
        levels_done=max(1,end-start+1), levels_total=max(1,end-start+1), level=end,
        progress={"mode":"determinate","current":max(1,end-start+1),"total":max(1,end-start+1),
                  "fraction":1.0,"unit":"levels"},
        message=snap['message'],
    )
    publish(snap)
    return snap
