"""Source-legal, independently scored gear perturbations for persistent search.

Short two-mob screens overvalue initial prebuff and may reverse long-run gear
rankings. Start only from blind optimizer source stages; vary *source-selector
stat weights*, never inject known item IDs or past winner configurations.
Every legal proposed gear set must survive a 10-mob real CombatRuntime screen
and then 100 consecutive persistent mobs on one actor before it may win.
"""
from __future__ import annotations

from math import isfinite
from time import monotonic

from src.game.data.forever.gear import select_named_gear, available_gear_roles


def refine_source_gear_persistent(*, class_key: str, level: int,
                                  stage: dict, screen_mobs: int = 10,
                                  finalist_mobs: int = 100,
                                  max_proposals: int = 24,
                                  max_finalists: int = 5,
                                  max_screen_wall_s: float | None = 2.0,
                                  max_finalist_wall_s: float | None = 4.0,
                                  recovery_policy=None,
                                  source_ir=None,
                                  strict_l2_item_effects: bool = False,
                                  max_total_wall_s: float | None = None) -> dict:
    """Bounded local gear search. No winner fixtures, guessed stats or free evals."""
    from src.v2.source_persistent_joint_finalists import prepare_candidate,evaluate_persistent_candidate
    if not (1 <= screen_mobs <= finalist_mobs and max_proposals >= 1 and max_finalists >= 1):
        raise ValueError('invalid source-gear refinement budget')
    t0=monotonic()
    base=stage['gear_policy_result']['winner']['gear']
    known=base['selection_weights']
    if not base['slots'] or not known or not available_gear_roles(class_key):
        raise ValueError('missing source named gear or selector axes')
    rows=[];seen=set();paid_events=0;attempts=0;legal_identities=set()
    def time_left():
        return None if max_total_wall_s is None else max_total_wall_s-(monotonic()-t0)
    def remaining_budget(per_candidate):
        left=time_left()
        return per_candidate if left is None else max(0.001,min(per_candidate,left-0.10))
    origin=tuple(sorted((str(k),int(v['item_id'])) for k,v in base['slots'].items()))
    # Use only stat axes already explored by the source-stat controller. It is
    # legal to rescale a search hyperparameter; never synthesize an item fact.
    axes=sorted(str(k) for k in known)
    candidates=[]
    roles=(base['role'],*(x for x in available_gear_roles(class_key) if x!=base['role']))
    # Interleave source roles: a tight 30s search must not spend its entire
    # frontier on the first role's axes while other legal packages are unseen.
    for stat in axes:
        for factor in (.1,.25,1.,4.,10.,40.):
            for role in roles:
                weights={str(k):float(v) for k,v in known.items()}
                # A zero axis can be explored using the median observed
                # positive weight rather than remaining forever invisible.
                positive=sorted(x for x in weights.values() if x>0 and isfinite(x))
                if not positive:raise ValueError('unusable source selector weights')
                weights[stat]=(weights[stat] if weights[stat]>0 else positive[len(positive)//2]) * factor
                candidates.append((role,stat,factor,weights))
    # Keep source-role diversity while respecting a finite, explicit cap.
    candidates=candidates[:max_proposals]
    for role,stat,factor,weights in candidates:
        if time_left() is not None and time_left()<0.20:break
        attempts+=1
        try:
            selection=select_named_gear(class_key=class_key,level=level,
                stat_weights=weights,required_level_policy='observed',role=role,
                exclude_unknown_item_effects=strict_l2_item_effects)
            gear=selection.as_dict()
            identity=tuple(sorted((str(k),int(v['item_id'])) for k,v in gear['slots'].items()))
            if identity==origin or identity in seen:
                continue
            seen.add(identity)
            # New gear, same sourced policy/talent allocation. Rebuild fresh
            # IR through the exact public candidate preparation routine.
            updated={**stage,
                # The source L2 score belongs to the ORIGINAL equipment and
                # cannot be carried over to a newly selected source item set.
                'score_s_per_mob':None,
                'original_paid_source_stage_score_s_per_mob':stage.get('score_s_per_mob'),
                'source_policy_and_gear_reused':True,
                'paid_candidate_origin':'persistent_source_gear_neighborhood',
                'stage_score_status':'NOT_L2_TESTED_WITH_CHANGED_GEAR',
                'gear_policy_result':{
                    **stage['gear_policy_result'],
                    'winner':{**stage['gear_policy_result']['winner'],'gear':gear}}}
            candidate=prepare_candidate(class_key=class_key,level=level,stage=updated,
                source_ir=source_ir,strict_l2_item_effects=strict_l2_item_effects)
            legal_identities.add(identity)
            screen=evaluate_persistent_candidate(candidate,level=level,mobs=screen_mobs,
                max_wall_s=remaining_budget(max_screen_wall_s or 10.),
                recovery_policy=recovery_policy)
            paid_events+=int(screen.get('events') or 0)
        except (ValueError,RuntimeError,KeyError) as exc:
            rows.append({'role':role,'axis':stat,'factor':factor,
                         'status':'BLOCKED_SOURCE_GEAR','reason':str(exc)})
            continue
        rows.append({'role':role,'axis':stat,'factor':factor,'stage':updated,
                     'gear_items':{slot:int(x['item_id']) for slot,x in gear['slots'].items()},
                     'screen':screen,'status':screen['status']})
    viable=[r for r in rows if r['status']=='COMPLETE']
    viable.sort(key=lambda r:(r['screen']['mean_s_per_mob'],
        tuple(sorted(r['gear_items'].items()))))
    finalists=[]
    for r in viable[:max_finalists]:
        if time_left() is not None and time_left()<0.20:break
        attempts+=1
        cand=prepare_candidate(class_key=class_key,level=level,stage=r['stage'],
            source_ir=source_ir,strict_l2_item_effects=strict_l2_item_effects)
        replay=evaluate_persistent_candidate(cand,level=level,mobs=finalist_mobs,
            max_wall_s=remaining_budget(max_finalist_wall_s or 10.),
            recovery_policy=recovery_policy)
        paid_events+=int(replay.get('events') or 0)
        finalists.append({**r,'persistent':replay})
    completed=[r for r in finalists if r['persistent']['status']=='COMPLETE']
    completed.sort(key=lambda r:(r['persistent']['mean_s_per_mob'],
        tuple(sorted(r['gear_items'].items()))))
    return {'status':'PERSISTENT_GEAR_NEIGHBOR_VERIFIED_BOUNDED' if completed else 'BLOCKED_NO_GEAR_FINALIST',
            'class_key':class_key,'level':level,'proposals_budget':max_proposals,
            'proposals_generated':len(candidates),'distinct_source_gear_sets_evaluated':len(rows),
            'screen_completed':len(viable),'finalists_completed':len(completed),
            'screen_mobs':screen_mobs,'finalist_mobs':finalist_mobs,
            'winner':completed[0] if completed else None,
            'finalists':finalists,
            'screened':[{k:v for k,v in r.items() if k not in ('stage',)} for r in rows],
            'elapsed_wall_s':monotonic()-t0,
            'attempts_paid':attempts,'events_paid':paid_events,
            'unique_legal_gear_sets':len(legal_identities),
            'legal_gear_identities':[list(x) for x in sorted(legal_identities)],
            'global_optimum_proven':False,'formal_checkpoint_accepted':False,
            'limitations':['bounded weight perturbations cannot prove complete gear coverage',
                           'source acquisition/rune effects and player combat fidelity still incomplete']}
