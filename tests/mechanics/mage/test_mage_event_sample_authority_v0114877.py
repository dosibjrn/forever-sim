from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.v2.mage_class_model import (
    MageClassModel,
    MAGE_EVENT_POOL_SAMPLES,
    MAGE_EVENT_ADJUDICATION_SAMPLES,
)
from src.v2.path_dp import LevelNode


def _setup():
    game_context.configure('forever', 'mage')
    reset_engine_cache()
    mage = get_engine()
    return mage, MageClassModel(mage)


def test_mage_event_sample_sizes_are_large_enough_for_stable_l20_authority(monkeypatch):
    mage, model = _setup()
    assert MAGE_EVENT_POOL_SAMPLES == 32
    assert MAGE_EVENT_ADJUDICATION_SAMPLES == 64
    t = mage.Talents(imp_frostbolt=5, elemental_precision=1, permafrost=1, frostbite=3, ice_lance=1)
    node = LevelNode(20, t, 2000.0, None, 'analytic', {'total_s': 2000.0, 'kill_s': 1200.0, 'recovery_s': 580.0, 'travel_s': 220.0})
    calls = []

    def fake_policy_search(level, talents, cfg, school, *, n, seed):
        calls.append((level, school, n, seed))
        return {'best_found': {
            'mobs_per_hour': 180.0,
            'kill_seconds_per_mob': 12.0,
            'recovery_seconds_per_mob': 5.8,
            'travel_seconds_per_mob': 2.2,
            'rotation': 'stable-event-rotation',
        }}

    monkeypatch.setattr(mage, 'policy_search', fake_policy_search)
    pools = model.rerank_repaired_pools({20: [node]}, mage.SimConfig())
    assert pools[20][0].details['event_structural_rerank']['samples'] == 32
    assert calls[-1][2] == 32

    t0 = mage.Talents(imp_frostbolt=5, elemental_precision=3, permafrost=3)
    leader = LevelNode(20, t0, 1900.0, None, 'analytic', {'total_s': 1900.0})
    _, overrides = model.adjudicate_per_level_candidate(20, [leader, node], mage.SimConfig())
    assert overrides['selection_validation']['samples'] == 64
    assert calls[-1][2] == 64
