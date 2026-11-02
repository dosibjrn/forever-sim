"""P2 source-ranked critical resource gains must execute in real CombatRuntime.

The canonical staged Druid source carries two independent mode/trigger clauses.
No source catalogue entry or compiled modifier alone earns a behavioral PASS.
"""
from dataclasses import replace
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from tools.wf_gate_p2_live import (
    _behavior_fixtures, _critical_resource_gain_runtime_witness,
)

SOURCE = (Path(__file__).resolve().parents[1] /
          'data/forever/staged_druid_l30_talents_70338.sqlite')
FILLER = {
    'ferocity': 5, 'heart_of_the_wild': 5, 'feral_swiftness': 2,
    'feral_instinct': 3, 'thick_hide': 3, 'shredding_attacks': 3,
    'savage_fury': 2, 'sharpened_claws': 2,
}


def rank_pair(rank):
    compiled, _ = compile_talent_runtime(
        build_game_ir_slice(class_key='druid', level=30, ability_db_path=SOURCE))
    talent = next(t for t in compiled.talents if t.id == 'blood_frenzy')
    prior_rank = next((r for r in talent.ranks if r.rank == rank - 1), None)
    current_rank = next(r for r in talent.ranks if r.rank == rank)
    filler = dict(FILLER)
    if rank == 2:
        filler['feral_instinct'] -= 1
    previous = {**filler, **({'blood_frenzy': rank - 1} if rank > 1 else {})}
    current = {**filler, 'blood_frenzy': rank}
    before, _ = apply_talent_selection(compiled, previous,
                                       level=30, bonus_talent_points=5)
    after, _ = apply_talent_selection(compiled, current,
                                      level=30, bonus_talent_points=5)
    modifiers = tuple(replace(mod, value=mod.value - (
        prior_rank.modifiers[i].value if prior_rank else 0.))
        for i, mod in enumerate(current_rank.modifiers))
    return before, after, modifiers


def test_both_source_critical_resource_clauses_execute_for_each_rank():
    for rank in (1, 2):
        before, after, modifiers = rank_pair(rank)
        assert {m.target_id for m in modifiers} == {'rage', 'combo_points'}
        tests, missing = _behavior_fixtures(before, after, modifiers)
        assert not missing
        assert len(tests) == 2
        assert {test['resource_id'] for test in tests} == {'rage', 'combo_points'}
        assert all(test['probe'] == 'paired_production_critical_resource_gain'
                   and test['after_gain'] > test['before_gain']
                   and test['no_crit_control_gain'] == 0.
                   for test in tests)


def test_source_probability_mismatch_does_not_certify_a_real_proc():
    before, after, modifiers = rank_pair(1)
    for mod in modifiers:
        wrong = replace(mod, value=mod.value / 2.)
        assert _critical_resource_gain_runtime_witness(before, after, wrong) is None


def test_wrong_mode_cannot_reuse_an_unrelated_resource_proc():
    before, after, modifiers = rank_pair(1)
    for mod in modifiers:
        wrong = replace(mod, provenance={
            **mod.provenance, 'required_mode_id': 'not_a_source_mode'})
        assert _critical_resource_gain_runtime_witness(before, after, wrong) is None
