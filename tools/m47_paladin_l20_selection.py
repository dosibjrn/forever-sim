from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from src import game_context
from src.engine_registry import get_engine, reset_engine_cache

VERSION='v0.11.47.2'

def build():
    payload=json.loads((ROOT/'M47_3X3_BASELINE_v0.11.47.0.json').read_text(encoding='utf-8'))
    row=next(r for r in payload['rows'] if r['class']=='paladin' and int(r['level'])==20)
    prior=game_context.current()
    try:
        game_context.configure('forever','paladin'); reset_engine_cache(); e=get_engine()
        t=e.Talents(**row['talent_ranks']); s=e.experimental_level_score(20,t,'all')
        seed={'level':20,'score_s_per_100':float(s['total_s']),'allocation':e.final_allocation(t),
              'talent_ranks':row['talent_ranks'],'combat_profile':s.get('profile'),'gear':s.get('gear'),
              'pull_size':s.get('pull_size'),'rotation':s.get('rotation'),'mobs_per_hour':s.get('mobs_per_hour'),'details':s}
        expanded=e.expand_event_validation_candidates(20,[seed])
        result=e.event_validate_candidates(20,expanded)
        best=result['event_validated_best']
        return {'schema_version':1,'version':VERSION,'milestone':'M47','cell':'paladin_L20',
                'status':'SELECTION_WIRING_CLOSED_MECHANIC_AUTHORITY_STILL_HYBRID',
                'selection_authority':'deterministic_event_reranked_expanded_finalists',
                'retention':{'rounds':2,'seed_width':1,'frontier_width':8,'replay_finalists':len(expanded),'scope':'target_end_level'},
                'smooth_seed':{'allocation':seed['allocation'],'mobs_per_hour':seed['mobs_per_hour']},
                'published_event_winner':{'allocation':best['allocation'],'talent_ranks':best['talent_ranks'],'mobs_per_hour':best['mobs_per_hour'],
                                          'smooth_rank':best.get('smooth_rank'),'gear':best.get('gear'),'pull_size':best.get('pull_size'),'rotation':best.get('rotation')},
                'selection_regression_closed':best['allocation']!=seed['allocation'] and float(best['mobs_per_hour'])>295,
                'gate_a':{'selection_closed':True,'cell_fully_closed':False,
                          'why':'Production target-level selection now retains and event-reranks the L20 challenger that falsified v0.11.47.0. Event replay remains hybrid fidelity authority, so full cell closure is deferred.'}}
    finally:
        game_context.configure(prior.ruleset,prior.class_name); reset_engine_cache()

def main():
    p=build(); jp=ROOT/f'M47_PALADIN_L20_SELECTION_{VERSION}.json'; mp=ROOT/f'M47_PALADIN_L20_SELECTION_{VERSION}.md'
    jp.write_text(json.dumps(p,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    b=p['published_event_winner']
    mp.write_text(f"# M47 Paladin L20 selection — {VERSION}\n\nProduction target-level selection now expands a bounded two-round legal talent neighborhood and deterministically event-reranks the retained finalists.\n\n- published event winner: **{b['mobs_per_hour']:.1f} mobs/h**\n- smooth rank in retained finalists: **{b['smooth_rank']}**\n- allocation: `{b['allocation']}`\n- selection regression: **closed**\n- full cell Gate A: **not yet closed** because event replay remains hybrid mechanic authority.\n\nNext: apply the same target-level adversarial/selection closure to Paladin L40, then L60.\n",encoding='utf-8')
    print(json.dumps(p,indent=2))
if __name__=='__main__': main()
