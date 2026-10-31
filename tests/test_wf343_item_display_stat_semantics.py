"""Forever source item raw amounts must become display percentages, never TBC ratings."""
from dataclasses import dataclass,field
from math import isclose
import pytest
from src.game.data.forever.source_checkpoint_p3_ratings import (
    SOURCE_STATUS, displayed_percent_from_raw, forever_display_chance_fraction_per_raw_point,
    source_item_stat_to_combat, apply_source_item_stat_delta, apply_source_equipped_item_stats)
from src.game.data.forever.source_checkpoint_p3 import source_item_l0
from src.rulesets.forever.items.runtime_selection import available_items

@dataclass(frozen=True)
class Actor:base_stats:dict
@dataclass(frozen=True)
class IR:actor:Actor;provenance:dict=field(default_factory=dict)


def test_direct_item_display_pct_is_level_invariant():
    # Client raw amounts verified against *displayed* Forever item pages.
    assert displayed_percent_from_raw('crit',14.)==1.
    assert displayed_percent_from_raw('hit',10.)==1.
    assert displayed_percent_from_raw('dodge',12.)==1.
    for stat,amount,key in [('crit',14.,'melee_crit_chance'),
                            ('hit',10.,'melee_hit_bonus'),('dodge',12.,'dodge_chance')]:
        a=source_item_stat_to_combat(stat,amount,level=20)
        b=source_item_stat_to_combat(stat,amount,level=60)
        assert isclose(a['channel_deltas'][key],.01)
        assert a['channel_deltas']==b['channel_deltas']
        assert not a['uses_tbc_level_scaled_rating']
        assert a['status']==SOURCE_STATUS
        assert isclose(forever_display_chance_fraction_per_raw_point(stat,20)*amount,.01)


def test_defense_is_skill_not_level_scaled_rating_and_exposes_gaps():
    for level in (10,20,60):
        r=source_item_stat_to_combat('defense',5.,level=level)
        assert r['displayed']=={'unit':'defense_skill','amount':5.}
        assert isclose(r['channel_deltas']['dodge_chance'],.002)
        assert isclose(r['channel_deltas']['incoming_miss_chance_bonus'],.002)
        assert 'incoming_crit_suppression' in r['unmodeled_channels']
        assert 'parry_chance' in r['unmodeled_channels']
        assert 'block_chance' in r['unmodeled_channels']
    assert forever_display_chance_fraction_per_raw_point('defense',20) is None


def test_actual_canonical_catalogue_matches_displayed_item_examples():
    rows={int(x.item_id):x for x in available_items('druid',20,required_level_policy='observed')}
    assert rows[7348].crit==14
    assert rows[12985].defense==4
    assert rows[7348].fetch_status=='verified_listview'
    glove=source_item_l0(rows[7348]); ring=source_item_l0(rows[12985])
    assert glove['numeric_source_domains']['crit']==14
    assert not any('unconverted_rating' in e for e in glove['unresolved_effects'])
    assert ring['numeric_source_domains']['defense']==4
    assert any('partial_defense_skill' in e for e in ring['unresolved_effects'])


def test_real_equipped_items_modify_actor_using_display_pct_and_skill():
    ir=IR(Actor({'melee_crit_chance':.1,'dodge_chance':0.}))
    result=apply_source_equipped_item_stats(ir,class_key='druid',level=20,item_ids=[7348,12985])
    assert isclose(result.actor.base_stats['melee_crit_chance'],.11)
    assert isclose(result.actor.base_stats['dodge_chance'],.0016)
    assert isclose(result.actor.base_stats['incoming_miss_chance_bonus'],.0016)
    info=result.provenance['source_equipped_item_combat_stats']
    assert info['displayed_crit_pct']==1.
    assert info['defense_skill']==4.
    assert info['complete_Forever_L2'] is False
    assert ir.actor.base_stats['melee_crit_chance']==.1
    with pytest.raises(ValueError,match='DUPLICATE'):apply_source_equipped_item_stats(ir,class_key='druid',level=20,item_ids=[7348,7348])
    with pytest.raises(ValueError,match='NOT_LEGAL'):apply_source_equipped_item_stats(ir,class_key='druid',level=20,item_ids=[9999999])


def test_negative_item_stats_and_invalid_source_values():
    assert isclose(source_item_stat_to_combat('crit',-14.,level=20)['channel_deltas']['melee_crit_chance'],-.01)
    for v in (float('inf'),float('nan')):
        with pytest.raises(ValueError):source_item_stat_to_combat('hit',v,level=20)
