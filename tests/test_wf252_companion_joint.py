"""Real sourced pet + owner shared combat/recovery and joint-policy regressions."""
from __future__ import annotations
from dataclasses import replace
import sqlite3
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_companions import source_enrich_companions
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.gear import apply_gear_selection
from src.game.multi_pull import evaluate_repeated_pulls
from src.shared.leveling.objective import representative_hp
from src.v2.source_companion_policy_search import companion_policy_envelope
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_legal_beam import search_source_legal_beam
from tools.wf252_ingest_companions import ingest


def hunter(level=20):return build_game_ir_slice(class_key='hunter',level=level)


def test_sourced_companion_ranks_10_16_20_and_gear_inheritance():
    for level,ids in ((10,{17255,16828}),(16,{17256,16829}),(20,{17256,16829})):
        ir=hunter(level)
        assert len(ir.companions)==1 and len(ir.actor_links)==2
        pet=ir.companions[0]
        skills=[a for a in ir.actions if a.owner_actor_id==pet.id]
        assert {int(a.id.split(':')[-1]) for a in skills}==ids
        assert all(a.provenance[0]['source_url'].startswith('https://www.wowhead.com/forever/spell=') for a in skills)
        assert len([a for a in ir.auto_attacks if a.owner_actor_id==pet.id])==1
        assert any(x['family']=='source_companions' for x in ir.source_facts)


def test_joint_pet_policy_options_are_independent_and_exhaustive_within_source_slice():
    ir=hunter();opts,coverage=companion_policy_envelope(ir)
    assert coverage['candidate_count']==5 and not coverage['truncated']
    orders={tuple(rule.action_id for p in candidate.values() for rule in p.rules) for candidate in opts}
    assert len(orders)==5 and () in orders
    assert {len(x) for x in orders}=={0,1,2}
    limited,meta=companion_policy_envelope(ir,max_policies=1)
    assert len(limited)==1 and meta['truncated']
    with pytest.raises(ValueError,match='budget'):
        companion_policy_envelope(ir,max_policies=0)


def test_real_named_gear_owner_and_pet_attack_with_focus_continuity():
    ir=hunter()
    gear=_gear_envelope('hunter',20,max_gear_candidates=256,
        required_level_policy='observed',include_melee_gear=True,ir_slice=ir)[0]['selection']
    geared,_=apply_gear_selection(ir,aggregate_stats=gear.aggregate_stats,
        selected_items=tuple(gear.slots.values()),source='sourced_named_gear')
    opts,_=companion_policy_envelope(geared)
    policy=next(x for x in geared.policies if not x.provenance.get('companion_policy'))
    scored=evaluate_repeated_pulls(ir_slice=geared,policy=policy,level=20,
        target_health=representative_hp(20),count=3,
        apply_target_defense=True,companion_policy_override=opts[-1])
    assert scored.seconds_per_mob>0
    assert len(scored.pulls)==3
    assert all(p['damage_by_role']['player']>0 and p['damage_by_role']['pet']>0 for p in scored.pulls)
    assert all(p['recovery_s']>0 for p in scored.pulls)
    assert all(p['companion_resources_at_kill'] for p in scored.pulls)
    assert any(a['actor_id']==geared.companions[0].id
               for p in scored.pulls for a in p['selected_actions'])
    assert scored.pulls[1]['companion_resources_at_kill'] != scored.pulls[0]['companion_resources_at_kill']


def test_independent_search_scores_pet_with_same_incoming_recovery_objective():
    result=search_source_legal_beam(class_key='hunter',level=20,
        max_allocations=2,screening_gear_count=1,finalists=1,policy_cap=5,beam_width=1)
    winner=result['independent_winner']
    assert winner['seconds_per_mob']>0
    assert len(winner['gear_slots'])==16
    assert winner['best_policy']['companion_policies']
    assert winner['talent_allocation']=={}  # explicitly incomplete source, not 11 points silently granted
    assert any(p['damage_by_role']['pet']>0 for p in winner['best_policy']['pulls'])


def test_bad_companion_skill_source_fails_closed(tmp_path):
    tmp=tmp_path/'bad.sqlite'
    with sqlite3.connect(DEFAULT_DB) as source,sqlite3.connect(tmp) as dest:source.backup(dest)
    with sqlite3.connect(tmp) as db:
        db.execute("UPDATE companion_skill_source_facts SET focus_cost=-1 WHERE skill_key='bite' AND rank=3")
    # Enrichment receives a native owner slice with no existing companion.
    source=hunter()
    owner=replace(source,companions=(),actor_links=(),
        actions=tuple(a for a in source.actions if a.owner_actor_id==source.actor.id),
        auto_attacks=tuple(a for a in source.auto_attacks if a.owner_actor_id==source.actor.id),
        policies=tuple(p for p in source.policies if not p.provenance.get('companion_policy')))
    with pytest.raises(ValueError,match='invalid sourced companion rank'):
        source_enrich_companions(owner,db_path=tmp)


def test_idempotent_capture_and_paladin_does_not_gain_hunter_pet():
    before=sqlite3.connect(DEFAULT_DB).execute('SELECT COUNT(*) FROM companion_skill_source_facts').fetchone()[0]
    assert ingest()['skill_rows']==6
    after=sqlite3.connect(DEFAULT_DB).execute('SELECT COUNT(*) FROM companion_skill_source_facts').fetchone()[0]
    assert before==after==6
    assert not build_game_ir_slice(class_key='paladin',level=20).companions
