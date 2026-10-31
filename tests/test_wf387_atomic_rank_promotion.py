from dataclasses import replace
from pathlib import Path
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_rank_promotion import promote_atomic_source_talent_effects
from src.game.talents import apply_talent_selection

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'


def test_atomic_cast_time_source_affects_real_ir_and_never_claims_full_l2():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DB)
    before=next(a.cast_time_s for a in ir.actions if a.family_key=='frostbolt')
    transformed,ledger=promote_atomic_source_talent_effects(ir)
    assert before==3.
    assert ledger['promoted_rank_count']>=5
    assert ledger['unscored_rank_count']>0
    assert ledger['full_talent_execution_certified'] is False
    altered,application=apply_talent_selection(transformed,{'improved_frostbolt':5},level=30)
    after=next(a.cast_time_s for a in altered.actions if a.family_key=='frostbolt')
    assert after==pytest.approx(2.5)
    assert application.spent_points==5
    assert any(a['talent_id']=='improved_frostbolt' for a in application.applied_modifiers)
    # The newly complete compound now passes source semantics, but the
    # talent-tree tier gate must still reject an unqualified allocation.
    with pytest.raises(ValueError,match='talent tree tier gate'):
        apply_talent_selection(transformed,{'frost_channeling':3},level=30)


def test_compound_source_cannot_be_silently_promoted_and_missing_target_blocks():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DB)
    upgraded,ledger=promote_atomic_source_talent_effects(ir)
    # The full mana+threat source clause is now compiled *atomically*.
    assert all(len(r.modifiers)==2 for r in next(t for t in upgraded.talents if t.id=='frost_channeling').ranks)
    assert not any(r.modifiers for r in next(t for t in upgraded.talents if t.id=='wake_of_fire').ranks)
    target=next(t for t in upgraded.talents if t.id=='improved_frostbolt')
    assert all(r.modifiers and r.modifiers[0].provenance['url'].startswith('https://') for r in target.ranks)
    no_spell=replace(ir, actions=tuple(a for a in ir.actions if a.family_key!='frostbolt'))
    changed,ledger=promote_atomic_source_talent_effects(no_spell)
    assert not any(r.modifiers for r in next(t for t in changed.talents if t.id=='improved_frostbolt').ranks)


def test_source_school_scopes_apply_without_spreading_damage_to_wrong_schools():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DB)
    upgraded,ledger=promote_atomic_source_talent_effects(ir)
    frost_legal={'improved_frostbolt':5,'elemental_precision':5,'piercing_ice':3}
    # Row two requires 10 points from lower rows, all from this source tree.
    applied,result=apply_talent_selection(upgraded,frost_legal,level=30)
    fb=next(a for a in applied.actions if a.family_key=='frostbolt')
    fire=next(a for a in applied.actions if a.family_key=='fireball')
    base_fb=next(a for a in ir.actions if a.family_key=='frostbolt')
    base_fire=next(a for a in ir.actions if a.family_key=='fireball')
    assert fb.cast_time_s==pytest.approx(base_fb.cast_time_s-0.5)
    assert fb.metadata['outgoing_hit_bonus']==pytest.approx(.05)
    assert fire.metadata['outgoing_hit_bonus']==pytest.approx(.05)
    assert fb.effects[0].base_min==pytest.approx(base_fb.effects[0].base_min*1.06)
    assert fire.effects[0].base_min==pytest.approx(base_fire.effects[0].base_min)
    assert result.spent_points==13


def test_structural_21_and_26_point_frost_candidates_with_explicit_legacy_budget():
    from src.game.data.forever.source_checkpoint_p2 import check_structural_allocation,P2Checkpoint
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DB)
    standard={'improved_frostbolt':5,'elemental_precision':5,'ice_shards':5,
              'piercing_ice':3,'frost_channeling':3}
    legacy={**standard,'frostbite':3,'permafrost':2}
    scope=P2Checkpoint('mage',30,source_build='1.60.1.70374')
    assert check_structural_allocation(ir,standard,scope)
    with pytest.raises(ValueError,match='P2_POINT_BUDGET'):
        check_structural_allocation(ir,legacy,scope)
    assert check_structural_allocation(ir,legacy,scope,bonus_talent_points=5)
    upgraded,ledger=promote_atomic_source_talent_effects(ir)
    selected,application=apply_talent_selection(upgraded,standard,level=30)
    assert application.spent_points==21
    assert any(x['kind']=='critical_damage_bonus_pct' for x in application.applied_modifiers)
    with pytest.raises(ValueError,match='unsupported talent effect'):
        apply_talent_selection(upgraded,legacy,level=30,bonus_talent_points=5)
