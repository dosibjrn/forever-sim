from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from src.engine_registry import eng
from src import game_context
from src.class_registry import class_names, get_definition
from src.forever_build import configure as configure_forever_build, metadata as forever_build_metadata
from .analytic_frontier import AnalyticView, default_views
from .analytic_scorer import AnalyticOptions
from .continuity import close_pools_backward
from .local_search import search_level_analytic
from .path_dp import solve_path_dp
from .runtime_state import publish, read_snapshot, STATE_DIR
from . import mc_bridge
from . import view_models
from . import stat_weights
from .class_model import ClassModel, Evaluation, active_class_model


def _node_json(n) -> dict:
    return view_models.node_json(n)


def _path_json(path) -> dict:
    return view_models.path_json(path)



def _per_level_best_path(pools, cfg=None, *, start_level:int, end_level:int, respec_seconds:float=1.0, model: ClassModel) -> dict:
    """Best searched allocation independently at each level.

    This is intentionally a separate comparison mode from the continuity DP.
    It models the current target-server behavior where a respec costs ~1 s, so
    changing allocation between adjacent levels is effectively free but still
    accounted for explicitly.
    """
    from src.objective import level_weight_per_100
    steps=[]; objective_s=0.0; respec_levels=[]; previous_allocation=None
    for level in range(int(start_level), int(end_level)+1):
        rows=list(pools.get(level) or ())
        if not rows:
            continue
        node, overrides = model.adjudicate_per_level_candidate(int(level), rows, cfg)
        row=_node_json(node)
        if overrides:
            row.update({k:v for k,v in dict(overrides).items() if v is not None})
            row.update(Evaluation.from_published_row(row).published_fields())
        allocation=row.get('allocation')
        changed=previous_allocation is not None and allocation != previous_allocation
        if changed:
            objective_s += float(respec_seconds)
            respec_levels.append(int(level))
        objective_s += float(level_weight_per_100(level))*float(row.get('score_s_per_100',node.score_s_per_100))
        row.update({'kind':'respec' if changed else ('start' if previous_allocation is None else 'point_or_same'),
                    'respec_seconds':float(respec_seconds) if changed else 0.0})
        steps.append(row); previous_allocation=allocation
    return {
        'mode':'per_level_best', 'label':'Per-level best spec',
        'hours':objective_s/3600.0, 'respec_seconds':float(respec_seconds),
        'respecs_used':len(respec_levels), 'respec_levels':respec_levels,
        'resolved_through_level':int(steps[-1]['level']) if steps else int(start_level)-1,
        'steps':steps,
        'final_allocation':steps[-1].get('allocation','') if steps else '',
        'final_policy':steps[-1].get('policy','') if steps else '',
        'authority':'best searched current-level candidate; independent across levels',
    }



def _search_worker(args):
    do_stat_weights=False; stat_weight_top_k=0
    if len(args)==6:
        level,cfg,options,beam_width,family_keep,final_k = args; school='all'
    elif len(args)==7:
        level,cfg,options,beam_width,family_keep,final_k,school = args
    else:
        level,cfg,options,beam_width,family_keep,final_k,school,do_stat_weights,stat_weight_top_k = args

    if getattr(eng, 'RULESET', None) == 'forever':
        # Forever orchestration is selected by ClassModel capability, never by
        # a class-name branch in the top-level runner. The analytic-view strategy
        # currently belongs to Mage while its mature continuity repair remains.
        model=active_class_model()
        if model.runner_strategy() != 'analytic_views':
            raise RuntimeError(f"{model.name}: analytic worker used for {model.runner_strategy()} strategy")
        from .search_kernel import search_level
        prepare=getattr(model,'prepare_level_candidates',None)
        to_level_node=getattr(model,'to_level_node',None)
        if not callable(prepare) or not callable(to_level_node):
            raise RuntimeError(f"{model.name}: analytic_views strategy lacks mature candidate adapter hooks")
        builds=prepare(
            level,cfg,options=options,beam_width=beam_width,
            family_keep=family_keep,final_k=final_k,school=school,
        )
        searched=search_level(
            model,int(level),(),candidate_builds=builds,
            metadata={'school':school,'profile':school},derive_stat_weights=False,
        )
        rows=[to_level_node(found.result) for found in searched.candidates]
        rows.sort(key=lambda n:(float(n.score_s_per_100),model.build_preference_key(n.talents),n.key))
    else:
        # Classic Mage deliberately remains on the historical local-search path.
        rows = search_level_analytic(level,cfg,options=options,beam_width=beam_width,
                                     family_keep=family_keep,final_k=final_k,school=school)

    # A caller can inject/persist nodes created by a different ruleset while
    # the process-level registry points elsewhere (notably tests switching
    # Classic/Forever). Never feed such a node to the active engine's probe.
    compatible_nodes = bool(rows) and all(
        type(row.talents) is getattr(eng, 'Talents') for row in rows
    )
    if do_stat_weights and compatible_nodes:
        rows=stat_weights.annotate_top_nodes(
            rows,cfg,options=options,school=school,top_k=stat_weight_top_k
        )
    return int(level), rows



