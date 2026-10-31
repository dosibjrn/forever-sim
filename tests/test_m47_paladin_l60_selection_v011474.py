import json
from pathlib import Path
from src import game_context
from src.engine_registry import get_engine,reset_engine_cache
ROOT=Path(__file__).resolve().parents[1]

def _baseline_candidate(e):
 p=json.loads((ROOT/'M47_3X3_BASELINE_v0.11.47.0.json').read_text());r=next(x for x in p['rows'] if x['class']=='paladin' and x['level']==60);t=e.Talents(**r['talent_ranks']);s=e.experimental_level_score(60,t,'all');return {'level':60,'score_s_per_100':float(s['total_s']),'allocation':e.final_allocation(t),'talent_ranks':r['talent_ranks'],'combat_profile':s.get('profile'),'gear':s.get('gear'),'pull_size':s.get('pull_size'),'rotation':s.get('rotation'),'mobs_per_hour':s.get('mobs_per_hour'),'details':s}

def test_paladin_l60_one_round_retention_recovers_event_stable_winner():
 prior=game_context.current()
 try:
  game_context.configure('forever','paladin');reset_engine_cache();e=get_engine();base=_baseline_candidate(e);expanded=e.expand_event_validation_candidates(60,[base]);assert len(expanded)==24;out=e.event_validate_candidates(60,expanded);best=out['event_validated_best'];assert best is not None;assert best['allocation']!=base['allocation'];assert best['mobs_per_hour']>221.7;assert best['smooth_rank']>1
 finally:
  game_context.configure(prior.ruleset,prior.class_name);reset_engine_cache()

def test_l60_artifacts_record_selection_closed_but_mechanic_authority_open():
 p=json.loads((ROOT/'M47_PALADIN_L60_SELECTION_v0.11.47.4.json').read_text());a=json.loads((ROOT/'M47_PALADIN_L60_ADVERSARIAL_v0.11.47.4.json').read_text());assert p['selection_regression_closed'] is True;assert p['gate_a']['cell_fully_closed'] is False;assert a['profiles']['retribution']['event_best']['event_mobs_per_hour']>a['profiles']['protection']['event_best']['event_mobs_per_hour'];assert a['classification']['smooth_vs_event']=='mechanic_fidelity_gap'
