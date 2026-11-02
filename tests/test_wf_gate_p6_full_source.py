"""Fast orchestration regression; the paid 330s acceptance stays on-demand."""
import json
from pathlib import Path
from unittest.mock import patch

from tools.wf_gate_p6_full_source import run_full_source_comparison


class _Result:
    returncode = 0
    stdout = 'production paid run'
    stderr = ''


def _fake_paid_runner(commands, *, ratio=1.00001, incomplete=False):
    def run(command, **kwargs):
        assert command[1:3] == ['-m', 'tools.wf437_direct_budgeted_run']
        assert kwargs['check'] is False
        assert kwargs['timeout'] >= 240
        commands.append(command)
        output = Path(command[command.index('--output') + 1])
        if '--budget' in command:
            budget = int(command[command.index('--budget') + 1])
            report = {'requested_wall_budget_s': budget, 'search_only': True,
                      'validation_shortlist': [{'allocation': {'source': 1}}],
                      'wall_s': float(budget) - .1,
                      'source_db_sha256': 'pinned-source'}
        else:
            assert '--compare-30' in command and '--compare-300' in command
            for flag in ('--compare-30', '--compare-300'):
                assert Path(command[command.index(flag) + 1]).is_file()
            report = {'replays': [
                {'status': 'COMPLETE', 'count': 100, 's_per_mob': 12.5},
                {'status': 'INCOMPLETE' if incomplete else 'COMPLETE',
                 'count': 37 if incomplete else 100, 's_per_mob': 12.5}],
                'ratio_T30_T300': ratio, 'T30_s_per_mob': 12.5,
                'T300_s_per_mob': 12.5 / ratio,
                'numeric_p6_within_1pct': ratio <= 1.01 and not incomplete,
                'N30_unique_paid': 356, 'N300_unique_paid': 6325}
        output.write_text(json.dumps(report))
        return _Result()
    return run


def test_p6_explicit_full_source_run_uses_two_independent_cold_budgets_and_replay():
    commands = []
    with patch('tools.wf_gate_p6_full_source.subprocess.run',
               side_effect=_fake_paid_runner(commands)):
        result = run_full_source_comparison(Path('/tmp'), 'druid', 30)
    assert len(commands) == 3
    assert '--budget' in commands[0] and '30' in commands[0]
    assert '--budget' in commands[1] and '300' in commands[1]
    assert '--compare-30' in commands[2] and '--compare-300' in commands[2]
    assert result['source_replay_T30_T300'] == 1.00001
    assert result['N300_unique_paid'] == 6325
    assert [r['count'] for r in result['source_replay_results']] == [100, 100]
    assert result['status'] == 'FAIL'  # gsim-only is NEVER a hybrid P6 PASS
    assert result['full_p6_selected_backend_acceptance'] is False
    assert 'pass_count' not in result  # no invented M1 fractional denominator


def test_p6_source_ratio_and_incomplete_replay_are_not_accepted():
    for ratio, incomplete, expected in (
        (1.02, False, 'P6_NUMERIC_SATURATION_EXCEEDS_1_PERCENT'),
        (1.0, True, 'P6_INDEPENDENT_100MOB_REPLAY_INCOMPLETE'),
    ):
        with patch('tools.wf_gate_p6_full_source.subprocess.run',
                   side_effect=_fake_paid_runner([], ratio=ratio, incomplete=incomplete)):
            result = run_full_source_comparison(Path('/tmp'), 'druid', 30)
        assert result['status'] == 'FAIL'
        assert expected in result['reasons']


def test_p6_full_source_mode_never_fakes_unsupported_checkpoint():
    with patch('tools.wf_gate_p6_full_source.subprocess.run') as execute:
        result = run_full_source_comparison(Path('/tmp'), 'warlock', 60)
    assert result['status'] == 'BLOCKED'
    execute.assert_not_called()


def test_p6_live_gate_dispatches_only_when_full_mode_explicitly_enabled():
    from tools.wf_gate_p6_live import run_live
    from unittest.mock import patch
    with patch.dict('os.environ', {'FOREVER_P6_FULL_SOURCE_COMPARE': '1'}):
        with patch('tools.wf_gate_p6_full_source.run_full_source_comparison',
                   return_value={'status': 'FAIL', 'reasons': ['HYBRID_PENDING']}) as full:
            report = run_live(Path('/tmp'), 'druid', 30, spec='unrestricted')
    assert report['status'] == 'FAIL'
    full.assert_called_once_with(Path('/tmp'), 'druid', 30, spec='unrestricted')