def _base_snapshot(args) -> dict:
    snap = {
        'version': 1,
        'engine': 'v2-analytic-kiss',
        'game': game_context.describe(),
        'running': True,
        'started_at': time.time(),
        'phase': 'starting',
        'message': 'Starting analytic v2.',
        'config': {
            'start_level': args.start_level,
            'end_level': args.end_level,
            'beam_width': args.beam_width,
            'family_keep': args.family_keep,
            'final_k': args.final_k,
            'parent_k': args.parent_k,
            'workers': args.workers,
            'max_respecs': args.max_respecs,
            'water_mode': 'buy_water' if args.buy_water else 'conjured_water',
            'views': args.view,
            'school': getattr(args,'school','all'),
            'stat_weights': bool(getattr(args,'stat_weights',True)),
            'stat_weight_top_k': int(getattr(args,'stat_weight_top_k',0)),
            'ruleset': getattr(args,'ruleset',game_context.current().ruleset), 'class': getattr(args,'class_name',game_context.current().class_name),
            'forever_build_as_of': getattr(args,'forever_as_of',None),
            'mage_blizzard_aoe': bool(getattr(args,'mage_blizzard_aoe',False)),
        },
        'views': {},
        'capabilities': {
            'fast': True,
            'mc': bool(getattr(eng, 'MC_SUPPORTED', False)),
            'respec_path_search': True,
            'decision_artifacts': False,
            'endpoint_paths': False,
            'dual_spec_pair': False,
            'stat_matrix': False,
            'model_fidelity': dict(getattr(eng, 'MODEL_FIDELITY', {}) or {}),
        },
    }
    if getattr(args,'ruleset',game_context.current().ruleset) == 'forever':
        snap['forever_build'] = forever_build_metadata()
    provenance = getattr(eng, 'DATA_PROVENANCE', None)
    if provenance is not None and hasattr(provenance, 'as_dict'):
        snap['data'] = provenance.as_dict()
    elif getattr(eng, 'EXPERIMENTAL', False):
        snap['data'] = {
            'build': getattr(eng, 'DATA_BUILD', 'unknown'),
            'attribution': getattr(eng, 'DATA_ATTRIBUTION', 'unknown'),
            'quality': getattr(eng, 'DATA_QUALITY', 'experimental'),
        }
    return snap


def _publish_view(snap: dict, name: str, **updates):
    v = dict(snap.setdefault('views', {}).get(name, {}))
    v.update(updates)
    snap['views'][name] = v
    publish(snap)


_PROGRESS_PUBLISH_EVERY_LEVELS = 5


def _progress_publish_due(done: int, total: int, *, every: int = _PROGRESS_PUBLISH_EVERY_LEVELS) -> bool:
    """Throttle expensive full viewer-snapshot rewrites during search.

    Candidate summaries accumulate with every level. Re-serializing the entire
    snapshot on every completion makes listener I/O quadratic in the level
    count. MC seed-bank files are still written for every level; only viewer
    refreshes are batched.
    """
    done=max(0,int(done)); total=max(0,int(total)); every=max(1,int(every))
    return done in (1,total) or done % every == 0


