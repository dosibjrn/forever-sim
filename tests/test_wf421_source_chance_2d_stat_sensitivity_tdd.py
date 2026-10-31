"""WF421: P3 raw Forever item chance stats measured on paid 2D CombatRuntime.

The real WF420 cold winner is rebuilt from SQLite, not from a test fixture.
The 100-mob scenario must be explicit: a stat can be zero for a single
sequential enemy and positive for simultaneous 20-yard enemies.
"""
import pytest
from tools.wf420_druid20_independent_full_replay import rebuild_result_winner
from src.v2.source_reoptimized_stat_sensitivity import reoptimized_stat_sensitivity


@pytest.fixture(scope='module')
def winner():
    evidence,candidate,recovery=rebuild_result_winner()
    assert evidence['winner']['gear_move']=='source_stat_package:spell_power'
    assert sum(evidence['winner']['allocation'].values())==16
    return candidate,recovery


def measure(winner, stat, delta, pack_size):
    candidate,recovery=winner
    return reoptimized_stat_sensitivity(candidate=candidate,stat=stat,delta=delta,
        level=20,recovery_policies=(recovery,),pack_sizes=(pack_size,),mobs=100,
        max_wall_s_per_eval=15.)


def test_source_raw_dodge_12_points_is_measured_on_paid_simultaneous_2d_100mob(winner):
    result=measure(winner,'dodge',12.,2)
    assert result['status']=='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
    assert result['source_item_chance_mapping']['displayed']['amount']==1.0
    assert result['source_item_chance_mapping']['channel_deltas']['dodge_chance']==pytest.approx(.01)
    assert result['weight_s_saved_per_mob_per_unit']>0
    assert result['best']['before']['pack_size']==result['best']['after']['pack_size']==2
    assert all(row['mob_completed']==100 and row['status']=='COMPLETE' for row in result['rows'])


def test_source_defense_4_points_uses_real_two_channel_avoidance(winner):
    result=measure(winner,'defense',4.,2)
    assert result['source_item_chance_mapping']['channel_deltas']=={
        'incoming_miss_chance_bonus':.0016,'dodge_chance':.0016}
    assert result['weight_s_saved_per_mob_per_unit']>0
    assert result['source_item_chance_mapping']['unmodeled_channels']
    assert all(row['events']>0 for row in result['rows'])


def test_single_sequential_100mob_keeps_dodge_zero_without_epsilon(winner):
    result=measure(winner,'dodge',12.,1)
    assert result['status']=='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
    assert result['weight_s_saved_per_mob_per_unit']==0.
    assert result['positive'] is False


@pytest.mark.parametrize('stat,delta', [('crit',14.),('hit',10.)])
def test_source_crit_and_hit_are_measured_with_sourced_unified_chance(winner,stat,delta):
    result=measure(winner,stat,delta,2)
    assert result['status']=='COMPLETE_REOPTIMIZED_100MOB_STAT_PROBE'
    assert result['source_item_chance_mapping']['displayed']['amount']==1.0
    missing=result['source_item_chance_mapping']['unmodeled_channels']
    if stat=='crit':
        assert not missing
        assert result['source_item_chance_mapping']['channel_deltas']['spell_crit_chance']==pytest.approx(.01)
        assert result['weight_s_saved_per_mob_per_unit']>0.
    else:
        assert not missing
        assert result['source_item_chance_mapping']['channel_deltas']['spell_hit_bonus']==pytest.approx(.01)
        assert result['weight_s_saved_per_mob_per_unit']>0.


def test_unmodeled_parry_rating_remains_fail_closed(winner):
    with pytest.raises(ValueError,match='no executable generic gear semantic'):
        measure(winner,'parry',10.,2)
