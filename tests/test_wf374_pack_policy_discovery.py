"""Canonical scratch APL search must optimize the real paid 100-mob 2D objective."""

from dataclasses import replace

from src.game.data.forever import build_game_ir_slice
from src.game.multi_pull import search_repeated_pull_evolved_policies


def test_source_scratch_apls_rank_by_paid_concurrent_100mob_survival_and_recovery():
    full = build_game_ir_slice(class_key='druid', level=30)
    actions = tuple(next(a for a in full.actions if a.family_key == key)
                    for key in ('starfire', 'moonfire'))
    ir = replace(full, actions=actions, auto_attacks=(), incoming_attacks=(),
                 triggers=(), companions=(), timed_summons=())
    result = search_repeated_pull_evolved_policies(
        ir_slice=ir, level=30, target_health=20, pack_size=3,
        budget=3, recovery_mode='always', schedule_incoming_attacks=False)
    assert result.candidates == 3
    assert result.valid == 3
    assert len({trial['candidate_id'] for trial in result.trials}) == 3
    assert result.winner is not None
    from src.game.policy_evolution import scratch_policies
    assert {a.id for a in actions} <= {rule.action_id for p in scratch_policies(ir, max_candidates=3) for rule in p.rules}
    assert all(t['status'] == 'COMPLETE' and t['evidence']['mob_completed'] == 100
               and t['evidence']['packs'] == 34 and t['evidence']['events'] > 0
               and t['evidence']['recovery_s'] > 0 for t in result.trials)
    assert min(t['mean_s_per_mob'] for t in result.trials) > 0
    assert result.metric == 'actual_100mob_seconds_per_mob'
