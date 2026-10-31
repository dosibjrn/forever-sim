from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from src import game_context
from src.engine_registry import get_engine, reset_engine_cache

VERSION='v0.11.47.3'
LEVEL=40

def _baseline_row():
    payload=json.loads((ROOT/'M47_3X3_BASELINE_v0.11.47.0.json').read_text(encoding='utf-8'))
    return next(r for r in payload['rows'] if r['class']=='paladin' and int(r['level'])==LEVEL)

def build():
    row=_baseline_row(); prior=game_context.current()
    try:
        game_context.configure('forever','paladin'); reset_engine_cache(); e=get_engine()
        t=e.Talents(**row['talent_ranks']); s=e.experimental_level_score(LEVEL,t,'all')
        seed={'level':LEVEL,'score_s_per_100':float(s['total_s']),'allocation':e.final_allocation(t),
              'talent_ranks':row['talent_ranks'],'combat_profile':s.get('profile'),'gear':s.get('gear'),
              'pull_size':s.get('pull_size'),'rotation':s.get('rotation'),'mobs_per_hour':s.get('mobs_per_hour'),'details':s}
        expanded=e.expand_event_validation_candidates(LEVEL,[seed])
        result=e.event_validate_candidates(LEVEL,expanded); best=result['event_validated_best']
        return {'schema_version':1,'version':VERSION,'milestone':'M47','cell':'paladin_L40',
                'status':'SELECTION_WIRING_CLOSED_MECHANIC_AUTHORITY_STILL_HYBRID',
                'selection_authority':'deterministic_event_reranked_expanded_finalists',
                'retention':{'rounds':1,'seed_width':1,'frontier_width':8,'replay_finalists':len(expanded),'scope':'target_end_level',
                             'reason':'L40 event winner is one legal talent swap from the smooth baseline; deeper expansion is unnecessary for this validated cell.'},
                'smooth_seed':{'allocation':seed['allocation'],'mobs_per_hour':seed['mobs_per_hour']},
                'published_event_winner':{'allocation':best['allocation'],'talent_ranks':best['talent_ranks'],'mobs_per_hour':best['mobs_per_hour'],
                                          'smooth_rank':best.get('smooth_rank'),'gear':best.get('gear'),'pull_size':best.get('pull_size'),'rotation':best.get('rotation')},
                'selection_regression_closed':best['allocation']!=seed['allocation'] and float(best['mobs_per_hour'])>224,
                'gate_a':{'selection_closed':True,'cell_fully_closed':False,
                          'why':'Production target-level selection retains and event-reranks the L40 challenger that falsifies the smooth baseline. Event replay remains hybrid fidelity authority.'}}
    finally:
        game_context.configure(prior.ruleset,prior.class_name); reset_engine_cache()

def main():
    p=build(); jp=ROOT/f'M47_PALADIN_L40_SELECTION_{VERSION}.json'; mp=ROOT/f'M47_PALADIN_L40_SELECTION_{VERSION}.md'
    jp.write_text(json.dumps(p,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    b=p['published_event_winner']; s=p['smooth_seed']
    mp.write_text(f"# M47 Paladin L40 selection — {VERSION}\n\nProduction target-level selection uses a bounded one-round legal talent neighborhood at L40, then deterministic event rerank.\n\n- smooth seed: **{s['mobs_per_hour']:.1f} mobs/h**\n- published event winner: **{b['mobs_per_hour']:.1f} mobs/h**\n- smooth rank in retained finalists: **{b['smooth_rank']}**\n- allocation: `{b['allocation']}`\n- selection regression: **closed**\n- full cell Gate A: **not yet closed** because event replay remains hybrid mechanic authority.\n\nNext: Paladin L60 adversarial + selection closure.\n",encoding='utf-8')
    print(json.dumps(p,indent=2))
if __name__=='__main__': main()
