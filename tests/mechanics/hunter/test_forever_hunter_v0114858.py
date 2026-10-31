from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.class_registry import get_definition


def _hunter():
    game_context.configure('forever','hunter'); reset_engine_cache(); return get_engine()


def test_hunter_registered_as_visible_l20_class():
    d=get_definition('forever','hunter')
    assert d.display_name == 'Hunter'
    assert d.tree_names == ('beast_mastery','marksmanship','survival')
    assert d.proof_only is False
    assert d.capabilities.named_gear is True
    assert d.route_definitions.keys() == {'beast_mastery','marksmanship','survival'}


def test_hunter_l20_three_tree_corridors_are_legal():
    e=_hunter()
    for names in (
        ['deadly_aspects']*5 + ['endurance_training']*5 + ['bestial_swiftness'],
        ['lethal_attacks']*5 + ['careful_aim']*5 + ['lone_wolf'],
        ['improved_tracking']*5 + ['survivalist']*5 + ['surefooted'],
    ):
        t=e.Talents()
        for name in names:
            assert e.legal_add(t,name)
            t=e.add_point(t,name)
        assert t.points() == 11
        row=e.experimental_level_score(20,t,'all')
        assert row['mobs_per_hour'] > 0
        assert row['total_s'] > 0


def test_lone_wolf_creates_real_pet_vs_no_pet_choice():
    e=_hunter(); t=e.Talents(lethal_attacks=5,careful_aim=5,lone_wolf=1)
    row=e.experimental_level_score(20,t,'marksmanship')
    assert row['profile'] in {'pet_ranged','lone_wolf_ranged'}
    assert row['combat_profile'] == 'ranged'
    assert row['gear_stats']['ranged_attack_power'] > 0


def test_hunter_stat_weights_are_nonempty():
    e=_hunter(); t=e.Talents(lethal_attacks=5,careful_aim=5,lone_wolf=1)
    base=e.experimental_level_score(20,t,'all')
    sw=e.marginal_stat_weights(20,t,'all',base)
    stats=sw.get('stats') or sw.get('weights') or {}
    assert any(float((v or {}).get('seconds_saved_per_100_per_point',0) or 0)>0 for v in stats.values())