def _run_view(snap: dict, view: AnalyticView, cfg: eng.SimConfig, args, model: ClassModel):
    name=view.name
    school=getattr(args,'school','all')
    levels=list(range(args.start_level,args.end_level+1))
    t0=time.perf_counter()
    _publish_view(snap,name,status='searching',school=school,levels_done=0,levels_total=len(levels),
                  level_summaries=[],paths={},message='Independent per-level analytic search')

    do_stat_weights=(name=='smooth' and bool(getattr(args,'stat_weights',True)))
    jobs=[(l,cfg,view.options,args.beam_width,args.family_keep,args.final_k,school,
           do_stat_weights,int(getattr(args,'stat_weight_top_k',0))) for l in levels]
    pools={}
    summaries={}
    if args.workers <= 1:
        iterator=map(_search_worker,jobs)
        for level,rows in iterator:
            pools[level]=rows
            mc_bridge.publish_level_candidates(level, rows[:max(args.final_k, 12)], view=name,
                                               water_mode=('buy_water' if args.buy_water else 'conjured_water'))
            summaries[level]=[_node_json(n) for n in rows]
            best=summaries[level][0] if summaries[level] else None
            done=len(pools)
            if _progress_publish_due(done,len(levels)):
                _publish_view(snap,name,status='searching',levels_done=done,levels_total=len(levels),
                              current_level=level, level_summaries=[{'level':l,'candidates':summaries[l],
                              'best':summaries[l][0] if summaries[l] else None} for l in sorted(summaries)],
                              message=f'Level {level} complete' + (f" · {best['min_per_100']:.2f} min/100" if best else ''))
    else:
        with ProcessPoolExecutor(max_workers=args.workers, mp_context=mp.get_context('spawn')) as ex:
            futs={ex.submit(_search_worker,j):j[0] for j in jobs}
            for fut in as_completed(futs):
                level,rows=fut.result()
                pools[level]=rows
                mc_bridge.publish_level_candidates(level, rows[:max(args.final_k, 12)], view=name,
                                                   water_mode=('buy_water' if args.buy_water else 'conjured_water'))
                summaries[level]=[_node_json(n) for n in rows]
                best=summaries[level][0] if summaries[level] else None
                done=len(pools)
                if _progress_publish_due(done,len(levels)):
                    _publish_view(snap,name,status='searching',levels_done=done,levels_total=len(levels),
                                  current_level=level, level_summaries=[{'level':l,'candidates':summaries[l],
                                  'best':summaries[l][0] if summaries[l] else None} for l in sorted(summaries)],
                                  message=f'Level {level} complete' + (f" · {best['min_per_100']:.2f} min/100" if best else ''))

    search_s=time.perf_counter()-t0
    stat_weights_csv=None
    if do_stat_weights:
        stat_weights_csv=str(stat_weights.write_csv(STATE_DIR / f'stat_weights_{name}.csv', pools, view=name))
    _publish_view(snap,name,status='repairing',search_seconds=search_s,stat_weights_csv=stat_weights_csv,
                  message='Repairing talent-path continuity')

    tr=time.perf_counter()
    repaired=close_pools_backward(pools,cfg,view,parent_k=args.parent_k,
                                  start_level=args.start_level,end_level=args.end_level,
                                  max_workers=args.workers,school=school)
    repair_s=time.perf_counter()-tr

    # The smooth Forever Mage view is the primary decision surface.  Correct
    # its retained Ice Lance/control candidates with the bounded event backend
    # before cumulative path DP, so validation and the build recommendation use
    # the same authority.
    if name == 'smooth':
        repaired=model.rerank_repaired_pools(repaired,cfg)

    # Refresh UI with repaired pool leaders.
    repaired_summaries=[]
    for l in levels:
        js=[_node_json(n) for n in repaired[l][:max(args.final_k,12)]]
        repaired_summaries.append({'level':l,'candidates':js,'best':js[0] if js else None,
                                   'pool_size':len(repaired[l])})
    _publish_view(snap,name,status='solving',repair_seconds=repair_s,
                  level_summaries=repaired_summaries,message='Exact layered path DP')

    td=time.perf_counter(); paths={}
    # Solve independently for every budget so the UI shows the actual marginal value of each respec count.
    for r in range(args.max_respecs+1):
        try:
            p=solve_path_dp(repaired,max_respecs=r,start_level=args.start_level,end_level=args.end_level)
            paths[str(r)] = _path_json(p)
        except Exception as e:
            paths[str(r)] = {'error': f'{type(e).__name__}: {e}'}
    dp_s=time.perf_counter()-td
    # Current server respec is ~1 s, so expose a separate per-level-best mode.
    # Do not fold this into finite-respec DP semantics: it answers a different
    # player question ('what is fastest at this exact level if I can respec?').
    paths['per_level_best'] = _per_level_best_path(repaired,cfg,start_level=args.start_level,end_level=args.end_level,respec_seconds=1.0,model=model)
    valid=[p for k,p in paths.items() if str(k).isdigit() and isinstance(p,dict) and p.get('hours') is not None]
    best=min(valid,key=lambda x:x['hours']) if valid else None
    offered = mc_bridge.publish_paths(name, paths, water_mode=('buy_water' if args.buy_water else 'conjured_water'))
    decision_artifacts = None
    # Analytic-view backends adapt repaired pools to canonical LevelFrontier;
    # route publication itself is shared with continuity-beam classes.
    mature_compatible = bool(repaired) and all(
        type(node.talents) is getattr(eng, 'Talents')
        for rows in repaired.values() for node in rows
    )
    if name == 'smooth' and model.runner_strategy() == 'analytic_views' and mature_compatible:
        try:
            from .mature_decision_artifacts import publish_mature_class_decisions
            decision_artifacts = publish_mature_class_decisions(
                str(model.name), repaired, eng, cfg,
                start_level=args.start_level, end_level=args.end_level,
                dual_spec_unlock_level=int(getattr(args, 'dual_spec_unlock_level', 40)),
                candidate_limit=max(24, int(args.final_k), 48),
                max_respecs=int(args.max_respecs), model=model,
            )
            from .spec_matrix import generate_all
            targets = [level for level in (20, 30, 40, 60) if int(args.start_level) <= level <= int(args.end_level)]
            if not targets:
                targets = [int(args.end_level)]
            matrix_path, matrix = generate_all(str(model.name), targets)
            decision_artifacts['spec_matrix_json'] = str(matrix_path)
            decision_artifacts['spec_matrix_count'] = len(matrix.get('matrices', {}))
            snap.setdefault('capabilities', {}).update({
                'decision_artifacts': True,
                'endpoint_paths': bool(decision_artifacts.get('frontier', {}).get('levels')),
                'dual_spec_pair': bool((decision_artifacts.get('dual_spec') or {}).get('status') == 'available'),
                'stat_matrix': bool(matrix.get('matrices')),
            })
        except Exception as exc:
            decision_artifacts = {'error': f'{type(exc).__name__}: {exc}'}
    _publish_view(snap,name,status='complete',search_seconds=search_s,repair_seconds=repair_s,
                  dp_seconds=dp_s,total_seconds=time.perf_counter()-t0,paths=paths,best_path=best,
                  mc_bridge_paths=offered,stat_weights_csv=stat_weights_csv,
                  decision_artifacts=decision_artifacts,
                  message=f'Analytic view complete · offered {offered} path(s) to MC bridge')
    return repaired,paths


