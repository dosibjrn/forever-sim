"""Measured cross-family scheduling: identical source/runtime/scorer and event caps."""
import json
from pathlib import Path
from time import process_time_ns

from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
from src.v2.source_budgeted_gear import run_source_budgeted_gear
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents


def compact(r):
    w = r.get('winner')
    return dict(status=r['status'], l2_attempts=r['l2_attempts'],
        l1_attempts=r['l1_attempts'], events=r['event_transitions'],
        scorer_cpu_ms=round(r['cpu_ns']/1e6,3),
        total_controller_cpu_ms=round(r['total_controller_cpu_ns']/1e6,3),
        wall_ms=round(r['total_wall_ns']/1e6,3),
        score_s_per_mob=(w or {}).get('score_s_per_mob'),
        winner_prefix=(w or {}).get('prefix'),
        winner_fallback=(w or {}).get('fallback'),
        winner_guard=(w or {}).get('guarded_action'),
        kill_s=(w or {}).get('kill_s'), recovery_s=(w or {}).get('recovery_s'),
        verification_complete=r['verification_complete'],
        verification=r['scratch_verification'],
        family_counts=r['family_l2_counts'],
        family_best=r['family_verified_best'],
        decisions=r['family_decisions'],
        l1_value_evidence=r['l1_value_evidence'],
        curve=[dict(attempt=x['l2_attempts'],events=x['event_transitions'],
                    cpu_ms=round(x['cpu_ns']/1e6,3),score=x['best_verified_s_per_mob'])
               for x in r['observations'] if x['tier']=='progress'],
        missed_l0_winner=(None if w is None else sum(
            1 for x in r['observations'] if x.get('tier')=='L2' and
            x.get('status')=='FULL_L2_VERIFIED' and
            x.get('l0_predicted_s',1e10) < w['l0_predicted_s'] and
            x['score_s_per_mob'] > w['score_s_per_mob']+1e-8)),
        source_context=r['source_context'])


def run_case(name, event_cap, *, mode='legacy', l1=False, cache=False):
    r=run_source_stateful_budgeted(class_key='druid',level=20,
        max_l2_attempts=48,max_event_transitions=event_cap,
        use_l1=l1,use_prefix_cache=cache,
        search_guarded_continuations=True,search_mode_paths=True,
        family_budget_mode=mode)
    assert r['event_transitions']<=event_cap and r['l2_attempts']<=48
    return compact(r)


def main(path):
    cases={
        'legacy_4300':run_case('legacy',4300),
        'balanced_4300':run_case('balanced',4300,mode='measured_balanced'),
        'legacy_5000':run_case('legacy',5000),
        'balanced_5000':run_case('balanced',5000,mode='measured_balanced'),
        'balanced_l1_5000':run_case('l1',5000,mode='measured_balanced',l1=True),
        'balanced_cache_5000':run_case('cache',5000,mode='measured_balanced',cache=True),
    }
    gear=run_source_budgeted_gear(class_key='druid',level=20,
        max_evaluations=75,initial_search=24,search_per_gear=16,max_gear_states=2,
        policy_search_backend='stateful',stateful_use_l1=False,
        stateful_search_guarded_continuations=True,stateful_search_mode_paths=True,
        stateful_family_budget_mode='measured_balanced',
        probe_stats=('agility','strength','stamina'),max_event_transitions=12000)
    joint=run_source_budgeted_joint_talents(class_key='druid',level=20,
        max_evaluations=80,evaluations_per_talent=48,initial_search=18,
        search_per_gear=12,max_gear_states=1,policy_search_backend='stateful',
        stateful_use_l1=False,stateful_search_guarded_continuations=True,
        stateful_search_mode_paths=True,stateful_family_budget_mode='measured_balanced',
        max_event_transitions=13000)
    def joint_stage(stage):
        return {'stage':stage['stage'],'attempted':stage['attempted'],
                'score_s_per_mob':(stage.get('winner') or {}).get('score_s_per_mob'),
                'family_l2_counts':stage.get('family_l2_counts')}
    report={'version':'0.11.48.281','source':'Forever canonical SQLite Game IR Druid L20',
            'objective':'production generic full combat+recovery+survival scorer',
            'cases':cases,
            'gear':{'status':gear['status'],'attempted':gear['attempted'],
                    'events':gear['event_transitions'],
                    'winner_s_per_mob':gear['winner']['winner']['score_s_per_mob'],
                    'stages':[joint_stage(x) for x in gear['stages']]},
            'talent':{'status':joint['status'],'attempted':joint['attempted'],
                      'events':joint['event_transitions'],
                      'stages':len(joint['stages'])},
            'interpretation':{'family_prior':'explicit heuristic, not mathematical dominance',
                'equal_event_comparison':'4300 cap same scorer, differing number of L2 attempts',
                'full_optimum_proven':False,'full_gear_talent_legality_proven':False,
                'source_effects_changed':False,
                'cache_speedup_claimed':False,
                'legacy_oracle_same_scenario':False}}
    Path(path).write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str))
    for name,x in cases.items():
        print(name, x['l2_attempts'],x['events'],round(x['total_controller_cpu_ms']),x['score_s_per_mob'],x['family_counts'])
    print('gear',report['gear']['winner_s_per_mob'],report['gear']['events'])
    print('joint',report['talent']['attempted'],report['talent']['events'])


if __name__=='__main__':
    import sys
    main(sys.argv[1])
