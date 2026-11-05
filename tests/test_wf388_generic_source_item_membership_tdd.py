"""WF388: true class-filtered item denominator, not inherited profile fallback."""
from __future__ import annotations
import pytest

from src.rulesets.forever.items.runtime_selection import (
    _DEFAULT_DB, source_class_item_membership_verified,
)
from src.rulesets.forever.items.wowhead_queries import (
    CANONICAL_CLASS_QUERIES, bands_for_class, canonical_bands,
)
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0


@pytest.mark.parametrize('class_key',['mage','druid','paladin','hunter'])
def test_existing_class_rows_are_not_complete_capture_attestation(class_key):
    assert not source_class_item_membership_verified(class_key,_DEFAULT_DB)


def test_mage_checkpoint_p3_cannot_pass_from_unattested_1312_items():
    r=checkpoint_item_l0(class_key='mage',level=30)
    assert r['legal_item_count']>=1000
    assert r['l0_assessed_count']==r['legal_item_count']
    assert not r['source_membership_verified']
    assert not r['p3_pass']


@pytest.mark.parametrize('class_key',['mage','druid','paladin','hunter'])
def test_class_capture_must_cover_entire_source_item_level_envelope(class_key):
    bands=bands_for_class(class_key)
    assert bands[0][0]==1 and bands[-1][1]==255
    assert all(a[1]+1==b[0] for a,b in zip(bands,bands[1:]))


def test_unattested_mage_pool_can_be_verified_as_diagnostic_without_p3_pass():
    from copy import deepcopy
    from src.game.data.forever.source_checkpoint_p3 import verify_checkpoint_item_l0
    cert=checkpoint_item_l0(class_key='mage',level=30)
    with pytest.raises(ValueError,match='P3_CERTIFICATE_CHECKPOINT_MISMATCH'):
        verify_checkpoint_item_l0(cert,class_key='mage',level=30)
    coverage=verify_checkpoint_item_l0(cert,class_key='mage',level=30,
                                       allow_unattested_diagnostic=True)
    assert coverage['diagnostic_only'] and not coverage['p3_pass']
    assert coverage['assessed_count']==1312
    bad=deepcopy(cert)
    bad['slot_frontiers']['weapon']['priority_item_ids'].pop()
    with pytest.raises(ValueError,match='FRONTIER_INCOMPLETE'):
        verify_checkpoint_item_l0(bad,class_key='mage',level=30,
                                  allow_unattested_diagnostic=True)
    bad=deepcopy(cert)
    bad['source_items'][0]['numeric_source_domains']['strength']=999999
    with pytest.raises(ValueError,match='TAMPERED_ITEM_VECTOR'):
        verify_checkpoint_item_l0(bad,class_key='mage',level=30,
                                  allow_unattested_diagnostic=True)


def test_mage_unattested_p3_proposals_require_explicit_opt_in():
    from src.game.data.forever.gear import select_named_gear
    from src.v2.source_persistent_slot_search import _source_slot_proposals
    cert=checkpoint_item_l0(class_key='mage',level=30)
    base=select_named_gear(class_key='mage',level=30,role='mage',
        stat_weights={'intellect':1.,'spell_power':1.,'stamina':.2},
        required_level_policy='observed').as_dict()
    with pytest.raises(ValueError,match='P3_CERTIFICATE_CHECKPOINT_MISMATCH'):
        _source_slot_proposals(class_key='mage',level=30,base=base,
                               p3_certificate=cert)
    proposals,counts=_source_slot_proposals(class_key='mage',level=30,base=base,
        p3_certificate=cert,allow_unattested_diagnostic=True,
        per_slot=2,max_proposals=48)
    assert len(proposals)>=18 and counts['weapon']>5
    assert all(item.item_id in {x['item_id'] for x in cert['source_items']}
               for _,item in proposals)
