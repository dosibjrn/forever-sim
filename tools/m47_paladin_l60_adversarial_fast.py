from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from src import game_context
from src.engine_registry import get_engine,reset_engine_cache
from tools.m47_3x3_baseline import _reachable,_neighbors,_family_corridor,_key,_ranks
from src.rulesets.forever.classes.paladin.validation_report import validate_candidate
VERSION='v0.11.47.4';LEVEL=60

def build():
 p=json.loads((ROOT/'M47_3X3_BASELINE_v0.11.47.0.json').read_text()); base=next(r for r in p['rows'] if r['class']=='paladin' and r['level']==LEVEL); prior=game_context.current()
 try:
  game_context.configure('forever','paladin');reset_engine_cache();e=get_engine(); bt=_reachable(e,base['talent_ranks']); bs=e.experimental_level_score(LEVEL,bt,'retribution'); bev=validate_candidate(LEVEL,bt,bs)
  ret_c=[bt]+_neighbors(e,bt,40); ret=[]
  for t in ret_c:
   s=e.experimental_level_score(LEVEL,t,'retribution'); ret.append((float(s['total_s']),_key(t),t,s))
  ret.sort(key=lambda x:(x[0],x[1])); ret_ev=[]
  for rank,(_,_,t,s) in enumerate(ret[:8],1):
   ev=validate_candidate(LEVEL,t,s);ret_ev.append((float(ev['event_adjusted_mobs_per_hour']),rank,t,s,ev))
  ret_ev.sort(key=lambda x:(-x[0],x[1])); rb=ret_ev[0]
  pt=_family_corridor(e,LEVEL,'protection'); prot_c=[pt]+_neighbors(e,pt,40); prot=[]
  for t in prot_c:
   s=e.experimental_level_score(LEVEL,t,'protection');prot.append((float(s['total_s']),_key(t),t,s))
  prot.sort(key=lambda x:(x[0],x[1])); prot_ev=[]
  for rank,(_,_,t,s) in enumerate(prot[:8],1):
   ev=validate_candidate(LEVEL,t,s);prot_ev.append((float(ev['event_adjusted_mobs_per_hour']),rank,t,s,ev))
  prot_ev.sort(key=lambda x:(-x[0],x[1])); pb=prot_ev[0]
  return {'schema_version':1,'version':VERSION,'milestone':'M47','cell':'paladin_L60','status':'ADVERSARIAL_CHECK_COMPLETE_SELECTION_CLOSED_MECHANIC_AUTHORITY_OPEN','authority':'bounded_one_swap_plus_hybrid_event_replay_diagnostic','search':{'ret_neighbors':len(ret_c),'prot_neighbors':len(prot_c),'event_top_n_per_profile':8},'baseline':{'smooth_mobs_per_hour':float(bs['mobs_per_hour']),'event_mobs_per_hour':float(bev['event_adjusted_mobs_per_hour']),'event_delta_pct':float(bev['throughput_delta_pct']),'talent_ranks':_ranks(bt)},'profiles':{'retribution':{'event_best':{'event_mobs_per_hour':rb[0],'smooth_rank':rb[1],'allocation':e.final_allocation(rb[2]),'talent_ranks':_ranks(rb[2]),'smooth_mobs_per_hour':float(rb[3]['mobs_per_hour'])}},'protection':{'event_best':{'event_mobs_per_hour':pb[0],'smooth_rank':pb[1],'allocation':e.final_allocation(pb[2]),'talent_ranks':_ranks(pb[2]),'smooth_mobs_per_hour':float(pb[3]['mobs_per_hour'])}}},'classification':{'baseline_selection':'search_failure_closed_by_production_event_rerank','smooth_vs_event':'mechanic_fidelity_gap','ret_vs_prot':'expected_objective_difference_provisionally_supported','ret_vs_prot_event_margin_pct':(rb[0]/pb[0]-1)*100},'gate_a':{'selection_closed':True,'cell_fully_closed':False,'why':'L60 production retention recovers the falsifying Ret challenger; hybrid event replay remains non-final mechanic authority.'}}
 finally:
  game_context.configure(prior.ruleset,prior.class_name);reset_engine_cache()

def main():
 q=build(); jp=ROOT/f'M47_PALADIN_L60_ADVERSARIAL_{VERSION}.json'; mp=ROOT/f'M47_PALADIN_L60_ADVERSARIAL_{VERSION}.md'; jp.write_text(json.dumps(q,indent=2,sort_keys=True)+'\n'); r=q['profiles']['retribution']['event_best'];p=q['profiles']['protection']['event_best'];b=q['baseline'];mp.write_text(f"# M47 Paladin L60 adversarial check — {VERSION}\n\n- baseline Ret: **{b['smooth_mobs_per_hour']:.1f} smooth → {b['event_mobs_per_hour']:.1f} event mobs/h**\n- bounded Ret event winner: **{r['event_mobs_per_hour']:.1f}** (smooth rank {r['smooth_rank']})\n- forced deep-Prot event winner: **{p['event_mobs_per_hour']:.1f}**\n- Ret event margin: **{q['classification']['ret_vs_prot_event_margin_pct']:.1f}%**\n\nSelection failure is closed by production event rerank. Full Gate A remains open because event replay is still hybrid mechanic authority.\n")
 print(json.dumps(q,indent=2))
if __name__=='__main__':main()
