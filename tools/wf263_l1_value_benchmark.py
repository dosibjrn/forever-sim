"""WF263 real source-backed ablation; no synthetic oracle or new scorer.

CPU is measured process_time_ns for the *whole* call. Events and L2 attempts
are the engine's charged counts; median CPU across 3 repeated calls is only
indicative and does not imply universal speedup. All variants have identical
hard event and L2 caps, not necessarily identical consumed compute.
"""
import json
from pathlib import Path
from statistics import median
from time import process_time_ns, monotonic_ns
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted


def benchmark():
    cases = [
        ('druid_l10_direct', 'druid', 10, 40, 1500, False),
        ('mage_l20_direct', 'mage', 20, 54, 3900, False),
        ('druid_l10_joint', 'druid', 10, 90, 2900, True),
        ('mage_l20_joint', 'mage', 20, 120, 8500, True),
    ]
    results=[]
    for name, cl, lev, l2cap, evcap, joint in cases:
        for mode in ('legacy','value_gated','off'):
            repeats=[]
            for _ in range(3):
                t0=process_time_ns();w0=monotonic_ns()
                if joint:
                    r=run_source_budgeted_joint_talents(class_key=cl,level=lev,
                        max_evaluations=l2cap,
                        evaluations_per_talent=(38 if cl=='mage' else 36),
                        initial_search=(10 if cl=='mage' else 8),
                        search_per_gear=(10 if cl=='mage' else 8),
                        max_gear_states=2,policy_search_backend='stateful',
                        max_event_transitions=evcap,
                        stateful_use_l1=mode!='off',stateful_l1_mode=mode if mode!='off' else 'value_gated')
                    score=r['winner']['score_s_per_mob'] if r.get('winner') else None
                    l2=r['attempted'];l1=r['stateful_l1_attempts']
                    coverage={'talent_states':r['talent_states_evaluated'],
                              'source_talent_families':r['source_talent_families'],
                              'executable_talent_families':r['executable_talent_families']}
                else:
                    r=run_source_stateful_budgeted(class_key=cl,level=lev,
                        max_l2_attempts=l2cap,max_event_transitions=evcap,
                        use_l1=mode!='off',l1_mode=mode if mode!='off' else 'value_gated')
                    score=r['winner']['score_s_per_mob'] if r.get('winner') else None
                    l2=r['l2_attempts'];l1=r['l1_attempts']
                    coverage={'l0_candidates':r['l0_candidates_generated'],
                              'seed_count':r['seed_count'],
                              'l1_value_evidence':r['l1_value_evidence']}
                repeats.append({'cpu_ns':process_time_ns()-t0,'wall_ns':monotonic_ns()-w0,
                    'events':r['event_transitions'],'l2_attempts':l2,
                    'l1_attempts':l1,'winner_s_per_mob':score,
                    'source_context_sha256':r.get('source_context_sha256',r.get('source_context')),
                    'coverage':coverage})
            results.append({'case':name,'mode':mode,'hard_l2_cap':l2cap,
                'hard_event_cap':evcap,'runs':repeats,
                'median_cpu_ms':median(x['cpu_ns'] for x in repeats)/1e6,
                'median_wall_ms':median(x['wall_ns'] for x in repeats)/1e6,
                'events':repeats[0]['events'],'l1_attempts':repeats[0]['l1_attempts'],
                'l2_attempts':repeats[0]['l2_attempts'],
                'winner_s_per_mob':repeats[0]['winner_s_per_mob'],
                'deterministic_events_scores':len({(x['events'],x['l2_attempts'],x['winner_s_per_mob']) for x in repeats})==1})
    return {'parent':'0.11.48.262','candidate':'0.11.48.263',
            'source':'canonical SQLite + existing source-stateful executor',
            'repetitions':3,'results':results,
            'scope':'bounded real policy and joint talent/gear tests; no global optimum, no 540 checkpoint validation',
            'notes':['L1 predictions never substituted for L2 scores',
                     'equal hard caps, not necessarily equal consumed events or CPU',
                     'process CPU median is not a universal speedup claim',
                     'exact checkpoint cache retained; no new cache performance claim']}

if __name__=='__main__':
    r=benchmark()
    Path('WF263_L1_VALUE_REAL_BENCHMARK.json').write_text(json.dumps(r,indent=2)+'\n')
    for x in r['results']:
        print(f"{x['case']:20} {x['mode']:12} l2={x['l2_attempts']:3} l1={x['l1_attempts']:3} events={x['events']:5} cpu_ms={x['median_cpu_ms']:7.2f} score={x['winner_s_per_mob']}")
