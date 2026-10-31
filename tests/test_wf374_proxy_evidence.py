"""Searchable numeric proxies must disclose source uncertainty in paid evidence."""

from dataclasses import replace

from src.game.data.forever import build_game_ir_slice
from src.game.multi_pull import search_repeated_pull_evolved_policies


def test_actual_100mob_source_wrath_proxy_is_disclosed_not_silently_zeroed():
    full = build_game_ir_slice(class_key='druid', level=30)
    wrath = next(a for a in full.actions if a.family_key == 'wrath')
    assert wrath.effects[0].unsupported_semantics
    ir = replace(full, actions=(wrath,), auto_attacks=(), incoming_attacks=(),
                 triggers=(), companions=(), timed_summons=())
    result = search_repeated_pull_evolved_policies(
        ir_slice=ir, level=30, target_health=20, pack_size=3,
        budget=1, recovery_mode='always', schedule_incoming_attacks=False)
    assert result.valid == 1
    evidence = result.trials[0]['evidence']
    assert evidence['mob_completed'] == 100
    assert evidence['proxy_uncertainties']
    assert all(entry['action_id'] == wrath.id for entry in evidence['proxy_uncertainties'])
    assert any(entry['source_record']['status'] == 'explicit_approximation'
               for entry in evidence['proxy_uncertainties'])
