"""Check that SoD rune setup is opt-in, but legitimate talent grants survive."""
import json,sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_l0 import action_frontier
from src.game.data.forever.source_checkpoint_web_l0 import ingest_observations
from src.game.data.forever.source_observed_rank_parity import ingest_observations as ingest_beta
from src.game.data.forever.source_queued_swing import ingest as ingest_maul
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_observed_rank_parity import ingest_observations as ingest_beta
from tools.wf321_ingest_control_observations import ingest as ingest_control
from src.game.data.forever.source_queued_swing import ingest as ingest_maul
from src.game.data.forever.source_db_scope import ability_source_scope
from src.rulesets.forever.items.runtime_selection import available_items

ROOT=Path(__file__).resolve().parents[1]
OBS=ROOT/'evidence/wf331/druid20_source_web_index_observations.json'

def stage(tmp_path):
    path=tmp_path/'runeflags.sqlite'
    with sqlite3.connect(f'file:{DEFAULT_DB.resolve()}?mode=ro',uri=True) as source,sqlite3.connect(path) as dest:
        source.backup(dest)
    ingest_beta(path,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
    ingest_control(path,ROOT/'evidence/wf321/druid_l20_control_observations.json')
    ingest_maul(path,ROOT/'evidence/wf330/druid_l20_maul_observations.json')
    # The same beta + Bash + Maul source stage used by the WF330 L2 comparison.
    ingest_beta(path,ROOT/'evidence/WF322_DRUID_L20_WEB_TEXT_OBSERVATIONS_70338.json')
    ingest_control(path,ROOT/'evidence/wf321/druid_l20_control_observations.json')
    ingest_maul(path,ROOT/'evidence/wf330/druid_l20_maul_observations.json')
    assert ingest_observations(path,OBS)['observations_ingested']==20
    return path

def test_runes_off_preserves_every_source_index_row_but_excludes_setup(tmp_path):
    path=stage(tmp_path)
    with ability_source_scope(path):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=path)
        r=action_frontier(ir,class_key='druid',level=20,db_path=path)
    assert ir.provenance['rune_system_enabled'] is False
    assert r['use_runes'] is False
    assert r['rune_engraving_rows_disabled']==37
    assert r['rune_conditional_grants_blocked_without_talent']==9
    assert r['auxiliary_nonbuttons_needing_parent_coverage']==4
    assert r['potentially_legal_positive_ranks']==52
    # Current staged snapshot has three unresolved source role/amount rows; do not claim P1 from this older index.
    assert r['potential_ranks_unknown_role_and_amount']==3
    # Only source-executable rows are admitted to the historical L0 index.
    assert r['paid_search_admitted_source_rows']==14
    assert r['complete_legal_spell_universe_proven'] is False
    assert not r['PASS1']
    all_rows={x['spell_id']:x for x in r['records'] if 'spell_id' in x}
    assert all_rows[410021]['eligibility']=='RUNE_ENGRAVING_DISABLED_BY_DEFAULT'
    assert all_rows[417157]['eligibility']=='RUNE_CONDITIONAL_GRANT_DISABLED_TALENT_PATH_UNVERIFIED'
    assert all_rows[408245]['eligibility']=='AUXILIARY_OR_PASSIVE_NOT_STANDALONE_ACTION'

def test_rune_option_does_not_imply_live_rune_vendor_or_legal_action(tmp_path):
    path=stage(tmp_path)
    with ability_source_scope(path):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=path,use_runes=True)
        r=action_frontier(ir,class_key='druid',level=20,db_path=path,use_runes=True)
    assert ir.provenance['rune_system_enabled'] is True
    assert r['rune_engraving_rows_disabled']==0
    assert r['potentially_legal_positive_ranks']==60
    # Only source-executable rows are admitted to the historical L0 index.
    assert r['paid_search_admitted_source_rows']==14
    assert not r['PASS1']
    rune=next(x for x in r['records'] if x.get('spell_id')==410021)
    assert rune['legal_combat_spell_proven'] is False

def test_rune_derived_action_can_be_eligible_through_sourced_talent_at_level(tmp_path):
    path=stage(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO verified_talent_granted_action_facts '
                   '(class_key,spell_id,action_json,source_url,captured_at,capture_id) '
                   'VALUES (?,?,?,?,?,?)',('druid',417157,
                   json.dumps({'spell_id':417157,'required_level':20}),
                   'https://www.wowhead.com/forever/spell=417157','fixture','test'))
    with ability_source_scope(path):
        ir=build_game_ir_slice(class_key='druid',level=20,ability_db_path=path)
        r=action_frontier(ir,class_key='druid',level=20,db_path=path)
    row=next(x for x in r['records'] if x.get('spell_id')==417157)
    assert row['verified_talent_grant_exact_id_and_level'] is True
    assert row['eligibility']=='POTENTIALLY_LEGAL_RANK_ACQUISITION_UNRESOLVED'
    assert row['legal_combat_spell_proven'] is False

def test_rune_named_ordinary_trinkets_are_not_equipment_engravings():
    # Item names are not an acceptable proxy for rune acquisition; the two
    # genuine trinkets remain in legal gear search.
    items={item.name:item for item in available_items('druid',20)}
    assert items['Rune of Perfection'].slot=='trinket'
    assert items['Rune of Duty'].slot=='trinket'

def test_executable_rune_grant_is_removed_from_ir_modes_unless_talent_verified(tmp_path,monkeypatch):
    from dataclasses import replace
    from src.game.data.forever import registry
    path=stage(tmp_path)
    with ability_source_scope(path):
        base=registry.build_game_ir_slice(class_key='druid',level=20,ability_db_path=path,use_runes=True)
    fake=replace(base.actions[0], id='test_unproven_rune_button',
        provenance=({'source_spell_id':417157},),metadata={})
    modes=tuple(replace(m,enabled_action_ids=(
        None if m.enabled_action_ids is None else
        (*m.enabled_action_ids,'test_unproven_rune_button'))) for m in base.modes)
    from dataclasses import replace as dc_replace
    staged=dc_replace(base,actions=(*base.actions,fake),modes=modes)
    monkeypatch.setattr(registry,'_build_game_ir_slice_inner',lambda **_: staged)
    with ability_source_scope(path):
        ir_off=registry.build_game_ir_slice(class_key='druid',level=20,ability_db_path=path)
        ir_on=registry.build_game_ir_slice(class_key='druid',level=20,ability_db_path=path,use_runes=True)
    assert all(a.id!='test_unproven_rune_button' for a in ir_off.actions)
    assert any(a.id=='test_unproven_rune_button' for a in ir_on.actions)
    assert all(not m.enabled_action_ids or 'test_unproven_rune_button' not in m.enabled_action_ids for m in ir_off.modes)
    assert 'test_unproven_rune_button' in ir_off.provenance['rune_disabled_action_ids']
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO verified_talent_granted_action_facts '
                   '(class_key,spell_id,action_json,source_url,captured_at,capture_id) '
                   'VALUES (?,?,?,?,?,?)',('druid',417157,
                   json.dumps({'spell_id':417157,'required_level':20}),
                   'https://www.wowhead.com/forever/spell=417157','fixture','test'))
    with ability_source_scope(path):
        ir_talent=registry.build_game_ir_slice(class_key='druid',level=20,ability_db_path=path)
    assert any(a.id=='test_unproven_rune_button' for a in ir_talent.actions)
