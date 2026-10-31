from src import classic_mage_leveling_optimizer_v10 as eng
from src import pnp_cache as pnp


def _metrics(n):
    total = float(n * 10)
    return {
        'total_s': total, 'kill_s': total * .8, 'recovery_s': total * .2,
        'mana': float(n), 'pushback_s': 0.0, 'swings': 0.0,
        'total_sq_s': float(n * 100), 'mean_s_per_mob': 10.0,
        'stderr_s_per_mob': 0.0,
    }


def test_pnp_continuation_extends_and_exact_repeat_is_cache_hit(tmp_path, monkeypatch):
    pnp.close_connection()
    monkeypatch.setattr(pnp, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(pnp, 'DB_PATH', tmp_path / 'pnp.sqlite3')
    pnp._DB_READY.clear()
    calls=[]
    def fake_incremental(level, talents, policy, cfg, target_n, seed, hp_mult=1.0, continuation=None):
        start = int((continuation or {}).get('n', 0))
        calls.append((start, int(target_n)))
        return _metrics(int(target_n)), {'n': int(target_n), 'fake': True}
    monkeypatch.setattr(pnp.eng, 'simulate_chain_incremental', fake_incremental)
    talents=eng.Talents(imp_frostbolt=1)
    policy=eng.Policy(name='test', primary='frostbolt')
    cfg=eng.SimConfig()
    seed=pnp.canonical_seed(11)

    a=pnp.evaluate_policy(11,talents,policy,cfg,32,seed)
    assert a['_cache'] == 'miss'
    assert a['_simulated_new_mobs'] == 32
    b=pnp.evaluate_policy(11,talents,policy,cfg,100,seed)
    assert b['_cache'] == 'extend'
    assert b['_extended_from_n'] == 32
    assert b['_simulated_new_mobs'] == 68
    before=list(calls)
    c=pnp.evaluate_policy(11,talents,policy,cfg,100,seed)
    assert c['_cache'] == 'hit'
    assert c['_simulated_new_mobs'] == 0
    assert calls == before
    assert c['total_s'] == b['total_s'] == 1000.0
    assert (32,64) in calls and (64,100) in calls
    pnp.close_connection()
