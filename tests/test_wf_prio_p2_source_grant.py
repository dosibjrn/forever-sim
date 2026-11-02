"""Canonical source talent grants execute without a duplicate staged talent catalogue."""
from dataclasses import replace
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_rank_promotion import promote_atomic_source_talent_effects
from src.game.talents import apply_talent_selection
from tools.wf_gate_p2_live import _action_runtime_probe

DB = Path(__file__).resolve().parents[1] / 'data/forever/staged_druid_l30_talents_70338.sqlite'
FILLER = {'genesis': 5, 'improved_wrath': 5, 'improved_moonfire': 2,
          'natures_majesty': 2, 'moonglow': 3, 'natures_reach': 2,
          'improved_entangling_roots': 1}


def _stripped_source():
    ir = build_game_ir_slice(class_key='druid', level=30, ability_db_path=DB)
    talent = next(t for t in ir.talents if t.id == 'insect_swarm')
    assert talent.metadata['sqlite_spell_id'] == 5570
    assert any(f.get('family') == 'talent_granted_action_facts'
               for f in ir.source_facts if isinstance(f, dict))
    source_rank = replace(talent.ranks[0], modifiers=(), provenance={
        'source': {'authority': 'canonical_sqlite_spell_index', 'entity_id': 5570},
        'raw_tooltip': 'The enemy target is swarmed by insects, decreasing their chance to hit with attacks by 2% and causing 48 Nature damage over 12 sec.'})
    return replace(ir, talents=tuple(replace(t, ranks=(source_rank,))
        if t.id == talent.id else t for t in ir.talents))


def test_verified_grant_promotes_and_executes_real_periodic_damage():
    ir = _stripped_source()
    compiled, coverage = promote_atomic_source_talent_effects(ir)
    rank = next(t.ranks[0] for t in compiled.talents if t.id == 'insect_swarm')
    assert len(rank.modifiers) == 1
    mod = rank.modifiers[0]
    assert (mod.kind, mod.target_type, mod.target_id) == (
        'grant_source_action', 'source_action', '5570')
    assert mod.provenance['authority'] == 'canonical_sqlite_verified_source_rank_grant'
    assert any(row['talent_id'] == 'insect_swarm' for row in coverage['promoted'])
    selected, receipt = apply_talent_selection(
        compiled, {**FILLER, 'insect_swarm': 1},
        level=30, bonus_talent_points=5)
    action = next(a for a in selected.actions if a.id == 'insect_swarm:24974')
    assert all(a.id != action.id for a in ir.actions)
    observed = _action_runtime_probe(selected, action, observe_periodic=True)
    assert observed is not None
    assert observed['periodic_damage'] > 0


def test_missing_or_mismatched_grant_cannot_promote_noop_rank():
    ir = _stripped_source()
    no_source = replace(ir, source_facts=tuple(f for f in ir.source_facts
        if not (isinstance(f, dict) and
                f.get('family') == 'talent_granted_action_facts')))
    wrong_parent = replace(ir, talents=tuple(
        replace(t, metadata={**t.metadata, 'sqlite_spell_id': 999999})
        if t.id == 'insect_swarm' else t for t in ir.talents))
    for candidate in (no_source, wrong_parent):
        compiled, coverage = promote_atomic_source_talent_effects(candidate)
        rank = next(t.ranks[0] for t in compiled.talents if t.id == 'insect_swarm')
        assert not rank.modifiers
        assert any(row['talent_id'] == 'insect_swarm' for row in coverage['unscored'])
