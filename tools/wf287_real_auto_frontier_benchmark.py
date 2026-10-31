"""Measured nine-class production full-cycle canary, and named-gear coupling.

This is *bounded*, not a source-complete class-level acceptance test.
No independent score implementation is used.
"""
from __future__ import annotations
import json
from pathlib import Path
from statistics import median
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
from src.v2.source_budgeted_gear import run_source_budgeted_gear

CLASSES=('druid','hunter','mage','paladin','priest','rogue','shaman','warlock','warrior')

def summarize(r):
    return {'status':r['status'], 'best_s_per_mob':(
        r['winner']['score_s_per_mob'] if r.get('winner') else None),
        'l2_attempts':r.get('l2_attempts',0),
        'l1_attempts':r.get('l1_attempts',0),
        'l0_candidates':r.get('l0_candidates_generated',0),
        'event_transitions':r.get('event_transitions',0),
        'full_run_cpu_ms':round(r.get('full_run_cpu_ns',0)/1e6,3),
        'scratch_verified':r.get('verification_completed',0),
        'scratch_required':r.get('verification_required',0),
        'auto_fallback_ids':r.get('auto_fallback_ids',[]),
        'winner_prefix':r['winner']['prefix'] if r.get('winner') else None,
        'winner_continuation':r['winner'].get('guarded_action') if r.get('winner') else None,
        'winner_fallback':r['winner']['fallback'] if r.get('winner') else None}

def main():
    data={'baseline':'v0.11.48.286','change':'generic source-qualified initial-mode auto continuation',
        'scenario':'L20 source IR, incoming attacks, real combat+recovery+survival',
        'policy_budget':{'max_l2_attempts':24,'max_event_transitions':5000,'use_l1':True},
        'classes':{},'gear':{},'complete_class_level_checkpoints':0,'continuous_routes':0}
    for key in CLASSES:
        before=run_source_stateful_budgeted(class_key=key,level=20,
            max_l2_attempts=24,max_event_transitions=5000,use_l1=True)
        after=run_source_stateful_budgeted(class_key=key,level=20,
            max_l2_attempts=24,max_event_transitions=5000,use_l1=True,
            search_auto_fallback=True)
        data['classes'][key]={'before':summarize(before),'after':summarize(after)}
    data['l20_l2_successes_before']=sum(x['before']['best_s_per_mob'] is not None for x in data['classes'].values())
    data['l20_l2_successes_after']=sum(x['after']['best_s_per_mob'] is not None for x in data['classes'].values())
    for key in ('hunter','paladin'):
        r=run_source_budgeted_gear(class_key=key,level=20,max_evaluations=45,
            initial_search=22,search_per_gear=12,max_gear_states=2,
            probe_stats=('agility','strength','stamina'),probe_deltas=(5,),
            policy_search_backend='stateful',stateful_search_auto_fallback=True,
            stateful_use_l1=False,max_event_transitions=7000,
            required_level_policy='observed')
        data['gear'][key]={'status':r['status'],'attempted':r['attempted'],
            'event_transitions':r['event_transitions'],
            'total_controller_cpu_ms':round(r['total_controller_cpu_ns']/1e6,3),
            'stat_probe_attempts':r['stat_probe_attempts'],
            'stages':[{'name':s['stage'],
                'best_s_per_mob':s['winner']['score_s_per_mob'] if s['winner'] else None,
                'gear_role':s.get('source_gear_role'),
                'gear_item_count':len(s['gear']['slots']) if s['gear'] else 0}
                for s in r['stages']],
            'acquisition_complete':False}
    print(json.dumps(data,indent=2,sort_keys=True))
    return data

if __name__=='__main__':main()
