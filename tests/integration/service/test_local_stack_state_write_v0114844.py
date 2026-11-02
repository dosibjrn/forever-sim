from __future__ import annotations

import json
from pathlib import Path

from src.service import local_stack


def test_write_json_falls_back_to_in_place_when_replace_is_locked(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / 'local_stack.json'
    path.write_text('{"old": true}', encoding='utf-8')

    calls = {'replace': 0}

    def locked_replace(src, dst):
        calls['replace'] += 1
        raise PermissionError('simulated Windows sharing violation')

    monkeypatch.setattr(local_stack.os, 'replace', locked_replace)
    monkeypatch.setattr(local_stack.time, 'sleep', lambda _delay: None)

    assert local_stack._write_json(path, {'token': 'abc', 'children': {}}) is True
    assert calls['replace'] == 6
    assert json.loads(path.read_text(encoding='utf-8')) == {'token': 'abc', 'children': {}}
    assert not list(tmp_path.glob('*.tmp'))


def test_best_effort_runtime_state_failure_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / 'local_stack.json'
    path.write_text('{"old": true}', encoding='utf-8')
    real_write_text = Path.write_text

    def locked_replace(src, dst):
        raise PermissionError('simulated Windows sharing violation')

    def locked_destination_write(self: Path, data: str, *args, **kwargs):
        if self == path:
            raise PermissionError('destination still locked')
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(local_stack.os, 'replace', locked_replace)
    monkeypatch.setattr(local_stack.time, 'sleep', lambda _delay: None)
    monkeypatch.setattr(Path, 'write_text', locked_destination_write)

    assert local_stack._write_json(path, {'token': 'abc'}, best_effort=True) is False
