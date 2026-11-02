"""Keep both historical WF240/WF241 CLI behaviors when sharing replay code."""
from __future__ import annotations

import json
from types import SimpleNamespace

from tools import wf240_source_joint_replay as full
from tools import wf241_source_joint_replay as bounded


def test_replay_score_preserves_independent_policy_budgets(monkeypatch):
    calls = []
    monkeypatch.setattr(full, 'apply_gear_selection', lambda *a, **kw: (object(), None))
    monkeypatch.setattr(full, 'apply_talent_selection', lambda *a, **kw: (object(), None))

    def winner():
        return {'winner': {
            'seconds_per_mob': 1.0, 'selected_actions': [],
            'policy': {}, 'combat_kill_s': 0.8, 'recovery_s': 0.2,
        }}

    def caster(*a, **kw):
        calls.append(('caster', kw['max_policies']))
        return winner()

    def mode(*a, **kw):
        calls.append(('mode', kw['max_policies_per_path']))
        return winner()

    monkeypatch.setattr(full, '_evaluate_caster_already_talented', caster)
    monkeypatch.setattr(full, 'evaluate_discovered_mode_search', mode)
    gear = {'selection': SimpleNamespace(aggregate_stats={}, slots={}),
            'id': 'fixture', 'gear_role': 'test'}
    full.score(object(), gear, {'ferocity': 1})
    bounded.score(object(), gear, {'ferocity': 1})
    assert calls == [('caster', 128), ('mode', 256),
                     ('caster', 24), ('mode', 24)]


def test_replay_versions_and_filenames_preserved(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(full, 'build_game_ir_slice', lambda **kw: object())
    monkeypatch.setattr(full, 'enumerate_legal_talent_allocations',
                        lambda *a, **kw: (({'ferocity': 1},), False))
    monkeypatch.setattr(full, 'talent_candidate_id',
                        lambda a: repr(sorted(a.items())))
    monkeypatch.setattr(full, '_gear_envelope', lambda *a, **kw: [{'id': 'gear'}])
    monkeypatch.setattr(full, '_diverse_gear_indices', lambda *a: [0])
    observed = []

    def fake_score(ir, gear, allocation, **kw):
        observed.append(kw)
        return {'seconds_per_mob': 1.0, 'talent_allocation': allocation}

    monkeypatch.setattr(full, 'score', fake_score)
    full.run()
    bounded.run()
    p240 = json.loads((tmp_path / 'WF240_DRUID_L20_JOINT_REPLAY.json').read_text())
    p241 = json.loads((tmp_path / 'WF241_DRUID_L20_JOINT_REPLAY.json').read_text())
    assert p240['version'] == '0.11.48.240'
    assert p241['version'] == '0.11.48.241'
    assert p240['limitations'][-1] == 'regrowth compound heal not yet considered by recovery optimizer'
    assert p241['limitations'][-1] == (
        'mixed direct/HoT recovery now executable; HoT continuation into the next pull not yet rehydrated'
    )
    assert observed[:2] == [dict(caster_max_policies=128, mode_max_policies=256)] * 2
    assert observed[2:] == [dict(caster_max_policies=24, mode_max_policies=24)] * 2
