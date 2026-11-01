"""WF283: source-tier corridors compete under ONE paid production controller."""
import json
from pathlib import Path
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talents import validate_talent_selection
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from tools.wf283_corridor_benchmark import ARGS


def test_tree_diverse_source_corridors_are_real_paid_l2_and_beat_heldout():
    ir=build_game_ir_slice(class_key='druid',level=20)
    r=run_source_budgeted_joint_talents(**ARGS,talent_corridor_reserve=6)
    assert r['attempted']<=ARGS['max_evaluations']
    assert r['event_transitions']<=ARGS['max_event_transitions']
    assert r['attempted']==r['evaluated']+r['blocked']
    assert r['source_corridors_evaluated']==6
    assert r['source_corridors_unvisited']==[]
    trees={t.id:t.tree_key for t in ir.talents}
    covered=set()
    for s in r['stages']:
        validate_talent_selection(ir,s['allocation'],level=20)
        assert s['attempted']<=ARGS['evaluations_per_talent']
        if s['operation']=='source_tier_corridor':
            covered.update(trees[f] for f in s['allocation'])
            assert s['attempted']>0
            assert s['gear_policy_result']['policy_search_backend']=='stateful'
    assert covered=={'balance','feral','restoration'}
    assert r['winner']['score_s_per_mob']==pytest.approx(16.838119142532577)
    heldout=json.loads((Path(__file__).resolve().parents[1]/'fixtures/wf243_heldout_feral_l20.json').read_text())
    assert heldout['talent_allocation'] not in r['source_corridors_reserved']
    assert r['winner']['score_s_per_mob']<17.887004619287094
    assert not r['complete_search']


def test_corridor_reserve_rejects_invalid_and_never_overruns_small_budget():
    with pytest.raises(ValueError,match='talent_corridor_reserve'):
        run_source_budgeted_joint_talents(**{**ARGS,'max_evaluations':2},talent_corridor_reserve=-1)
    r=run_source_budgeted_joint_talents(**{**ARGS,'max_evaluations':5,
        'evaluations_per_talent':2,'initial_search':2,'search_per_gear':2,
        'max_event_transitions':250},talent_corridor_reserve=6)
    assert r['attempted']<=5
    assert r['event_transitions']<=250
    assert r['source_corridors_evaluated']<6
    assert len(r['source_corridors_unvisited'])>0
    assert r['attempted']==r['evaluated']+r['blocked']


def test_default_does_not_inject_source_corridors():
    r=run_source_budgeted_joint_talents(**{**ARGS,'max_evaluations':4,
        'evaluations_per_talent':2,'initial_search':2,'search_per_gear':2,
        'max_event_transitions':350})
    assert r['talent_corridor_reserve']==0
    assert not r['source_corridors_reserved']
    assert all(s['operation']!='source_tier_corridor' for s in r['stages'])
