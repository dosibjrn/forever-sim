"""WF286: batch source-index normalization and rank-complete adaptive frontier."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sqlite3

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
from src.game.model.ir import DamageEffect
from src.game.runtime import ActorState, TargetState, execute_action
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
from tools.ingest_source_index_effect_candidates_sqlite import ingest


def test_every_independently_sourced_rank_is_represented_at_l60():
    with sqlite3.connect(DEFAULT_DB) as conn:
        all_semantic_ids = {r[0] for r in conn.execute(
            "SELECT spell_id FROM ability_semantic_source_facts WHERE class_key='druid'")}
    assert len(all_semantic_ids) == 44
    ir = build_game_ir_slice(class_key='druid', level=60)
    in_ir = {sid for action in ir.actions for sid in _source_spell_ids(action)}
    assert all_semantic_ids <= in_ir
    assert len({action.id for action in ir.actions}) == len(ir.actions)
    assert ir.provenance['indexed_ability_coverage']['exact_source_rank_in_ir_count'] == 50
    assert not ir.provenance['complete_source_action_coverage']
    assert ir.provenance['indexed_ability_coverage']['unrepresented_rank_count'] == 229


def test_low_rank_damage_uses_real_executor_and_data_only_source_change(tmp_path):
    ir = build_game_ir_slice(class_key='druid', level=60)
    rank = next(a for a in ir.actions if a.id == 'source_spell:2912')
    assert rank.effects and isinstance(rank.effects[0], DamageEffect)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    target = TargetState.with_health('test_target', 2000)
    result = execute_action(action=rank, actor=actor, target=target)
    assert any(e.kind == 'Damage' for e in result.events)
    with sqlite3.connect(DEFAULT_DB) as src, sqlite3.connect(tmp_path/'stage.sqlite') as dest:
        src.backup(dest)
    db = tmp_path/'stage.sqlite'
    with sqlite3.connect(db) as conn:
        raw = conn.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='druid' AND spell_id=2912").fetchone()[0]
        payload = json.loads(raw)
        old = payload['envChange']['after']['text']
        assert old == 'Causes 79 to 96 Arcane damage to the target.'
        payload['envChange']['after']['text'] = 'Causes 99 to 119 Arcane damage to the target.'
        conn.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='druid' AND spell_id=2912",
                     (json.dumps(payload),))
    changed = build_game_ir_slice(class_key='druid', level=60, ability_db_path=db)
    changed_rank = next(a for a in changed.actions if a.id == 'source_spell:2912')
    assert changed_rank.effects[0].base_min == 99
    assert changed_rank.effects[0].base_min != rank.effects[0].base_min
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM ability_semantic_source_facts WHERE class_key='druid' AND spell_id=2912")
    blocked = build_game_ir_slice(class_key='druid', level=60, ability_db_path=db)
    assert not any(a.id == 'source_spell:2912' for a in blocked.actions)
    assert blocked.provenance['indexed_ability_coverage']['unrepresented_rank_count'] == 230


def test_nine_class_batch_candidates_are_typed_but_not_promoted(tmp_path):
    with sqlite3.connect(DEFAULT_DB) as src, sqlite3.connect(tmp_path/'copy.sqlite') as dest:
        src.backup(dest)
    db = tmp_path/'copy.sqlite'
    with sqlite3.connect(db) as conn:
        conn.execute('DROP TABLE ability_index_effect_candidates')
    summary = ingest(db, captured_at='2026-10-12T00:00:00Z')
    assert summary['indexed_abilities'] == 2255
    assert summary['typed_candidates'] == 326
    assert len(summary['by_class']) == 9
    assert summary['executable_promotions'] == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM ability_index_effect_candidates').fetchone()[0] == 326
        assert conn.execute('SELECT count(*) FROM ability_index_effect_candidates WHERE spell_power_coefficient IS NOT NULL').fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM ability_index_effect_candidates WHERE missing_fields_json NOT LIKE '%acquisition_gate%'").fetchone()[0] == 0
    mage = build_game_ir_slice(class_key='mage', level=20, ability_db_path=db)
    assert mage.provenance['indexed_ability_coverage']['typed_index_candidate_count'] > 0
    assert mage.provenance['indexed_ability_coverage']['exact_source_rank_in_ir_count'] == 5


def test_stale_index_candidate_not_trusted_until_batch_reingest(tmp_path):
    with sqlite3.connect(DEFAULT_DB) as src, sqlite3.connect(tmp_path/'copy.sqlite') as dest:
        src.backup(dest)
    db = tmp_path/'copy.sqlite'
    with sqlite3.connect(db) as conn:
        raw = conn.execute("SELECT raw_listview_json FROM spell_index WHERE class_key='priest' AND spell_id=2061").fetchone()[0]
        payload = json.loads(raw)
        payload['envChange']['after']['text'] = 'Heals a friendly target for 194 to 233.'
        conn.execute("UPDATE spell_index SET raw_listview_json=? WHERE class_key='priest' AND spell_id=2061", (json.dumps(payload),))
    ir = build_game_ir_slice(class_key='priest', level=20, ability_db_path=db)
    coverage = next(f for f in ir.source_facts if f.get('fact_kind') == 'canonical_indexed_ability_coverage')
    row = next(r for r in coverage['records'] if r['spell_id'] == 2061)
    assert row['typed_index_status'] == 'STALE_SOURCE_CAPTURE_REINGEST_REQUIRED'
    assert 'typed_index_shape' not in row
    ingest(db, captured_at='2026-10-12T00:00:00Z')
    updated = build_game_ir_slice(class_key='priest', level=20, ability_db_path=db)
    coverage = next(f for f in updated.source_facts if f.get('fact_kind') == 'canonical_indexed_ability_coverage')
    row = next(r for r in coverage['records'] if r['spell_id'] == 2061)
    assert row['typed_index_shape'] == 'direct_heal'
    assert 'spell_power_coefficient' in row['typed_index_missing_fields']
    assert not row['matched_action_ids']


def test_large_rank_frontier_stages_all_pairs_without_hard_pruning():
    result = run_source_stateful_budgeted(class_key='druid', level=60,
        max_l2_attempts=45, max_event_transitions=12000, use_l1=False)
    assert result['staged_pairs']
    assert result['seed_count'] == 990
    assert result['l0_candidates_generated'] <= result['seed_count']
    assert len(result['pair_expansion_decisions']) >= 5
    assert all(0 < x['new_pairs'] <= 90 for x in result['pair_expansion_decisions'])
    assert not result['unexpanded_pair_heads']
    assert result['l0_candidates_generated'] == result['seed_count']
    assert result['event_transitions'] <= result['max_event_transitions']
    assert result['l2_attempts'] <= result['max_l2_attempts']
    assert result['seed_unattempted'] > 0