def _run_analytic_views(args, model: ClassModel):
    """Run the historical analytic-view search behind the shared Forever entrypoint.

    Classic Mage may still call this directly; Forever callers arrive through
    ``forever_runner`` based on the ClassModel-declared runner strategy.
    """
    cfg=eng.SimConfig(use_best_water=bool(args.buy_water))
    cfg=model.apply_cli_config(cfg,args)
    mc_bridge.reset(water_mode=('buy_water' if args.buy_water else 'conjured_water'), views=args.view)
    snap=_base_snapshot(args); publish(snap)
    try:
        views={v.name:v for v in default_views()}
        order=['hard','smooth'] if args.view=='both' else [args.view]
        for name in order:
            snap['phase']=f'{name}:search'
            snap['message']=f'Running {name} analytic view'
            publish(snap)
            _run_view(snap,views[name],cfg,args,model)
        snap['running']=False; snap['phase']='complete'; snap['message']='V2 analytic search complete.'
        best=[]
        for name,v in snap.get('views',{}).items():
            p=v.get('best_path')
            if p and p.get('hours') is not None: best.append((float(p['hours']),name,p))
        if best:
            _,name,p=min(best)
            snap['best_analytic']={'view':name,**p}
        publish(snap)
        return snap
    except KeyboardInterrupt:
        snap['running']=False; snap['phase']='interrupted'; snap['message']='Interrupted by user.'; publish(snap)
        raise
    except Exception as e:
        snap['running']=False; snap['phase']='error'; snap['message']=f'{type(e).__name__}: {e}'
        snap['traceback']=traceback.format_exc(limit=20); publish(snap)
        raise


