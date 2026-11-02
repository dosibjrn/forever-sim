"""Native target identity regressions — fake rows NEVER constitute P7 evidence."""
from __future__ import annotations

import pytest

from src.game.runtime.go_native_spell_observations import NativeSpellObservationError
from src.game.runtime.go_native_target_spell_observations import NativeTargetSpellObservationLedger


def row(*, target_index=0, unit_index=1, label="pinned-native-mob", casts=1, damage=10):
    return {"action_id":"SpellID:123","rank":1,
            "native_target_index":target_index,
            "native_target_unit_index":unit_index,
            "native_target_label":label,
            "casts":casts,"hits":casts,"crits":0,"ticks":0,
            "total_damage":damage}


def test_only_one_native_target_maps_to_gsim_selected_enemy():
    ledger=NativeTargetSpellObservationLedger()
    first=ledger.observe([row()],sequence=0,gsim_target_id="m1")
    assert len(first)==1
    assert first[0]["gsim_selected_target_id"]=="m1"
    assert first[0]["native_target_index"]==0
    assert first[0]["total_damage"]==10
    next_=ledger.observe([row(casts=2,damage=25)],sequence=1,gsim_target_id="m1")
    assert next_[0]["casts"]==1
    assert next_[0]["total_damage"]==15


@pytest.mark.parametrize("bad",[
    row(target_index=1),
    row(unit_index=-1),
    row(label=""),
    dict(row(),native_target_unit_index=True),
])
def test_bad_native_enemy_identity_rejected(bad):
    with pytest.raises(NativeSpellObservationError):
        NativeTargetSpellObservationLedger().observe([bad],sequence=0,gsim_target_id="m1")


def test_native_enemy_identity_switch_rejected_without_losing_sequence():
    ledger=NativeTargetSpellObservationLedger()
    ledger.observe([row()],sequence=0,gsim_target_id="m1")
    with pytest.raises(NativeSpellObservationError,match="IDENTITY_CHANGED"):
        ledger.observe([row(label="another enemy")],sequence=1,gsim_target_id="m1")
    accepted=ledger.observe([row(casts=2,damage=20)],sequence=1,gsim_target_id="m1")
    assert accepted[0]["total_damage"]==10


def test_missing_target_gsim_mapping_rejected():
    with pytest.raises(NativeSpellObservationError,match="GSIM_TARGET"):
        NativeTargetSpellObservationLedger().observe([row()],sequence=0,gsim_target_id="")


def test_gsim_target_swap_without_native_rebind_rejected():
    ledger=NativeTargetSpellObservationLedger()
    ledger.observe([row()],sequence=0,gsim_target_id="m1")
    with pytest.raises(NativeSpellObservationError,match="GSIM_SELECTED_TARGET_CHANGED"):
        ledger.observe([row(casts=2,damage=20)],sequence=1,gsim_target_id="m2")
    good=ledger.observe([row(casts=2,damage=20)],sequence=1,gsim_target_id="m1")
    assert good[0]["gsim_selected_target_id"]=="m1"
