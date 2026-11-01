"""Real executor three-pull validation for source-ranked periodic finishers."""
from __future__ import annotations
import json
from pathlib import Path
from statistics import median
from time import process_time_ns,perf_counter_ns
from src.game.data.forever.registry import build_game_ir_slice
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.runtime.simulator import CombatRuntime


def measure(level,hp):
    ir=build_game_ir_slice(class_key='druid',level=level)
    policy=next(p for p in ir.policies if 'cat-builder-finisher' in p.id)
    rip=next(a for a in ir.actions if a.family_key=='rip')
    instances=[];old_init=CombatRuntime.__init__
    def track(self,*a,**kw):
        old_init(self,*a,**kw);instances.append(self)
    CombatRuntime.__init__=track
    runs=[]
    try:
        for _ in range(5):
            instances.clear();cpu=process_time_ns();wall=perf_counter_ns()
            result=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=level,
                target_health=hp,count=3,pre_combat_action_ids=('cat_form:768',),
                post_combat_action_ids=('cancel_mode:cat',),
                prepared_first_pull_resources={'energy':100,'rage':0},
                recovery_mode='threshold',retain_mode_between_pulls=True,
                travel_time_s=2.2,apply_target_defense=True)
            runs.append({'cpu_ms':(process_time_ns()-cpu)/1e6,
                         'wall_ms':(perf_counter_ns()-wall)/1e6,
                         'events':sum(r.event_transitions for r in instances),
                         'seconds_per_mob':result.seconds_per_mob})
    finally:CombatRuntime.__init__=old_init
    return {'level':level,'policy_id':policy.id,'rip_action':rip.id,
            'source_spell_id':rip.provenance[0].get('source_spell_id'),
            'score_s_per_mob':runs[0]['seconds_per_mob'],
            'events':runs[0]['events'],
            'cpu_ms_median':median(x['cpu_ms'] for x in runs),
            'wall_ms_median':median(x['wall_ms'] for x in runs),
            'deterministic':len({(x['events'],x['seconds_per_mob']) for x in runs})==1,
            'full_sim_attempts':5,'runs':runs}

if __name__=='__main__':
    report={'scorer':'evaluate_repeated_pulls real combat+recovery+survival',
            'scenario':'three consecutive mobs, full Energy first mob, target defense on',
            'results':[measure(l,hp) for l,hp in ((20,360),(27,484),(28,500),(36,800),(44,1000),(52,1300),(60,1500))],
            'caveat':'AP/periodic crit semantics not yet normalized; not a validated checkpoint'}
    Path('WF272_REAL_RIP_MULTI_PULL.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
