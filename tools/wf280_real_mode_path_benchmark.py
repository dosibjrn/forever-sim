import sys, json, hashlib, sqlite3, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition,PolicyRuleDefinition
from src.v2.source_budgeted_prefix import source_prefix_envelope, ordered_prefix_executed
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
from src.v2.generic_backend import _policy_combat_evaluation

out={'version':'0.11.48.280','source':'canonical SQLite + source IR (unchanged)',
     'objective':'real combat + incoming + recovery + survival seconds_per_mob',
     'claim':'bounded opt-in mode-path canary, NOT Feral completeness or full optimality',
     'cases':[],'tiny_exhaustive_mode_fixture':[]}
for level, attempts, event_budget, use_l1, use_cache in [
 (10,24,3200,False,False),
 (20,24,3200,False,False),
 (20,48,6000,True,False),
 (20,48,6000,True,True)]:
 for enabled in (False,True):
  start_cpu=time.process_time_ns();start_wall=time.monotonic_ns()
  r=run_source_stateful_budgeted(class_key='druid',level=level,
      max_l2_attempts=attempts,max_event_transitions=event_budget,
      use_l1=use_l1,use_prefix_cache=use_cache,
      search_guarded_continuations=True,search_mode_paths=enabled)
  cpu=time.process_time_ns()-start_cpu;wall=time.monotonic_ns()-start_wall
  entries={m['entry'] for m in r.get('available_source_mode_paths',())}
  l2=[x for x in r.get('observations',()) if x.get('tier')=='L2']
  mode_l2=[x for x in l2 if x['prefix'][0] in entries]
  l1=[x for x in r.get('observations',()) if x.get('tier')=='L1']
  row={'class_key':'druid','level':level,'mode_enabled':enabled,
       'use_l1':use_l1,'use_cache':use_cache,
       'attempt_cap':attempts,'event_cap':event_budget,
       'l2_attempts':r.get('l2_attempts'), 'l1_attempts':r.get('l1_attempts'),
       'l0_cpu_ns':r.get('l0_cpu_ns'),
       'event_transitions':r.get('event_transitions'),
       'measured_cpu_ns':cpu,'measured_wall_ns':wall,
       'controller_cpu_ns':r.get('full_run_cpu_ns'),
       'mode_l2_attempts':len(mode_l2),
       'mode_l2_successes':sum(x['status']=='FULL_L2_VERIFIED' for x in mode_l2),
       'mode_l1_attempts':sum(x['prefix'][0] in entries for x in l1),
       'best_score_s_per_mob':r.get('winner',{}).get('score_s_per_mob') if r.get('winner') else None,
       'best_prefix':r.get('winner',{}).get('prefix') if r.get('winner') else None,
       'scratch_verification_matches':[x.get('matches_scratch') for x in r.get('scratch_verification',())],
       'cache_hits_l2':r.get('cache_hits_l2'),
       'mode_outcomes':[{'prefix':x['prefix'],'fallback':x['fallback'],
           'guarded_action':x.get('guarded_action'),'status':x['status'],
           'score_s_per_mob':x.get('score_s_per_mob'),
           'l0_predicted_s':x.get('l0_predicted_s'),
           'l1_predicted_s':x.get('l1_predicted_s'),
           'events':x.get('events'),'cpu_ns':x.get('cpu_ns')}
           for x in mode_l2],
       'score_vs_compute':[{'attempt':x['l2_attempts'],'events':x['event_transitions'],
            'cpu_ns':x['cpu_ns'],'best_s_per_mob':x['best_verified_s_per_mob']}
            for x in r.get('observations',()) if x.get('tier')=='progress'],
       'mode_path_sources':r.get('available_source_mode_paths',()),
       'source_context':r.get('source_context'),
       'blocked_source_semantics':r.get('blocked_source_semantics',[]),
       'source_actions':r.get('source_actions',[])}
  out['cases'].append(row)
  print('case',level,attempts,event_budget,use_l1,use_cache,enabled,'score',row['best_score_s_per_mob'],'events',row['event_transitions'],'cpu_ms',round(cpu/1e6,1),'mode',len(mode_l2),flush=True)

ir=build_game_ir_slice(class_key='druid',level=20)
envelope=source_prefix_envelope(ir,level=20)
for row in envelope['mode_paths']:
 for fallback in row['fillers']:
  for prefix in [(row['entry'],), (row['entry'],fallback)]:
   policy=PolicyDefinition(id='wf280:exhaustive_tiny',label='tiny full-cycle',
       rules=(PolicyRuleDefinition(id='fallback',action_id=fallback),),
       provenance={'search_performed':True})
   start=time.process_time_ns()
   try:
    e,x,d=_policy_combat_evaluation(ir,level=20,policy_override=policy,
       opening_action_ids=prefix,schedule_incoming_attacks=True)
    outcome={'status':'FULL_L2_VERIFIED' if e and x and x.timeline.target_defeated and ordered_prefix_executed(x,prefix) else 'BLOCKED_PREFIX_OR_KILL',
             'score_s_per_mob':float(e.seconds_per_mob) if e and x and x.timeline.target_defeated and ordered_prefix_executed(x,prefix) else None,
             'events':d.get('event_transitions_new') if d else None,
             'reason':x.stopped_reason if x else None}
   except (ValueError,RuntimeError) as exc:
    outcome={'status':'BLOCKED_EXECUTOR','reason':str(exc)}
   out['tiny_exhaustive_mode_fixture'].append({'mode_id':row['mode_id'],'prefix':prefix,
       'fallback':fallback,'cpu_ns':time.process_time_ns()-start,**outcome})

for name in ('forever_abilities.sqlite','items_2026-09-29.sqlite'):
 p=ROOT/'data/forever/catalogue'/name
 conn=sqlite3.connect(p);integrity=conn.execute('PRAGMA integrity_check').fetchone()[0];conn.close()
 out.setdefault('canonical_sqlite',{})[name]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
    'bytes':p.stat().st_size,'integrity_check':integrity}
Path(sys.argv[1] if len(sys.argv)>1 else ROOT/'WF280_REAL_MODE_PATH_BENCHMARK.json').write_text(json.dumps(out,indent=2,default=str))
