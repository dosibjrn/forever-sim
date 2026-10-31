import json
from pathlib import Path
from src import game_context
from src.engine_registry import get_engine, reset_engine_cache

ROOT=Path(__file__).resolve().parents[1]

def _baseline_candidate(engine):
    payload=json.loads((ROOT/'M47_3X3_BASELINE_v0.11.47.0.json').read_text(encoding='utf-8'))
    row=next(r for r in payload['rows'] if r['class']=='paladin' and int(r['level'])==40)
    t=engine.Talents(**row['talent_ranks']); score=engine.experimental_level_score(40,t,'all')
    return {'level':40,'score_s_per_100':float(score['total_s']),'allocation':engine.final_allocation(t),
            'talent_ranks':row['talent_ranks'],'combat_profile':score.get('profile'),'gear':score.get('gear'),
            'pull_size':score.get('pull_size'),'rotation':score.get('rotation'),'mobs_per_hour':score.get('mobs_per_hour'),'details':score}

def test_paladin_l40_one_round_retention_recovers_event_stable_winner():
    prior=game_context.current()
    try:
        game_context.configure('forever','paladin'); reset_engine_cache(); e=get_engine()
        baseline=_baseline_candidate(e)
        expanded=e.expand_event_validation_candidates(40,[baseline])
        assert len(expanded) == 24
        out=e.event_validate_candidates(40,expanded); best=out['event_validated_best']
        assert best is not None
        assert best['talent_ranks']=={
            'deflection':5,'benediction':5,'improved_judgement':2,'holy_conduit':2,
            'conviction':5,'vindication':2,'sanctified_judgement':3,'seal_of_command':1,
            'pursuit_of_justice':2,'eye_for_an_eye':1,'crusade':2,'two_handed_weapon_specialization':1,
        }
        assert best['mobs_per_hour'] > 224
        assert best['allocation'] != baseline['allocation']
    finally:
        game_context.configure(prior.ruleset,prior.class_name); reset_engine_cache()
