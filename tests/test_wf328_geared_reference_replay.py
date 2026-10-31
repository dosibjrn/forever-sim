"""Pin the *geared* 100-pull objective, not a naked actor's one-mob score."""
from __future__ import annotations
from tools.wf328_geared_comparison import run


def test_wf326_geared_reference_replays_same_source_100_consecutive_mobs():
    measured = run()
    assert measured['status'] == 'COMPLETE'
    assert measured['new']['count'] == 100
    assert measured['new']['continuous_actor_state'] is True
    assert measured['new']['events'] == 7282
    assert abs(measured['new']['mean_s_per_mob'] - 13.46412880141965) < 1e-9
    assert measured['absolute_difference_s'] == 0.0
    # Replaying known gear is NOT an independent search or an acceptance proof.
    assert measured['independent_new_search'] is False
