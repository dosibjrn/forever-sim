import json

from src import game_context, listener
from src.engine_registry import get_engine, reset_engine_cache
from src.v2 import decision_dashboard
from src.v2.experimental_classes import _BeamRow, _candidate_json, _merge_event_winner


def test_event_overlay_preserves_rich_paladin_metadata():
    rich={
        'mobs_per_hour':297.5,
        'stat_weights':{'stats':{'strength':{'seconds_saved_per_100_per_point':1.2}}},
        'gear':'canonical_sqlite_paladin_retribution',
        'gear_stats':{'slots':{'weapon':{'name':'Rich weapon'}}},
        'gear_fixed_point':{'converged':True,'iterations':2},
        'details':{'stat_weights':{'stats':{'strength':{}}}},
    }
    event={
        'mobs_per_hour':341.2,
        'score_s_per_100':1055.1,
        'stat_weights':None,
        'gear_stats':None,
        'gear':None,
        'details':None,
    }
    out=_merge_event_winner(rich,event)
    assert out['mobs_per_hour'] == 341.2
    assert out['stat_weights'] == rich['stat_weights']
    assert out['gear_stats'] == rich['gear_stats']
    assert out['gear_fixed_point']['converged'] is True


def test_real_paladin_l20_candidate_publishes_stat_weights():
    game_context.configure('forever','paladin')
    reset_engine_cache()
    eng=get_engine()
    talents=eng.Talents(deflection=5,benediction=3,conviction=2,seal_of_command=1)
    score=eng.experimental_level_score(20,talents,'all')
    row=_candidate_json(_BeamRow(talents,0.0,score,tuple()),20,include_stat_weights=True,include_envelope=False)
    stats=(row.get('stat_weights') or {}).get('stats') or {}
    assert row.get('stat_weights_error') is None
    assert any(float((v or {}).get('seconds_saved_per_100_per_point') or 0.0) > 0 for v in stats.values())
    assert 'strength' in stats
    assert 'weapon_dps' in stats


def test_decision_payload_declares_all_registry_routes_and_one_per_level_winner(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_dashboard,'CLASSES',('paladin',))
    viewer=tmp_path/'state/games/forever-paladin/v2/viewer.json'
    viewer.parent.mkdir(parents=True)
    winner={
        'level':20,'allocation':'holy(0) / protection(0) / retribution(11)[deflection:5,benediction:3,conviction:2,seal_of_command:1]','talent_ranks':{'deflection':5,'benediction':3,'conviction':2,'seal_of_command':1},
        'tree_points':{'holy':0,'protection':0,'retribution':11},
        'talent_family':'retribution','combat_profile':'retribution',
        'mobs_per_hour':341.2,'score_s_per_100':1055.1,
        'stat_weights':{'stats':{'strength':{'status':'measured','seconds_saved_per_100_per_point':1.0}}},
        'gear':'canonical_sqlite_paladin_retribution','gear_stats':{'slots':{}},
    }
    viewer.write_text(json.dumps({'views':{'experimental':{'level_summaries':[{'level':20,'best':winner}]}}}),encoding='utf-8')
    # Current publication resolution is service-owned. This fixture intentionally
    # supplies one direct viewer, so pin only viewer resolution to that file
    # instead of relying on the pre-publication root/state lookup semantics.
    monkeypatch.setattr(decision_dashboard, 'resolve_published_path', lambda root, rel: viewer)
    payload=decision_dashboard.build_decision_payload(tmp_path,selected_level=20)
    assert payload['per_level_rows']['paladin'][0]['mobs_per_hour'] == 341.2
    assert payload['class_metadata']['paladin']['declared_routes'] == ['holy','protection','retribution']


def test_listener_uses_per_level_rows_for_cross_class_cards_and_registry_routes():
    html=listener.DECISIONS_HTML
    assert 'function perLevelRow(cls,level)' in html
    assert "const r=perLevelRow(cls,lvl)" in html
    assert 'classMeta(cls).declared_routes||[]' in html
    assert "names.push('unconstrained',...(declared.length?declared:[...artifact,...matrix]))" in html
    assert 'Class comparison · L${lvl} · per-level fastest' in html


