from src import pnp_cache


def test_chain_state_codec_preserves_extended_barrier_continuation_tuple():
    # PnP continuation is intentionally length-agnostic: v0.9.1 extends the
    # historical cooldown tuple with Barrier absorb + remaining aura duration.
    import random
    rng=random.Random(123)
    state={
        'n':32,'rng_state':rng.getstate(),
        'cooldowns':(1.0,2.0,3.0,4.0,0.0,1.0,2.0,7.0,321.5,28.25),
        'total_s':100.0,'kill_s':80.0,'recovery_s':20.0,'mana':50.0,
        'pushback_s':3.0,'swings':4.0,'total_sq_s':400.0,'casts':{'frostbolt':9},
    }
    got=pnp_cache.decode_chain_state(pnp_cache.encode_chain_state(state))
    assert got['n'] == 32
    assert got['cooldowns'] == state['cooldowns']
    assert got['rng_state'] == state['rng_state']


def test_barrier_incremental_extension_matches_fresh_chain_bit_for_bit():
    from tests.test_ice_barrier import _barrier_prereq_30, _pure_frost
    from src import classic_mage_leveling_optimizer_v10 as eng
    talents=eng.add_point(_barrier_prereq_30(),'ice_barrier')
    policy=_pure_frost(barrier=True)
    cfg=eng.SimConfig(use_best_water=True,generic_melee_hit_hp_frac=.03)
    a,state=eng.simulate_chain_incremental(40,talents,policy,cfg,target_n=8,seed=91)
    extended,state16=eng.simulate_chain_incremental(40,talents,policy,cfg,target_n=16,seed=91,
                                                   continuation=state)
    fresh,fresh_state=eng.simulate_chain_incremental(40,talents,policy,cfg,target_n=16,seed=91)
    assert extended == fresh
    assert state16 == fresh_state
