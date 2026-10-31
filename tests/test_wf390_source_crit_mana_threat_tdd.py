"""Class-neutral L0 -> GameIR execution for sourced crit-bonus & compound cost/threat."""
from pathlib import Path
from dataclasses import replace
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_rank_promotion import promote_atomic_source_talent_effects
from src.game.talents import apply_talent_selection

DB=Path(__file__).resolve().parents[1]/'data/forever/staged_mage_l30_talent_positions_70374.sqlite'


def _context():
    ir=build_game_ir_slice(class_key='mage',level=30,ability_db_path=DB)
    promoted,ledger=promote_atomic_source_talent_effects(ir)
    return ir,promoted,ledger


def test_source_crit_bonus_modifies_only_frost_critical_bonus_not_base_damage():
    original,promoted,ledger=_context()
    selected,applied=apply_talent_selection(promoted,{'improved_frostbolt':5,'elemental_precision':5,'ice_shards':5},level=30)
    frost=next(a for a in selected.actions if a.family_key=='frostbolt')
    fire=next(a for a in selected.actions if a.family_key=='fireball')
    orig_frost=next(a for a in original.actions if a.family_key=='frostbolt')
    orig_fire=next(a for a in original.actions if a.family_key=='fireball')
    assert frost.effects[0].crit_multiplier==pytest.approx(1+2*(orig_frost.effects[0].crit_multiplier-1))
    assert frost.effects[0].base_min==pytest.approx(orig_frost.effects[0].base_min)
    assert fire.effects[0].crit_multiplier==orig_fire.effects[0].crit_multiplier
    assert any(a['kind']=='critical_damage_bonus_pct' for a in applied.applied_modifiers)


def test_source_compound_mana_and_threat_applies_atomically_to_only_frost():
    original,promoted,ledger=_context()
    selection={'improved_frostbolt':5,'elemental_precision':5,'ice_shards':5,'piercing_ice':3,'frost_channeling':3}
    selected,app=apply_talent_selection(promoted,selection,level=30)
    frost=next(a for a in selected.actions if a.family_key=='frostbolt')
    fire=next(a for a in selected.actions if a.family_key=='fireball')
    orig_frost=next(a for a in original.actions if a.family_key=='frostbolt')
    orig_fire=next(a for a in original.actions if a.family_key=='fireball')
    assert frost.costs[0].amount==pytest.approx(orig_frost.costs[0].amount*.85)
    assert fire.costs[0].amount==orig_fire.costs[0].amount
    assert frost.metadata['threat_multiplier']==pytest.approx(.7)
    assert fire.metadata.get('threat_multiplier',1.0)==pytest.approx(1.)
    assert app.spent_points==21
    assert ledger['full_talent_execution_certified'] is False


def test_fail_closed_when_compound_loses_source_clause_or_valid_spell_target():
    original,promoted,ledger=_context()
    talent=next(t for t in original.talents if t.id=='frost_channeling')
    rank=talent.ranks[2]
    captured=dict(rank.provenance['checkpoint_source_l0'])
    captured['effects']=captured['effects'][:1]
    broken=replace(original,talents=tuple(replace(t,ranks=tuple(replace(r,provenance={**r.provenance,'checkpoint_source_l0':captured}) if t.id=='frost_channeling' and r.rank==3 else r for r in t.ranks)) if t.id=='frost_channeling' else t for t in original.talents))
    altered,_=promote_atomic_source_talent_effects(broken)
    assert not next(t for t in altered.talents if t.id=='frost_channeling').ranks[2].modifiers
    no_frost=replace(original,actions=tuple(a for a in original.actions if all(getattr(e,'school',None)!='frost' for e in a.effects)))
    altered,_=promote_atomic_source_talent_effects(no_frost)
    assert not any(r.modifiers for r in next(t for t in altered.talents if t.id=='frost_channeling').ranks)


def test_unmodeled_frostbite_permafrost_not_promoted_even_with_other_mechanics():
    _,promoted,_=_context()
    for name in ('frostbite','permafrost'):
        assert not any(r.modifiers for r in next(t for t in promoted.talents if t.id==name).ranks)
