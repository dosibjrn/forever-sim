"""Adapt the existing WF261 exact stateful scorer to WF259/260 joint search.

No new gameplay engine.  L1 event work and scratch verification are charged to
one per-call transition budget; old W1's scorer result contract is preserved.
"""
from __future__ import annotations

from src.v2.source_stateful_budgeted import run_source_stateful_budgeted


def stateful_policy_as_prefix(*, class_key, level, max_evaluations, ir_slice,
                              schedule_incoming_attacks=True,
                              max_event_transitions=15000,
                              use_l1=True, use_prefix_cache=True, l1_mode='value_gated',
                              search_guarded_continuations=False,
                              search_mode_paths=False, search_auto_fallback=False, family_budget_mode='legacy'):
    r=run_source_stateful_budgeted(class_key=class_key,level=level,
        max_l2_attempts=max_evaluations,
        max_event_transitions=max_event_transitions,
        use_l1=use_l1, l1_mode=l1_mode, use_prefix_cache=use_prefix_cache,
        search_guarded_continuations=search_guarded_continuations,
        search_mode_paths=search_mode_paths, search_auto_fallback=search_auto_fallback,
        family_budget_mode=family_budget_mode,
        ir_slice=ir_slice,
        schedule_incoming_attacks=schedule_incoming_attacks)
    if 'l2_attempts' not in r:
        # Fail closed when all sourced actions/fallbacks are unsupported. No
        # produced L2 result, no fabricated no-op talent/policy.
        return {'status':r['status'],'attempted':0,'evaluated':0,'blocked':0,
                'budget':max_evaluations,'seed_count':0,'seed_skipped_by_budget':0,
                'context_sha256':r.get('source_context'),
                'winner':None,'runner_up':None,'best_vs_budget':[],
                'event_transitions':0,'l1_attempts':0,'cache_hits_l2':0,'cpu_ns':0,
                'source_blockers':r.get('blocked_source_semantics',[])}
    # Full scratch verifications are real L2 invocations, paid by the engine;
    # they are not extra "free" score observations.
    l2=[x for x in r.get('observations',()) if x.get('tier')=='L2']
    verification=r.get('scratch_verification',())
    guarded_l2=[x for x in l2 if x.get('guarded_action') is not None]
    guarded_successes=[x for x in guarded_l2 if x.get('status')=='FULL_L2_VERIFIED']
    paid=[*l2, *verification]
    assert len(paid)==r['l2_attempts']
    best=None
    trace=[]
    good=0
    for index,x in enumerate(paid,1):
        ok=x.get('status')=='FULL_L2_VERIFIED'
        if ok:
            good+=1
            score=float(x['score_s_per_mob'])
            best=score if best is None else min(best,score)
        trace.append({'attempt':index,'best_s_per_mob':best,
                      'status':'evaluated' if ok else 'blocked',
                      'prefix':x.get('prefix'),'source_tier':'L2_scratch' if index>len(l2) else 'L2'})
    def convert(x):
        if x is None:return None
        return {'score_s_per_mob':x['score_s_per_mob'],
                'prefix':list(x['prefix']), 'fallback':x['fallback'],
                'guarded_action':x.get('guarded_action'),
                'guarded_conditions':list(x.get('guarded_conditions',[])),
                'selected_actions':x.get('actions',[]),
                'kill_s':x['kill_s'],'recovery_s':x['recovery_s'],
                'event_count':x.get('full_timeline_events'),
                'checkpoint_hit_length':x.get('checkpoint_hit_length',0),
                'source_context_sha256':r['source_context']}
    return {'status':'EVALUATED_BOUNDED' if r.get('winner') else r['status'],
            'attempted':len(paid),'evaluated':good,'blocked':len(paid)-good,
            'budget':max_evaluations,'seed_count':r.get('seed_count'),
            'seed_skipped_by_budget':r.get('seed_unattempted'),
            'context_sha256':r.get('source_context'),
            'winner':convert(r.get('winner')),'runner_up':convert(r.get('runner_up')),
            'best_vs_budget':trace,
            'event_transitions':r.get('event_transitions',0),
            'l1_attempts':r.get('l1_attempts',0),
            'cache_hits_l2':r.get('cache_hits_l2',0),
            'cpu_ns':r.get('cpu_ns',0),
            'stateful_model':r.get('status'),
            'guarded_continuations_searched':bool(search_guarded_continuations),
            'mode_path_search_enabled':bool(search_mode_paths),
            'auto_fallback_search_enabled':bool(search_auto_fallback),
            'family_budget_mode':family_budget_mode,
            'family_l2_counts':r.get('family_l2_counts',{}),
            'available_source_mode_paths':r.get('available_source_mode_paths',[]),
            'mode_l2_attempts':r.get('mode_l2_attempts',0),
            'guarded_l2_attempts':len(guarded_l2),
            'guarded_l2_verified':len(guarded_successes),
            'guarded_l2_evidence':[{'prefix':x['prefix'], 'fallback':x['fallback'],
                'guarded_action':x['guarded_action'],
                'guarded_conditions':x.get('guarded_conditions',[]),
                'status':x['status'], 'score_s_per_mob':x.get('score_s_per_mob'),
                'events':x['events']} for x in guarded_l2],
            'l1_mode':r.get('l1_mode'), 'l1_value_evidence':r.get('l1_value_evidence'),
            'source_blockers':r.get('blocked_source_semantics',[]),
            'event_work_includes_L1_L2_and_scratch':True}
