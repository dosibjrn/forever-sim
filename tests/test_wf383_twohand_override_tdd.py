"""An explicit two-hand choice must evict the selector's implicit offhand."""
import pytest
from src.rulesets.forever.items.runtime_selection import (
    available_items, gear_overrides, select_gear, item_vector,
)
from src.game.data.forever.gear import select_named_gear

WEIGHTS={'intellect':1.,'spell_power':1.18,'spirit':.34,'mp5':.55,'stamina':.05,'wand_dps':1.}


def _twohand():
    return next(x for x in available_items('mage',30,required_level_policy='observed')
                if x.item_id == 249392 and x.weapon_hands == 2)


def test_named_twohand_override_evicts_implicit_offhand():
    item=_twohand()
    with gear_overrides({'weapon':item.item_id}):
        selected=select_named_gear(class_key='mage',level=30,role='mage',
            stat_weights=WEIGHTS,required_level_policy='observed',
            exclude_unknown_item_effects=True)
    assert selected.slots['weapon']['item_id']==item.item_id
    assert 'offhand' not in selected.slots
    assert selected.aggregate_stats['intellect'] == pytest.approx(sum(
        item_vector(x)['intellect'] for x in select_gear('mage',30,'mage',weights=WEIGHTS,
            required_level_policy='observed',exclude_unknown_item_effects=True)
        .values()) - item_vector(select_gear('mage',30,'mage',weights=WEIGHTS,
            required_level_policy='observed',exclude_unknown_item_effects=True)['offhand'])['intellect']
        - item_vector(select_gear('mage',30,'mage',weights=WEIGHTS,
            required_level_policy='observed',exclude_unknown_item_effects=True)['weapon'])['intellect']
        + item_vector(item)['intellect'])


def test_explicit_twohand_plus_offhand_override_still_fails():
    item=_twohand()
    with gear_overrides({'weapon':item.item_id,'offhand':249394}):
        with pytest.raises(ValueError,match='ILLEGAL_TWO_HAND_AND_OFFHAND_PACKAGE'):
            select_named_gear(class_key='mage',level=30,role='mage',
                stat_weights=WEIGHTS,required_level_policy='observed',
                exclude_unknown_item_effects=True)


def test_onehand_override_keeps_legal_offhand():
    base=select_named_gear(class_key='mage',level=30,role='mage',
        stat_weights=WEIGHTS,required_level_policy='observed',exclude_unknown_item_effects=True)
    assert 'offhand' in base.slots
    with gear_overrides({'weapon':base.slots['weapon']['item_id']}):
        again=select_named_gear(class_key='mage',level=30,role='mage',
            stat_weights=WEIGHTS,required_level_policy='observed',exclude_unknown_item_effects=True)
    assert 'offhand' in again.slots
