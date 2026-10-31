"""Current source tier-3 Primal Bite talent is the old Decisions `mangle` alias.

A sourced spellbook rank is NOT sufficient for talent-locked executability.
"""
from __future__ import annotations
import sqlite3,tempfile
from pathlib import Path
import pytest
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.source_observed_rank_parity import ingest_observations
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import apply_talent_selection
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.rulesets.forever.classes.druid import Talents
from src.rulesets.forever.classes.druid.mechanics import _bear_pack

ROOT=Path(__file__).resolve().parents[1]


def test_primal_bite_talent_unlock_new_and_old_names():
    with tempfile.TemporaryDirectory() as tmp:
        db=Path(tmp)/'source.sqlite'
        source=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
        with sqlite3.connect(f'file:{source.resolve()}?mode=ro',uri=True) as s, sqlite3.connect(db) as d:
            s.backup(d)
        ingest_observations(db,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
        ingest_control(db,ROOT/'evidence/wf321/druid_l20_control_observations.json')
        with ability_source_scope(db):
            ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
            source_talent=next(x for x in ir.talents if x.id=='primal_bite')
            assert source_talent.prerequisite=={'talent_id':'savage_fury','required_rank':2}
            assert source_talent.ranks[0].modifiers[0].kind=='unlock_action_family'
            none,_=apply_talent_selection(ir,{},level=30)
            assert not any(x.family_key=='primal_bite' for x in none.actions)
            assert not any('primal_bite:' in aid for m in none.modes for aid in m.enabled_action_ids)
            allocation=dict(ferocity=5,heart_of_the_wild=5,feral_swiftness=2,
                            savage_fury=2,sharpened_claws=2,primal_bite=1)
            chosen,application=apply_talent_selection(ir,allocation,level=30)
            ability=next(a for a in chosen.actions if a.family_key=='primal_bite')
            assert ability.id=='primal_bite:25'
            assert any('primal_bite:' in aid for m in chosen.modes for aid in m.enabled_action_ids)
            assert any(x['kind']=='unlock_action_family' for x in application.applied_modifiers)
    old=_bear_pack(30,Talents(ferocity=5,savage_fury=2,sharpened_claws=2,mangle=1),1)
    old_no=_bear_pack(30,Talents(ferocity=5,savage_fury=2,sharpened_claws=2,mangle=0),1)
    assert 'Primal Bite' in old['rotation']
    assert 'Primal Bite' not in old_no['rotation']
