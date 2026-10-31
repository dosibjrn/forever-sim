"""Measured identical 29-policy real Cat L27 replay; no synthetic scorer."""
from __future__ import annotations
import json
from pathlib import Path
from time import process_time_ns, perf_counter_ns
from statistics import median
from src.game.data.forever.registry import build_game_ir_slice
from src.game.gear import apply_gear_selection
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.runtime.simulator import CombatRuntime
from src.rulesets.forever.items.runtime_selection import available_items,item_payload,item_vector,effective_level
from src.v2.source_policy_search import synthesize_source_policies

source=build_game_ir_slice(class_key='druid',level=27)
item=next(i for i in available_items('druid',27,required_level_policy='observed') if i.item_id==3203)
ir,_=apply_gear_selection(source,aggregate_stats=item_vector(item),
    selected_items=(item_payload(item,display_slot='weapon',effective_level=effective_level(item)),),
    source='canonical_sqlite_forever_catalogue')
env=synthesize_source_policies(ir,level=27,max_policies=28,include_auto_resource_fallback=True,
    mode_id='cat',budget_mode='balanced_frontier')
cat=next(p for p in ir.policies if 'cat-builder-finisher' in p.id)
cases=[cat,*env['policies']]
original_init=CombatRuntime.__init__
instances=[]
def tracked_init(self,*args,**kwargs):
    original_init(self,*args,**kwargs)
    instances.append(self)
CombatRuntime.__init__=tracked_init
runs=[]
try:
    for _ in range(3):
        instances.clear()
        scores=[];failed=[]
        cpu_start=process_time_ns();wall_start=perf_counter_ns()
        for policy in cases:
            try:
                result=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=27,
                    target_health=484,count=3,pre_combat_action_ids=('cat_form:768',),
                    post_combat_action_ids=('cancel_mode:cat',),
                    prepared_first_pull_resources={'energy':100,'rage':0},
                    recovery_mode='threshold',retain_mode_between_pulls=True,
                    travel_time_s=2.2,apply_target_defense=True)
                scores.append((policy.id,result.seconds_per_mob,
                    json.dumps([(rule.action_id,[c.as_dict() for c in rule.conditions],rule.phase)
                        for rule in policy.rules],sort_keys=True)))
            except (ValueError,RuntimeError) as exc:
                failed.append((policy.id,str(exc)))
        runs.append({'cpu_ms':(process_time_ns()-cpu_start)/1e6,
                     'wall_ms':(perf_counter_ns()-wall_start)/1e6,
                     'events':sum(r.event_transitions for r in instances),
                     'full_sim_attempts':len(cases),'successful':len(scores),
                     'failed':failed,'scores':sorted(scores,key=lambda x:(x[1],x[0]))})
finally:
    CombatRuntime.__init__=original_init
report={'scope':'L27 named weapon, same real full combat+recovery+survival scoring; 29 bounded candidates',
        'cpu_ms_median':median(x['cpu_ms'] for x in runs),
        'wall_ms_median':median(x['wall_ms'] for x in runs),
        'events':runs[0]['events'],
        'full_sim_attempts':len(cases),
        'failed':runs[0]['failed'],
        'winner':runs[0]['scores'][0],
        'runnerup':runs[0]['scores'][1],
        'identical_runs':all(x['scores']==runs[0]['scores'] and x['events']==runs[0]['events'] for x in runs),
        'runs':runs}
path=Path(__file__).resolve().parents[1]/'WF271_REAL_MELEE_PARITY.json'
path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='runs'},indent=2))
