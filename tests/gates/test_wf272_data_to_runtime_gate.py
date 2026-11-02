"""Data-only canonical fact mutation must reach policy discovery and real runtime."""
from dataclasses import replace
import json
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_ability_semantics import source_ability_actions
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import CombatRuntime
from src.v2.source_button_discovery import discover_source_combat_buttons


def _rebuild(base, db):
    ids={a.id for a in base.actions if a.family_key=='rake'}
    stripped=replace(base,actions=tuple(a for a in base.actions if a.id not in ids),
        modes=tuple(replace(m,enabled_action_ids=(None if m.enabled_action_ids is None else
             tuple(a for a in m.enabled_action_ids if a not in ids))) for m in base.modes))
    return source_ability_actions(stripped,class_key='druid',level=27,db_path=db)


def _damage(ir):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('cat')
    actor.resources['energy']=100.
    actor.stats['melee_crit_chance']=0.
    target=TargetState.with_health('target',9999.)
    runtime=CombatRuntime(actor=actor,target=target,auto_attacks=())
    runtime.schedule_action(next(a for a in ir.actions if a.family_key=='rake'))
    runtime.run_until_idle()
    return sum(e.payload['amount'] for e in runtime.result().events
               if e.kind=='Damage' and e.payload.get('applied'))


def test_sqlite_fact_to_generic_ir_to_button_to_real_combat(tmp_path):
    base=build_game_ir_slice(class_key='druid',level=27)
    db=tmp_path/'source.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(db) as dst:src.backup(dst)
    original=_damage(base)
    with sqlite3.connect(db) as conn:
        obj=json.loads(conn.execute('SELECT raw_listview_json FROM spell_index WHERE spell_id=1822').fetchone()[0])
        text=obj['envChange']['after']['text']
        assert 'for 23 damage' in text
        obj['envChange']['after']['text']=text.replace('for 23 damage','for 123 damage')
        conn.execute('UPDATE spell_index SET raw_listview_json=? WHERE spell_id=1822',(json.dumps(obj),))
    modified=_rebuild(base,db)
    assert 'rake:1822' in discover_source_combat_buttons(modified,level=27,mode_id='cat')['action_ids']
    assert _damage(modified)==pytest.approx(original+100)
    assert _damage(base)==pytest.approx(original)


def test_invalid_new_source_fact_blocks_generic_compilation(tmp_path):
    base=build_game_ir_slice(class_key='druid',level=27)
    db=tmp_path/'invalid.sqlite'
    with sqlite3.connect(DEFAULT_DB) as src,sqlite3.connect(db) as dst:src.backup(dst)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE sourced_direct_periodic_melee_semantics SET crit_multiplier=-1 WHERE spell_id=1822')
    with pytest.raises(ValueError,match='invalid sourced melee'):
        _rebuild(base,db)
