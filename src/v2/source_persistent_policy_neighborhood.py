"""Paid policy mutations on the existing source-backed persistent CombatRuntime.

Two-mob trials ONLY prioritize spending compute. Ranking/acceptance uses real
100-mob kill+recovery+survival, exact same evaluator as joint gear/talents.
No separate combat engine, no hardcoded action vocabulary, no legacy seeds.
"""
from __future__ import annotations
from dataclasses import replace
from math import isfinite
from time import monotonic

from src.game.policy_evolution import mutations, scratch_policies, _identity
def evaluate_persistent_candidate(*args, **kwargs):
    # Import only when paid execution starts; the module can also be tested as
    # an isolated, layered overlay without materializing all older archives.
    from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate as run
    return run(*args, **kwargs)


def _completed_hundred(evidence):
    return evidence.get('status')=='COMPLETE' and (evidence.get('count')==100 or evidence.get('mob_completed')==100)


def refine_source_policy_persistent(candidate, *, level: int, recovery_policy,
                                    max_proposals: int=16,max_finalists: int=2,
                                    max_total_wall_s: float=22.,
                                    max_screen_wall_s: float=1.5,
                                    max_finalist_wall_s: float=7.,
                                    baseline_100mob: dict|None=None,
                                    add_scratch:bool=True,
                                    mob_spacing_yards:float=0.) -> dict:
    if not (1<=max_proposals<=512 and 1<=max_finalists<=max_proposals):
        raise ValueError('INVALID_APL_SEARCH_BOUNDS')
    if not(isfinite(max_total_wall_s) and max_total_wall_s>0):
        raise ValueError('INVALID_APL_WALL_BUDGET')
    start=monotonic()
    # Parent+local edits+sourced scratch. Interleave structural and scratch
    # rather than filling candidate cap with dozens of insertions.
    parent=candidate.policy
    neighbors=mutations(parent,candidate.ir,max_candidates=max_proposals*3)
    scratch=scratch_policies(candidate.ir,max_candidates=max_proposals) if add_scratch else ()
    proposals=[parent]
    seen={_identity(parent)}
    for i in range(max(len(neighbors),len(scratch))):
        for source in (neighbors,scratch):
            if i<len(source):
                proposal=source[i];identity=_identity(proposal)
                if identity not in seen and len(proposals)<max_proposals:
                    seen.add(identity);proposals.append(proposal)
        if len(proposals)>=max_proposals:break
    def paid(policy, mobs, wall):
        try:
            return evaluate_persistent_candidate(replace(candidate,policy=policy),
                level=level,mobs=mobs,recovery_policy=recovery_policy,
                max_wall_s=wall,max_cpu_s=wall,
                max_total_events=4500 if mobs==2 else 200000,
                mob_spacing_yards=mob_spacing_yards)
        except (ValueError,RuntimeError,KeyError) as exc:
            return {'status':'BLOCKED_POLICY_RUNTIME_OR_SOURCE',
                    'reason':str(exc)[:300], 'events':0}

    attempts=[];screen_events=0
    for n,policy in enumerate(proposals):
        if monotonic()-start>max_total_wall_s-max_finalist_wall_s:
            break
        if n==0 and baseline_100mob is not None and _completed_hundred(baseline_100mob):
            # Parent has authoritative PAID 100-mob result; 2-mob proxy not
            # required to certify its baseline or to keep it among finalists.
            screen={'status':'PARENT_100MOB_ALREADY_PAID','mean_s_per_mob':baseline_100mob['mean_s_per_mob'], 'events':0}
        else:
            screen=paid(policy,2,max_screen_wall_s)
        screen_events+=int(screen.get('events') or 0)
        attempts.append({'policy_id':policy.id,'policy_sha256_16':_identity(policy),
                         'operation':policy.provenance.get('mutation',policy.provenance.get('origin')),
                         'policy':policy,'screen':screen})
    ranked=sorted((r for r in attempts[1:] if r['screen'].get('status')=='COMPLETE'),
                  key=lambda r:(float(r['screen']['mean_s_per_mob']),r['policy_sha256_16']))
    final=[];full_events=0
    if baseline_100mob is not None and _completed_hundred(baseline_100mob):
        parent_paid=dict(baseline_100mob)
    elif monotonic()-start<max_total_wall_s-max_finalist_wall_s:
        parent_paid=paid(parent,100,max_finalist_wall_s)
        full_events+=int(parent_paid.get('events') or 0)
    else:parent_paid={'status':'NOT_RUN_WALL_BUDGET'}
    final.append({'policy':parent,'policy_id':parent.id,'result':parent_paid,'parent':True})
    for row in ranked[:max_finalists]:
        if monotonic()-start>max_total_wall_s-max_finalist_wall_s:break
        paid_result=paid(row['policy'],100,max_finalist_wall_s)
        full_events+=int(paid_result.get('events') or 0)
        final.append({'policy':row['policy'],'policy_id':row['policy_id'],'result':paid_result,'parent':False})
    valid=[f for f in final if _completed_hundred(f['result'])
                        and f['result'].get('mean_s_per_mob') is not None
                        and isfinite(float(f['result']['mean_s_per_mob']))]
    winner=min(valid,key=lambda x:(float(x['result']['mean_s_per_mob']),
               len(x['policy'].rules),_identity(x['policy']))) if valid else None
    return {'status':'COMPLETE' if winner else 'NO_COMPLETE_100MOB_POLICY',
            'winner':winner,'parent_100mob':parent_paid,'screen_attempts':len(attempts),
            'screen_complete':sum(x['screen']['status']=='COMPLETE' for x in attempts),
            'full_attempts':len(final),'full_complete':len(valid),
            'paid_events':screen_events+full_events,'elapsed_wall_s':monotonic()-start,
            'attempts':attempts,'finalists':final,
            'actual_objective':'100 consecutive source-backed mobs with persistent actor, recovery, survival',
            'spatial_limit':'sequential travel only; NOT a simultaneous pack simulator',
            'source_actions_total':len({a.id for a in candidate.ir.actions if a.owner_actor_id==candidate.ir.actor.id}),
            'source_actions_proposed':len({r.action_id for p in proposals for r in p.rules}),
            'search_is_exhaustive':False}
