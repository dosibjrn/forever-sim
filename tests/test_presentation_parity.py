from types import SimpleNamespace

from src import classic_mage_leveling_optimizer_v10 as eng
from src import pnp_cache, state_manager
from src.v2 import runner


def test_display_family_is_identical_fast_mc_and_cache_for_hybrid_tie():
    t = eng.Talents(arcane_filler=3, imp_fireball=3)
    s_school, s_family = state_manager._talent_school_family(t)
    p_school, p_family = pnp_cache._talent_school_family(t)
    node = SimpleNamespace(level=20, talents=t, policy=None, score_s_per_100=1.0, source='x', details={})
    fast = runner._node_json(node)
    assert s_family == p_family == fast['family']
    assert s_school == p_school
    assert fast['tree_points'] == {'frost': 0, 'arcane': 3, 'fire': 3}
    assert '+' in fast['family'], 'hybrid tie must not render as a pure tree'


def test_display_family_uses_secondary_tree_once_material():
    t = eng.Talents(imp_frostbolt=5, arcane_filler=5, imp_fireball=1)
    _, fam = state_manager._talent_school_family(t)
    assert fam == 'arcane+frost' or fam == 'frost+arcane'
