"""Seeded search must not erase scratch discovery under a bounded budget."""

from dataclasses import replace

from src.game.data.forever import build_game_ir_slice
from src.game.policy_evolution import from_source_rules, search_evolved_policies


def test_seeded_policy_budget_includes_source_scratch_and_mutations():
    full = build_game_ir_slice(class_key='druid', level=30)
    actions = tuple(next(a for a in full.actions if a.family_key == key)
                    for key in ('starfire', 'moonfire'))
    ir = replace(full, actions=actions, auto_attacks=())
    seed = from_source_rules(ir, ((actions[1].id, ()),), provenance='test_seed')
    result = search_evolved_policies(
        ir, seed=seed, budget=5, include_scratch=True,
        evaluate=lambda _: {'status': 'COMPLETE', 'mob_completed': 100, 'mean_s_per_mob': 1.0})
    assert result.candidates == 5
    assert result.valid == 5
    origins = {trial['origin'] for trial in result.trials}
    assert 'test_seed' in origins
    assert 'scratch_generated' in origins
    assert any(origin in {'insert_action', 'replace_action', 'remove_action',
                          'add_health_gate', 'add_source_resource_gate'} for origin in origins)
