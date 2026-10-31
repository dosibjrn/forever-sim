"""WF482: P2 must resolve captured tree rows and observe real GCD behavior."""
from dataclasses import replace
from pathlib import Path
import json
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import _witness
from src.game.data.forever.checkpoint_p2_execution_gate import _executable_filler_witness
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection, available_talent_points, talented_bonus_for_level
from tools import wf_gate_p2_live as gate
from tools.ingest_talent_tree_rows_sqlite import ingest

SOURCE = Path(__file__).resolve().parents[1] / 'evidence/wf482_druid_tree_rows_20261017.json'


@pytest.fixture(scope='module')
def gcd_ir():
    ir=build_game_ir_slice(class_key='druid', level=20)
    compiled,_=compile_talent_runtime(ir)
    talent=next(t for t in compiled.talents if t.id=='gift_of_the_earthmother')
    level=20
    bonus=talented_bonus_for_level(level)
    points=available_talent_points(level, bonus_talent_points=bonus)
    step=int(compiled.provenance['talent_tree_rules']['points_per_row'])
    witness=_witness(talent,1,compiled.talents,points,step)
    assert witness
    witness=_executable_filler_witness(talent,1,compiled.talents,points=points,step=step)
    assert witness
    prior=dict(witness)
    prior.pop(talent.id)
    before,_=apply_talent_selection(compiled,prior,level=level,bonus_talent_points=bonus)
    after,_=apply_talent_selection(compiled,witness,level=level,bonus_talent_points=bonus)
    return before,after,next(m for m in talent.ranks[0].modifiers if m.kind=='gcd_delta_s')


def test_gcd_probe_executes_and_checks_all_action_ranks(gcd_ir):
    before,after,mod=gcd_ir
    r=gate._gcd_runtime_witness(before,after,mod)
    assert r and r['probe']=='paired_production_gcd_readiness'
    assert r['checked_ir_actions']
    assert set(r['checked_ir_actions'])=={a.id for a in after.actions if a.family_key==mod.target_id}
    assert r['before_gcd_ready_s']>r['after_gcd_ready_s']


def test_gcd_rejects_wrong_source_delta(gcd_ir):
    before,after,mod=gcd_ir
    assert gate._gcd_runtime_witness(before,after,replace(mod,value=mod.value*2)) is None


def test_gcd_rejects_wrong_ir_rank(gcd_ir):
    before,after,mod=gcd_ir
    actions=list(after.actions)
    indices=[i for i,a in enumerate(actions) if a.family_key==mod.target_id]
    assert indices
    i=indices[-1]
    actions[i]=replace(actions[i],gcd_s=actions[i].gcd_s+0.05)
    assert gate._gcd_runtime_witness(before,replace(after,actions=tuple(actions)),mod) is None


def test_gcd_rejects_nonexecuting_runtime(gcd_ir,monkeypatch):
    before,after,mod=gcd_ir
    original=gate._action_runtime_probe
    def no_effect(ir,action,*,observe_periodic=False):
        result=original(ir,action,observe_periodic=observe_periodic)
        if result is None:return None
        return {**result,'gcd_ready_s':1.5}
    monkeypatch.setattr(gate,'_action_runtime_probe',no_effect)
    assert gate._gcd_runtime_witness(before,after,mod) is None


def test_all_eight_rows_are_canonical_sqlite_facts_after_ingest(tmp_path):
    output=tmp_path/'talents.sqlite'
    output.write_bytes(Path(DEFAULT_DB).read_bytes())
    with sqlite3.connect(output) as db:
        # Re-enact actual missing-row state, including on a reconstructed baseline.
        db.execute("DELETE FROM talent_tree_row_facts WHERE class_key='druid' AND spell_id IN (16958,16850,17123,5570,17007,24858,16972,16909)")
    first=ingest(output,SOURCE)
    assert first['imported']==8
    second=ingest(output,SOURCE)
    assert second['imported']==8
    with sqlite3.connect(output) as db:
        rows=db.execute("SELECT s.name,t.tree_row,t.tree_col,t.authority,t.source_url "
          "FROM talent_tree_row_facts t JOIN spell_index s ON s.spell_id=t.spell_id "
          "WHERE t.class_key='druid' AND s.class_key='druid' AND s.kind='talents' "
          "AND t.capture_id='wf482-druid-remaining-tree-rows-2026-10-17'").fetchall()
    assert len(rows)==8
    expected={x['name']:x['row'] for x in json.loads(SOURCE.read_text())['facts']}
    assert {name:row for name,row,*_ in rows}==expected
    assert all(col is None and authority=='secondary_provisional_row'
               and url=='https://talentsforever.com/druid/talents'
               for _,_,col,authority,url in rows)


def test_no_unresolved_reachability_with_source_row_ingestion():
    result=gate.run_live(Path(__file__).resolve().parents[1], 'druid',20)
    assert result['unresolved_count']==0
    assert result['reachability_count']>=88
    assert result['status']=='FAIL'  # Missing talent implementations are real blockers.
    assert any('IMPLEMENTATION_MISSING' in x for x in result['reasons'])
