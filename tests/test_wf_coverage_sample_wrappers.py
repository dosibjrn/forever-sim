"""Both historical sample replay entry points share one deterministic sampler."""
import json

from scripts import run_wf_coverage238_sample as wf238
from scripts import run_wf_coverage239_sample as wf239


def test_wf238_and_wf239_share_samples_but_keep_evidence_contracts(tmp_path, monkeypatch):
    legal = [{}, {'ferocity': 1}, {'ferocity': 2}, {'moonglow': 1}]
    monkeypatch.setattr(wf238, 'build_game_ir_slice', lambda **_: object())
    monkeypatch.setattr(wf238, 'enumerate_legal_talent_allocations',
                        lambda *args, **kwargs: (legal, False))
    monkeypatch.setattr(wf238, 'talent_candidate_id',
                        lambda allocation: '|'.join(
                            f'{key}:{value}' for key, value in sorted(allocation.items())))
    calls = []

    def evaluate(**kwargs):
        sample, truncated = wf238.staged.enumerate_legal_talent_allocations()
        assert not truncated
        calls.append((kwargs['finalist_talent_count'], sample))
        return {'elapsed_s': 0.0,
                'winner': {'seconds_per_mob': 1.0, 'talent_allocation': {}},
                'held_out': {'best': {'seconds_per_mob': 2.0}}}

    monkeypatch.setattr(wf238.staged, 'evaluate_staged_joint_search', evaluate)
    original = wf238.staged.enumerate_legal_talent_allocations
    path238 = tmp_path / 'wf238.json'
    path239 = tmp_path / 'wf239.json'
    first = wf238.run(path238)
    assert wf238.staged.enumerate_legal_talent_allocations is original
    second = wf239.run(path239)
    assert wf238.staged.enumerate_legal_talent_allocations is original

    assert calls[0][0] == 16
    assert calls[1][0] == 8
    assert calls[0][1] == calls[1][1]
    assert first['version'] == '0.11.48.238'
    assert second['version'] == '0.11.48.239'
    assert 'finalist_talent_count' not in first
    assert second['finalist_talent_count'] == 8
    assert {k: v for k, v in first.items() if k != 'version'} == {
        k: v for k, v in second.items()
        if k not in ('version', 'finalist_talent_count')}
    assert json.loads(path238.read_text()) == first
    assert json.loads(path239.read_text()) == second
