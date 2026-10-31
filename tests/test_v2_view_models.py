from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.path_dp import LevelNode, PathStep, PathResult
from src.v2 import view_models


def test_node_view_model_uses_shared_presentation():
    t = eng.Talents(arcane_filler=3, imp_fireball=3)
    n = LevelNode(20, t, 600.0, None, 'fixture', {'x': 1})
    out = view_models.node_json(n)
    assert out['family'] == 'arcane+fire'
    assert out['tree_points'] == {'frost': 0, 'arcane': 3, 'fire': 3}
    assert out['min_per_100'] == 10.0


def test_path_view_model_is_pure_and_complete():
    t11 = eng.Talents(imp_frostbolt=2)
    n = LevelNode(11, t11, 2400.0, eng.Policy('x','frostbolt',use_fireblast=False,use_nova=False,use_blink=False), 'fixture')
    step = PathStep(n, 'start', None, 0, 2400.0)
    path = PathResult((step,), 2400.0, 0, 11)
    out = view_models.path_json(path)
    assert out['hours'] == 2400.0/3600.0
    assert out['steps'][0]['policy'] == eng.policy_desc(n.policy, 11)
    assert out['final_allocation'] == eng.final_allocation(t11)


def test_node_view_model_surfaces_stat_weights_at_top_level_for_listener_parity():
    t = eng.Talents(imp_frostbolt=2)
    sw = {"method": "fixture", "stats": {"intellect": {"normalized_to_reference": 0.5}}}
    n = LevelNode(11, t, 2400.0, None, 'fixture', {'stat_weights': sw})
    out = view_models.node_json(n)
    assert out['stat_weights'] == sw
    assert out['details']['stat_weights'] == sw
