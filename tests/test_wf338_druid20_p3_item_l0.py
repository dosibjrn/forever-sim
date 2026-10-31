"""P3 is a complete source item inventory, not a fixed build fixture."""
from copy import deepcopy
from collections import Counter
import pytest

from src.game.data.forever.gear import select_named_gear
from src.game.data.forever.source_checkpoint_p3 import (
    checkpoint_item_l0,verify_checkpoint_item_l0,source_item_l0,
)
from src.rulesets.forever.items.runtime_selection import available_items
from src.v2.source_persistent_slot_search import _source_slot_proposals,_gear_replace
from src.game.data.forever.source_named_gear_proof import audit_named_gear_source


def _certificate():
    return checkpoint_item_l0(class_key='druid',level=20)


def _base():
    return select_named_gear(class_key='druid',level=20,role='druid_feral',
        stat_weights={'strength':1.,'agility':.3,'stamina':.1},
        required_level_policy='observed').as_dict()


def test_p3_every_legal_item_and_all_fillable_slots_assessed():
    cert=_certificate()
    with pytest.raises(ValueError,match='P3_CERTIFICATE_CHECKPOINT_MISMATCH'):
        verify_checkpoint_item_l0(cert,class_key='druid',level=20)
    coverage=verify_checkpoint_item_l0(cert,class_key='druid',level=20,
        allow_unattested_diagnostic=True)
    assert coverage['diagnostic_only'] and not coverage['p3_pass']
    source=available_items('druid',20,required_level_policy='observed')
    assert cert['legal_item_count']==len(source)==cert['l0_assessed_count']
    assert not cert['p3_pass']
    assert len(cert['source_items'])==len({r['item_id'] for r in cert['source_items']})
    assert {'weapon','offhand','relic','shirt','ring1','ring2','trinket1','trinket2'} <= set(cert['slot_frontiers'])
    for slot,frontier in cert['slot_frontiers'].items():
        assert len(frontier['priority_item_ids'])==frontier['legal_item_count']
    assert cert['unknown_effect_item_count']>0


def test_unknown_effects_not_silently_zero_or_pruned():
    cert=_certificate()
    relic=[x for x in cert['source_items'] if x['catalogue_slot']=='relic']
    assert len(relic)==1 and relic[0]['item_id']==249396
    assert relic[0]['l2_effect_fully_supported']
    assert relic[0]['typed_source_effects'][0]['stat']=='spirit'
    assert {x['item_id'] for x in relic} <= set(cert['slot_frontiers']['relic']['priority_item_ids'])
    assert all(x['contextual_zero'] for x in cert['source_items'] if x['catalogue_slot']=='shirt')


def test_source_p3_priority_drives_legal_slot_proposals_including_missing_slots():
    cert=_certificate();base=_base()
    # Exercise missing-slot proposal explicitly: current source-legal base
    # selector now already fills the real relic and cosmetic shirt slots.
    base['slots'].pop('relic',None)
    base['slots'].pop('shirt',None)
    base['item_count']=len(base['slots'])
    assert 'relic' not in base['slots']
    proposals,counts=_source_slot_proposals(class_key='druid',level=20,
        base=base,per_slot=3,max_proposals=48,p3_certificate=cert,
        allow_unattested_diagnostic=True)
    assert len(proposals)>=35
    assert {'relic','shirt','weapon'} <= {slot for slot,_ in proposals}
    assert counts['weapon']>50
    for slot,item in proposals:
        updated=_gear_replace(base,slot,item)
        audit=audit_named_gear_source(class_key='druid',level=20,gear=updated)
        assert audit['equipment_legality_complete'],(slot,item.item_id)
    relic=next((slot,item) for slot,item in proposals if slot=='relic')
    assert _gear_replace(base,*relic)['item_count']==len(base['slots'])+1


def test_wrong_checkpoint_tampered_and_incomplete_certificates_fail_closed():
    cert=_certificate()
    with pytest.raises(ValueError,match='CHECKPOINT_MISMATCH'):
        verify_checkpoint_item_l0(cert,class_key='druid',level=30)
    bad=deepcopy(cert)
    bad['source_items'][0]['numeric_source_domains']['strength']=999999.
    with pytest.raises(ValueError,match='TAMPERED_ITEM_VECTOR'):
        verify_checkpoint_item_l0(bad,class_key='druid',level=20,
            allow_unattested_diagnostic=True)
    bad=deepcopy(cert)
    bad['slot_frontiers']['weapon']['priority_item_ids'].pop()
    with pytest.raises(ValueError,match='FRONTIER_INCOMPLETE'):
        verify_checkpoint_item_l0(bad,class_key='druid',level=20,
            allow_unattested_diagnostic=True)


def test_druid_onehand_is_not_an_offhand_weapon():
    from src.game.data.forever.source_checkpoint_p3 import source_item_slots
    one=next(x for x in available_items('druid',20,required_level_policy='observed') if x.slot=='one_hand')
    assert source_item_slots(one)==('weapon',)
