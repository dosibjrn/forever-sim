from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.rulesets.forever.classes.hunter import mechanics as hm
from src.rulesets.forever.classes.hunter.profile import (
    VERIFIED_LEVEL_CAP, PLANNING_LEVEL_CAP, HUNTER_CAPABILITY_MATRIX, MODEL_FIDELITY,
)
from src.v2.class_model import CandidateResult, Evaluation, LevelFrontier
from src.v2.decision_result import solve_routes, reports
from src.v2.class_model import active_class_model


def _hunter():
    game_context.configure('forever','hunter')
    reset_engine_cache()
    return get_engine()


def test_hunter_has_distinct_verified_and_planning_ceilings():
    e=_hunter()
    assert VERIFIED_LEVEL_CAP == e.VERIFIED_LEVEL_CAP == 20
    assert PLANNING_LEVEL_CAP == e.PLANNING_LEVEL_CAP == 40
    assert MODEL_FIDELITY['verified_level_cap'] == 20
    assert MODEL_FIDELITY['planning_level_cap'] == 40


def test_capability_matrix_is_complete_and_fail_closed_for_known_gaps():
    assert set(HUNTER_CAPABILITY_MATRIX) == {'beast_mastery','marksmanship','survival','shared'}
    assert HUNTER_CAPABILITY_MATRIX['beast_mastery']['summon_hawk_sustained_attacks'] == 'unpriced'
    assert HUNTER_CAPABILITY_MATRIX['marksmanship']['ammo_quiver_haste'] == 'unmodeled'
    assert HUNTER_CAPABILITY_MATRIX['survival']['counterattack_parry_cadence'] == 'unpriced'
    assert HUNTER_CAPABILITY_MATRIX['survival']['strider_kick_mana'] == 'unpriced'
    assert HUNTER_CAPABILITY_MATRIX['shared']['multi_shot_pack_leveling'] == 'unmodeled'


def test_post20_scorer_labels_planning_range_without_claiming_verification():
    e=_hunter()
    row=hm.experimental_level_score(30,e.Talents(),profile='marksmanship')
    assert row['verified_level_cap'] == 20
    assert row['planning_level_cap'] == 40
    assert row['post20_fallback'] == 'hunter_l21_l40_planning_range_source_backed_bounded'
    flags=' '.join(row.get('approximation_flags') or [])
    assert 'provisional Hunter planning range L21-L40' in flags
    assert 'reassessed in I07' not in flags


def test_decision_report_surfaces_hunter_fidelity_and_planning_status():
    e=_hunter(); model=active_class_model()
    t=e.Talents()
    fronts=[]
    for lvl in (20,30):
        raw=hm.experimental_level_score(lvl,t,profile='marksmanship')
        ev=Evaluation.from_raw(raw)
        c=CandidateResult(level=lvl,build=t,loadout=None,policy=raw.get('rotation','—'),evaluation=ev,metadata={
            'publication_row': {'level':lvl, **ev.published_fields(), 'allocation':'', 'talent_family':'marksmanship', 'combat_profile':'marksmanship', 'model_fidelity':MODEL_FIDELITY}
        })
        fronts.append(LevelFrontier(level=lvl,candidates=(c,)))
    result=solve_routes(fronts,model=model,class_name='hunter',targets=(20,30))
    route,_=reports(result,verified_level_cap=20)
    assert route['verified_level_cap'] == 20
    assert route['planning_level_cap'] == 40
    assert route['model_fidelity']['capability_matrix']['survival']['melee_trap_policy'] == 'source_backed_bounded'
    assert route['targets']['20']['planning_status'] == 'verified_range'
    assert route['targets']['30']['planning_status'] == 'provisional_planning_range'
    assert route['targets']['30']['uses_unverified_levels'] is True
    assert route['targets']['30']['uses_levels_above_planning_cap'] is False