def main():
    ap=argparse.ArgumentParser(description='Analytic v2 leveling optimizer with live listener snapshot')
    game_context.add_game_arguments(ap)
    ap.add_argument('--start-level',type=int,default=11)
    ap.add_argument('--forever-as-of', dest='forever_as_of', default=None, help='Forever beta build/as-of date YYYY-MM-DD; omitted legacy scripts map to the 2026-10-02 compatibility snapshot')
    ap.add_argument('--end-level',type=int,default=None)
    ap.add_argument('--beam-width',type=int,default=10)
    ap.add_argument('--family-keep',type=int,default=2)
    ap.add_argument('--final-k',type=int,default=8)
    ap.add_argument('--stat-weights',action=argparse.BooleanOptionalAction,default=True,
                    help='smooth view: compute per-build stat weights through the shared class backend contract')
    ap.add_argument('--stat-weight-top-k',type=int,default=0,
                    help='smooth view: number of top builds per level to annotate with stat weights; 0 = all returned final-k')
    ap.add_argument('--parent-k',type=int,default=1)
    ap.add_argument('--workers',type=int,default=(1 if os.name=='nt' else max(1,min(5,(os.cpu_count() or 2)-1))))
    ap.add_argument('--max-respecs',type=int,default=2)
    ap.add_argument('--dual-spec-unlock-level',type=int,default=40,
                    help='level where a second independent talent path becomes available (default: 40)')
    ap.add_argument('--view',choices=('hard','smooth','both'),default='smooth', help='production default is smooth; hard is debug/reference only')
    ap.add_argument('--buy-water',action=argparse.BooleanOptionalAction,default=True)
    ap.add_argument('--gear-overrides-json', default='', help='JSON object mapping published gear slots to exact item IDs; unpinned slots still optimize')
    ap.add_argument('--mage-blizzard-aoe', action=argparse.BooleanOptionalAction, default=False,
                    help='Forever Mage only: opt into the server-dependent Blizzard/AoE leveling lane; fail closed until its AoE scorer is implemented')
    school_group=ap.add_mutually_exclusive_group()
    profile_choices=tuple(dict.fromkeys(profile for cls in class_names('forever') for profile in get_definition('forever', cls).primary_profiles))
    school_group.add_argument('--school','--spec',dest='school',choices=profile_choices,default='all',
                              help='primary leveling spec/profile declared by the selected class registry entry')
    school_group.add_argument('--frost',dest='school',action='store_const',const='frost',
                              help='shortcut for --school frost')
    args=ap.parse_args()
    selected_game=game_context.validate_cli_selection(ap, args)
    selected_definition=get_definition(selected_game.ruleset, selected_game.class_name)
    if selected_game.ruleset == 'forever':
        explicit = args.forever_as_of is not None
        identity = configure_forever_build(args.forever_as_of, source='cli_explicit' if explicit else 'legacy_compat_default')
        args.forever_as_of = identity.as_of.isoformat()
        if not explicit:
            print(f'[forever build] no --forever-as-of supplied; using legacy compatibility snapshot {args.forever_as_of}', flush=True)
    if args.end_level is None:
        # A class may be first-class in the UI while still having a deliberately
        # bounded verified mechanics range. Respect an explicit class-local cap
        # below 60 instead of coupling CLI defaults to the old proof-only label.
        local_cap = int(getattr(eng, 'VERIFIED_LEVEL_CAP', 60 if getattr(eng,'RULESET','classic') == 'forever' else 59))
        if getattr(eng,'RULESET','classic') == 'forever' and local_cap < 60:
            args.end_level = local_cap
        else:
            args.end_level = 60 if getattr(eng,'RULESET','classic') == 'forever' else 59
    if args.end_level < args.start_level: ap.error('end-level must be >= start-level')
    if getattr(eng,'EXPERIMENTAL',False) and args.end_level > int(getattr(eng,'VERIFIED_LEVEL_CAP',args.end_level)):
        print(f"[warning] {eng.RULESET}/{eng.CLASS_NAME}: levels above verified beta cap {eng.VERIFIED_LEVEL_CAP} use fallback/approximate data", flush=True)
    args.max_respecs=max(0,min(8,args.max_respecs))
    os.environ[eng.PRIMARY_SCHOOL_ENV]=args.school
    model=active_class_model()
    if selected_game.ruleset == 'forever':
        from .forever_runner import run as run_forever
        from src.rulesets.forever.items.runtime_selection import gear_overrides
        try:
            overrides = json.loads(args.gear_overrides_json) if str(args.gear_overrides_json or '').strip() else None
        except Exception as exc:
            ap.error(f'--gear-overrides-json must be a JSON object: {exc}')
        if overrides is not None and not isinstance(overrides, dict):
            ap.error('--gear-overrides-json must be a JSON object')
        with gear_overrides(overrides):
            return run_forever(args, analytic_runner=_run_analytic_views)
    return _run_analytic_views(args, model)


if __name__=='__main__':
    main()