def test_paladin_declared_unlock_corridors_survive_bounded_selection():
    from src.v2.experimental_classes import _select_diverse
    game_context.configure('forever','paladin')
    reset_engine_cache()
    eng=get_engine()
    rows=[]
    def add(t, score):
        rows.append(_BeamRow(t, float(score), {'total_s':float(score)}, tuple()))
    # Strong deep-tree decoys that would otherwise dominate family/depth lanes.
    add(eng.Talents(toughness=5,redoubt=5), 10)
    add(eng.Talents(deflection=5,benediction=5), 11)
    add(eng.Talents(divine_strength=5,divine_intellect=5), 12)
    # More globally attractive unique rows.
    for i, field in enumerate(['healing_light','spiritual_focus','improved_seals','unyielding_faith','voice_of_truth','reverence','purifying_power','precision','anticipation']):
        add(eng.Talents(**{field:1}), 20+i)
    # Deliberately poor route-defining unlocks. Registry-corridor preservation
    # must retain them despite a small beam.
    prot=eng.Talents(improved_seal_of_fury=1)
    ret=eng.Talents(seal_of_command=1)
    add(prot, 999)
    add(ret, 1000)
    kept=_select_diverse(rows,width=3,family_keep=1)
    assert any(getattr(r.talents,'improved_seal_of_fury',0) >= 1 for r in kept)
    assert any(getattr(r.talents,'seal_of_command',0) >= 1 for r in kept)


def test_publication_boundary_rehydrates_missing_paladin_stat_weights():
    from src.v2.experimental_classes import _ensure_summary_best_stat_weights
    game_context.configure('forever','paladin'); reset_engine_cache(); eng=get_engine()
    t=eng.Talents(deflection=5,benediction=3,conviction=2,seal_of_command=1)
    # Mimic a replay/minimal serializer row that kept the winner identity but
    # dropped rich gearing derivatives.
    summary={'level':20,'best':{
        'level':20,'talent_ranks':{k:int(getattr(t,k)) for k in t.__dataclass_fields__ if int(getattr(t,k))},
        'allocation':eng.final_allocation(t),'combat_profile':'retribution','mobs_per_hour':341.2,
    }}
    out=_ensure_summary_best_stat_weights(summary,20)
    row=out['best']; stats=(row.get('stat_weights') or {}).get('stats') or {}
    assert row.get('stat_weights_error') is None
    assert float(stats['strength']['seconds_saved_per_100_per_point']) > 0
    assert float(stats['weapon_dps']['seconds_saved_per_100_per_point']) > 0


def test_decision_payload_preserves_real_paladin_weight_schema_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(decision_dashboard,'CLASSES',('paladin',))
    game_context.configure('forever','paladin'); reset_engine_cache(); eng=get_engine()
    t=eng.Talents(deflection=5,benediction=3,conviction=2,seal_of_command=1)
    score=eng.experimental_level_score(20,t,'all')
    rich=_candidate_json(_BeamRow(t,0.0,score,tuple()),20,include_stat_weights=True,include_envelope=False)
    viewer=tmp_path/'state/games/forever-paladin/v2/viewer.json'; viewer.parent.mkdir(parents=True)
    viewer.write_text(json.dumps({'views':{'experimental':{'level_summaries':[{'level':20,'best':rich}]}}}),encoding='utf-8')
    payload=decision_dashboard.build_decision_payload(tmp_path,selected_level=20)
    row=payload['per_level_rows']['paladin'][0]
    stats=(row.get('stat_weights') or {}).get('stats') or {}
    assert float(stats['strength']['seconds_saved_per_100_per_point']) > 0
    assert float(stats['weapon_dps']['seconds_saved_per_100_per_point']) > 0
