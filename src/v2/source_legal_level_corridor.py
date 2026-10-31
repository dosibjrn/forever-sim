"""Full-budget, source-legal contiguous level corridor using existing scorer/DP.

This does NOT claim all indexed source talents or all obtainable gear are
executable. Every *currently executable* full-budget talent allocation is
enumerated by incremental one-point transitions; no Cartesian cutoff, legacy
seed or invented filler point. Each allocation is scored on a bounded,
source-selected named gear screen with the shared incoming-inclusive 3-pull
combat/recovery scorer, then the existing no-respec route DP solves the path.
"""
from __future__ import annotations
from math import isfinite
from time import monotonic

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_search import talent_candidate_id
from src.game.talents import validate_talent_selection
from src.shared.leveling.objective import representative_hp
from src.v2.generic_frontier import GenericTalentBuild, GenericTalentRouteModel
from src.v2.path_dp import LevelNode, solve_path_dp
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_legal_beam import legal_point_frontier
from src.v2.source_multi_pull_joint import _score_state
from src.v2.source_staged_joint_search import _diverse_gear_indices


def search_source_legal_level_corridor(*, class_key: str, start_level: int = 10,
        end_level: int = 30, gear_screen_count: int = 3,
        policy_cap: int = 12, pulls: int = 3):
    if start_level != 10 or end_level < start_level or end_level > 60:
        raise ValueError('source full-budget corridor requires talent start L10 and end <=60')
    if not 1 <= gear_screen_count <= 256 or policy_cap < 1 or pulls < 2:
        raise ValueError('invalid scored corridor budget')
    start=monotonic()
    previous=[{}]
    pools={}
    level_rows=[]
    total_policy=total_states=total_generated=total_duplicate=total_rejected=0
    for level in range(start_level,end_level+1):
        source=build_game_ir_slice(class_key=class_key,level=level)
        if source is None:
            raise ValueError(f'no source IR for {class_key} L{level}; no level interpolation')
        generated=[a for parent in previous for a in legal_point_frontier(
            source,parent,level=level,allow_transfers=False)]
        unique={talent_candidate_id(a):a for a in generated}
        if not unique:
            raise ValueError(f'no source-executable full-point talent corridor at L{level}')
        total_generated+=len(generated)
        total_duplicate+=len(generated)-len(unique)
        # Every source-executable full-budget allocation is represented, not
        # just the first lexical candidates. The gear/policy envelope remains
        # explicitly bounded; all missing indexed effects are recorded.
        for a in unique.values():
            validate_talent_selection(source,a,level=level)
            if sum(a.values())!=level-9:
                raise ValueError('partial-budget allocation entered legal route')
        gears=_gear_envelope(class_key,level,max_gear_candidates=256,
            required_level_policy='observed',include_melee_gear=True,ir_slice=source)
        if len(gears)<gear_screen_count:
            raise ValueError(f'insufficient source gear at L{level}')
        screen=[gears[i] for i in _diverse_gear_indices(gears,gear_screen_count)]
        nodes=[]
        for cid,allocation in sorted(unique.items()):
            if __import__('os').environ.get('WF257_PROGRESS') and level>=25:
                print(f'  scoring L{level} {cid}',flush=True)
            rows=[_score_state(source,level=level,gear=g,allocation=allocation,
                pulls=pulls,policy_cap=policy_cap,target_health=representative_hp(level))
                for g in screen]
            total_states+=len(rows)
            total_policy+=sum(row['policy_evaluated'] for row in rows)
            total_rejected+=sum(row['policy_rejected'] for row in rows)
            scored=[row for row in rows if row['seconds_per_mob'] is not None]
            if not scored:
                raise ValueError(f'no executable combat policy for source-legal {cid} L{level}')
            best=min(scored,key=lambda row:(row['seconds_per_mob'],row['gear_id']))
            tree_map={t.id:t.tree_key for t in source.talents}
            build=GenericTalentBuild.from_candidate(
                {'selection':allocation,'candidate_id':cid,'spent_points':sum(allocation.values())},
                available_points=level-9,
                executable_talent_ids=[t.id for t in source.talents if any(r.modifiers for r in t.ranks)],
                talent_tree_by_id=tree_map)
            nodes.append(LevelNode(level=level,talents=build,
                score_s_per_100=100*float(best['seconds_per_mob']),
                policy=best['best_policy']['policy'],source='source_legal_level_corridor',
                details={'candidate_id':cid,'gear_slots':best['gear_slots'],
                    'gear_id':best['gear_id'],'gear_role':best['gear_role'],
                    'seconds_per_mob':best['seconds_per_mob'],
                    'best_policy':best['best_policy'],
                    'policy_evaluated':sum(row['policy_evaluated'] for row in rows),
                    'source_builds':sorted({str(f.get('client_build'))
                        for f in source.source_facts if f.get('client_build')}),
                    'gear_screen_count':len(screen),'full_gear_count':len(gears)}))
        if __import__('os').environ.get('WF257_PROGRESS'):
            print(f'L{level}: {len(unique)} allocations / {len(screen)} gear, elapsed={monotonic()-start:.1f}s',flush=True)
        pools[level]=nodes
        level_rows.append({'level':level,'full_budget_legal_allocations':len(unique),
            'gear_screen_count':len(screen),'full_gear_envelope':len(gears),
            'screened_states':len(unique)*len(screen),
            'source_executable_families':sum(any(r.modifiers for r in t.ranks) for t in source.talents),
            'source_indexed_families':len(source.talents),
            'missing_executable_families':sorted(t.id for t in source.talents
                if not any(r.modifiers for r in t.ranks))})
        previous=list(unique.values())
    path=solve_path_dp(pools,max_respecs=0,model=GenericTalentRouteModel())
    if len(path.steps)!=end_level-start_level+1 or path.respecs_used:
        raise ValueError('continuous no-respec route was not proven')
    steps=[]
    for step in path.steps:
        detail=step.node.details
        steps.append({'level':step.node.level,'talents':dict(step.node.talents.ranks),
            'talent_added':step.talent_added,'gear_slots':detail['gear_slots'],
            'gear_id':detail['gear_id'],'seconds_per_mob':detail['seconds_per_mob'],
            'policy':detail['best_policy']['policy'],
            'recovery_action_ids':detail['best_policy'].get('recovery_action_ids'),
            'first_pull':detail['best_policy']['pulls'][0],
            'cumulative_weighted_objective_s':step.cumulative_s})
    return {'status':'EVALUATED_BOUNDED_CONTINUOUS_EXECUTABLE_SUBSPACE',
        'class_key':class_key,'start_level':start_level,'end_level':end_level,
        'objective':'stateful incoming-inclusive three-pull combat/recovery s/mob, route DP weighted by level',
        'route':steps,'route_total_weighted_s':path.cumulative_s,
        'route_respecs':path.respecs_used,
        'source_coverage_complete':False,'global_optimum_proven':False,
        'route_gear_acquisition_verified':False,
        'source_executable_talent_subspace_exhaustive':True,
        'source_executable_full_budget_allocations_by_level':level_rows,
        'candidate_transitions_generated':total_generated,
        'candidate_duplicate_transitions':total_duplicate,
        'talent_allocations_pruned':0,
        'gear_policy_screened_states':total_states,
        'policy_evaluations':total_policy,'policy_rejections':total_rejected,
        'gear_screen_count':gear_screen_count,'policy_cap':policy_cap,
        'missing_source_families_at_endpoint':level_rows[-1]['missing_executable_families'],
        'limits':['Only executable source talent families; all other indexed families explicitly unscored',
                  'Gear candidates are level-legal observed catalogue; actual acquisition/travel not verified',
                  'Gear screened rather than full envelope; policy frontier bounded',
                  'Source player HP/primary stat baselines and enemy damage include proxies',
                  'Talents, equipment, consumables, professions and all legal actions not source-complete'],
        'elapsed_s':monotonic()-start}
