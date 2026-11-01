"""WF318: source-index multi-atom actions execute as one paid L1 cast."""
from __future__ import annotations
import json, shutil, sqlite3
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_effect_atoms import ingest
from src.game.data.forever.source_index_composite_l1 import (
    source_index_composite_l1_action, probe_index_composite_l1)
from src.game.data.forever.source_partial_l1 import partial_source_action
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import execute_action
from tools.wf318_nine_class_composite_batch import measure

DB=Path('data/forever/catalogue/forever_abilities.sqlite')


@pytest.mark.parametrize('cls,sid,damage,cost',[
    ('druid',8924,41,50),
    ('shaman',8050,52,55),
    ('warlock',707,51,45),
])
def test_composite_one_paid_cast(cls,sid,damage,cost):
    ir=build_game_ir_slice(class_key=cls,level=20)
    action,proof=source_index_composite_l1_action(ir,class_key=cls,spell_id=sid)
    assert len(action.effects)==2
    assert action.costs[0].amount==cost
    assert action.metadata['never_l2_legal'] is True
    assert proof['source_index_atom_count']==2
    actor=ActorState.from_ir(ir.actor,ir.resources,())
    result=execute_action(action=action,actor=actor,
        target=TargetState.with_health('synthetic',1e6),allow_source_partial_l1=True)
    assert result.total_damage==pytest.approx(damage)
    assert sum(e.kind=='ActionStarted' for e in result.events)==1
    assert sum(e.payload['resource_spend'][0]['amount'] for e in result.events
               if e.kind=='ActionStarted')==cost
    with pytest.raises(ValueError,match='SOURCE_PARTIAL_L1_ACTION_FORBIDDEN'):
        execute_action(action=action,actor=ActorState.from_ir(ir.actor,ir.resources,()),
            target=TargetState.with_health('L2_forbidden',1e6))


def test_full_nine_class_inventory_and_ambiguous_blockers():
    l20=measure(DB,level=20)
    l60=measure(DB,level=60)
    assert l20['indexed_multi_atom_candidates']==26
    assert l20['executed_composite_l1']>=13
    assert l60['indexed_multi_atom_candidates']>=98
    assert l60['executed_composite_l1']>=53
    assert l20['validated_checkpoints']==l60['validated_checkpoints']==0
    assert l20['blocked_composite_l1']+l20['executed_composite_l1']==26
    assert l20['blocker_histogram']['AMBIGUOUS_DUPLICATE_COMPOSITE_FRAGMENT']>0
    assert l60['legal_routes']==0


def test_negative_rank_control_duplicates_and_source_l2_gate():
    ir=build_game_ir_slice(class_key='druid',level=20)
    for sid,reason in [(8926,'INDEX_RANK_EXCEEDS_ACTOR_LEVEL'),
                       (1079,'AMBIGUOUS_DUPLICATE_COMPOSITE_FRAGMENT')]:
        with pytest.raises(ValueError,match=reason):
            source_index_composite_l1_action(ir,class_key='druid',spell_id=sid)
    mage=build_game_ir_slice(class_key='mage',level=20)
    with pytest.raises(ValueError,match='USE_EXISTING_VERIFIED_DETAIL_COMPOSER'):
        source_index_composite_l1_action(mage,class_key='mage',spell_id=133)
    with pytest.raises(ValueError,match='USE_EXISTING_VERIFIED_DETAIL_COMPOSER'):
        source_index_composite_l1_action(mage,class_key='mage',spell_id=116)
    with pytest.raises(ValueError,match='COMPOSITE_INDEX_L2_L3_FORBIDDEN'):
        source_index_composite_l1_action(ir,class_key='druid',spell_id=8924,execution_tier='L2')
    # Existing single-fragment adapter must also reject higher-than-actor ranks.
    with pytest.raises(ValueError,match='SOURCE_RANK_EXCEEDS_ACTOR_LEVEL'):
        partial_source_action(ir,class_key='druid',spell_id=8926,fragment_kind='direct_damage')


def test_source_only_change_reingest_changes_both_composite_effects(tmp_path):
    stage=tmp_path/'source.sqlite';shutil.copy2(DB,stage)
    ir=build_game_ir_slice(class_key='druid',level=20)
    before=probe_index_composite_l1(ir,class_key='druid',spell_id=8924,db_path=stage)
    assert before['damage']==41
    with sqlite3.connect(stage) as db:
        raw=json.loads(db.execute('SELECT raw_listview_json FROM spell_index WHERE class_key=? AND spell_id=?',
            ('druid',8924)).fetchone()[0])
        text=raw['envChange']['after']['text']
        assert 'additional 24 Arcane damage over 12 sec' in text
        raw['envChange']['after']['text']=text.replace('additional 24 Arcane damage over 12 sec',
            'additional 34 Arcane damage over 12 sec')
        db.execute('UPDATE spell_index SET raw_listview_json=? WHERE class_key=? AND spell_id=?',
            (json.dumps(raw,sort_keys=True),'druid',8924))
    with pytest.raises(ValueError,match='STALE_ATOM_INDEX_REINGEST_REQUIRED'):
        source_index_composite_l1_action(ir,class_key='druid',spell_id=8924,db_path=stage)
    ingest(stage)
    after=probe_index_composite_l1(ir,class_key='druid',spell_id=8924,db_path=stage)
    assert after['damage']-before['damage']==10
