"""Druid L20 source parity: one source DB all the way to the real L2 scorer."""
from __future__ import annotations

import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from src.forever_build import FOREVER_BUILD_ENV, FOREVER_BUILD_SOURCE_ENV
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_effect_atoms import ingest as ingest_atoms
from src.v2.source_stateful_budgeted import _make_policy
from src.v2.generic_backend import _policy_combat_evaluation


@pytest.fixture(autouse=True)
def current_build(monkeypatch):
    monkeypatch.setenv(FOREVER_BUILD_ENV, '2026-10-13')
    monkeypatch.setenv(FOREVER_BUILD_SOURCE_ENV, 'wf319_test_current_build')


def _effect(ir, family, kind):
    matches = [e for a in ir.actions if a.family_key == family
               for e in a.effects if type(e).__name__ == kind]
    assert len(matches) == 1, (family, kind, len(matches))
    return matches[0]


def _changed_stage(tmp_path):
    stage = tmp_path / 'mutated-ability-index.sqlite'
    shutil.copy2(DEFAULT_DB, stage)
    changes = {
        5178: 'Causes 52 to 57 Nature damage to the target.',
        8925: 'Burns the enemy for 45 to 49 Arcane damage and then an additional 76 Arcane damage over 12 sec.',
        1430: 'Heals the target for 192 over 12 sec.',
    }
    with sqlite3.connect(stage) as db:
        for sid, text in changes.items():
            raw_text = db.execute('SELECT raw_listview_json FROM spell_index '
                                  "WHERE class_key='druid' AND spell_id=?", (sid,)).fetchone()[0]
            raw = json.loads(raw_text)
            raw['envChange']['after']['text'] = text
            db.execute('UPDATE spell_index SET raw_listview_json=? '
                       "WHERE class_key='druid' AND spell_id=?", (json.dumps(raw), sid))
    return stage


def test_current_build_index_parity_is_actual_runtime_data():
    ir = build_game_ir_slice(class_key='druid', level=20)
    assert (_effect(ir, 'wrath', 'DamageEffect').base_min,
            _effect(ir, 'wrath', 'DamageEffect').base_max) == (32, 37)
    assert (_effect(ir, 'moonfire', 'DamageEffect').base_min,
            _effect(ir, 'moonfire', 'PeriodicEffect').total_base_damage) == (25, 36)
    assert _effect(ir, 'rejuvenation', 'PeriodicHealEffect').total_base_heal == 92
    # Source index is later than September's approximate beta-tuning note.
    # Applying that multiplier again would be an unverified double count.
    assert not _effect(ir, 'wrath', 'DamageEffect').unsupported_semantics


def test_data_only_source_patch_changes_real_l2_and_restores_canonical(tmp_path):
    baseline = build_game_ir_slice(class_key='druid', level=20)
    stage = _changed_stage(tmp_path)
    # Derived index-atom ledger must be reingested from the changed source;
    # a stale SHA must never be accepted as an unchanged source.
    with pytest.raises(ValueError, match='STALE_ATOM_INDEX_REINGEST_REQUIRED'):
        build_game_ir_slice(class_key='druid', level=20, ability_db_path=stage)
    ingested = ingest_atoms(stage)
    assert ingested['indexed_ranks'] >= 100
    altered = build_game_ir_slice(class_key='druid', level=20, ability_db_path=stage)
    assert (_effect(altered, 'wrath', 'DamageEffect').base_min,
            _effect(altered, 'moonfire', 'DamageEffect').base_min,
            _effect(altered, 'moonfire', 'PeriodicEffect').total_base_damage,
            _effect(altered, 'rejuvenation', 'PeriodicHealEffect').total_base_heal) == (52, 45, 76, 192)
    assert _effect(baseline, 'wrath', 'DamageEffect').base_min == 32
    # Same real executor, identical policy, incoming attacks and recovery.
    scores = []
    for ir in (baseline, altered):
        policy = _make_policy(ir, 'wrath:5178')
        score, execution, details = _policy_combat_evaluation(
            ir, level=20, policy_override=policy, schedule_incoming_attacks=True)
        assert score is not None and execution.timeline.target_defeated
        assert details['actor_survived'] and details['event_transitions_new'] > 0
        scores.append(score.seconds_per_mob)
    assert scores[1] < scores[0] - 5.0, scores
    restored = build_game_ir_slice(class_key='druid', level=20)
    assert _effect(restored, 'wrath', 'DamageEffect').base_min == 32
    assert _effect(restored, 'rejuvenation', 'PeriodicHealEffect').total_base_heal == 92


def test_scope_resets_after_failed_parse_and_concurrent_builds(tmp_path):
    stage = _changed_stage(tmp_path)
    ingest_atoms(stage)
    def build(path):
        ir = build_game_ir_slice(class_key='druid', level=20, ability_db_path=path)
        return _effect(ir, 'wrath', 'DamageEffect').base_min
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(build, [None, stage, None, stage])) == [32, 52, 32, 52]
    with sqlite3.connect(stage) as db:
        raw = json.loads(db.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='druid' AND spell_id=5178").fetchone()[0])
        raw['envChange']['after']['text'] = 'UNKNOWN SERVER EFFECT'
        db.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='druid' AND spell_id=5178", (json.dumps(raw),))
    with pytest.raises(ValueError):
        build_game_ir_slice(class_key='druid', level=20, ability_db_path=stage)
    assert build(None) == 32


def test_checkpoint_rejects_historical_build_and_runs_real_current_joint_search():
    from datetime import date
    from tools.wf319_druid_l20_current_source import current_l20
    with pytest.raises(ValueError, match='STALE_BUILD_BEFORE_SOURCE_CAPTURE'):
        current_l20(as_of=date(2026, 10, 2))
    result = current_l20(as_of=date(2026, 10, 13))
    assert result['checkpoint'] == 'druid:L20:unrestricted'
    assert result['accepted_checkpoints'] == 0
    assert result['acceptance_status'] == 'BLOCKED_SOURCE_INCOMPLETE'
    assert len(result['source_runtime_index_parity']) == 5
    measured = result['L2_existing_joint_search']
    assert measured['comparison']['search_l2_attempts'] == 135
    assert measured['comparison']['search_executor_events'] > 0
    assert measured['comparison']['winner_independent_scratch_replay_s_per_mob'] == pytest.approx(
        measured['comparison']['new_score_s_per_mob'])
