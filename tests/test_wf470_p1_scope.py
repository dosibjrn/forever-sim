"""P1's changed meaning is a contract, not only a druid example."""
from pathlib import Path
import json
import pytest
import sys
from types import SimpleNamespace as N
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from wf_gate_p1_live import _highest_usable_ranks, _effect_scope, _load_source_scope_facts, run_live


def row(sid,name,level,rank,text=''):
    return {'spell_id':sid,'name':name,'level_hint':level,'rank_hint':rank,
            'raw_listview_json':json.dumps({'envChange':{'after':{'text':text}}})}


def test_highest_usable_rank_only_and_no_unlearned_bypass():
    rows=[row(10,'Test',1,1),row(20,'Test',6,2),row(30,'Other',6,1)]
    assert {r['spell_id'] for r in _highest_usable_ranks(rows)}=={20,30}
    ties=[row(10,'Test',6,2),row(20,'Test',6,2)]
    assert {r['spell_id'] for r in _highest_usable_ranks(ties)}=={10,20}


def test_generic_source_tooltips_classify_roles_without_spell_whitelist():
    assert _effect_scope(row(1,'Fireball',5,1,'Deals 25 fire damage'),{}, {})[0]=='IN_SCOPE'
    assert _effect_scope(row(2,'Shield',5,1,'Increases armor by 15'),{}, {})[0]=='IN_SCOPE'
    assert _effect_scope(row(3,'Sleep spell',5,1,'Forces target to sleep'),{}, {})[0]=='IN_SCOPE'
    assert _effect_scope(row(4,'Healing',5,1,'Heals target for 25'),{}, {})[0]=='EXCLUDED'
    assert _effect_scope(row(5,'Unknown',5,1,''),{}, {})[0]=='UNRESOLVED'


def test_unknown_missing_ability_never_dismissed_by_scope():
    from wf_gate_p1_live import audit_inventory
    missing=row(33,'Unmapped',10,1)
    ir=N(actor=N(id='me'),actions=(),modes=(),resources=())
    report=audit_inventory([missing],ir,parser=lambda a:set(),
        source_classifier=lambda r,x:{'role':'ABILITY'},
        policy_builder=lambda *a:None,scratch_builder=lambda *a,**k:[],
        executor=lambda *a:None,effect_checker=lambda e:'direct_damage')
    assert report['status']=='FAIL'
    assert {'MISSING_GAME_IR_ACTION','P1_EFFECT_SCOPE_UNRESOLVED'} <= {p['code'] for p in report['problems']}


def test_real_druid_l20_p1_staged_sourced_action_coverage(monkeypatch):
    monkeypatch.setenv('WOW_FOREVER_BUILD_AS_OF','2026-10-17')
    result=run_live(ROOT,'druid',20)
    assert result['status']=='PASS'
    assert result['effect_scope_policy']=='damage_buff_debuff_cc_highest_rank_only'
    assert result['problem_count']==0
    assert not result['problems']
    assert result['does_not_affect_sim_count']==2
    assert {r['source_spell_id'] for r in result['does_not_affect_sim']}=={2637,18960}
    assert result['matched_source_abilities']==18
    assert result['production_runtime_exercises']==18  # includes *damage* on queued Maul
    assert any(r['source_spell_id']==6807 and r['role']=='LOWER_LEARNED_RANK' for r in result['excluded_nonaction_or_inactive_rows'])
    assert any(r['source_spell_id']==6795 and r['role']=='OUT_OF_P1_EFFECT_SCOPE' for r in result['excluded_nonaction_or_inactive_rows'])


def test_role_evidence_is_versioned_and_source_id_bound():
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    facts=_load_source_scope_facts(DEFAULT_DB,'druid')
    assert len(facts)==6
    assert set(facts)=={1735,5211,2637,6808,16810,5215}
    for sid,fact in facts.items():
        assert fact['source_url'].startswith('https://') and fact['name']


def test_real_l30_spellbook_observations_resolve_source_roles_without_fake_ir():
    from wf_gate_p1_live import (_source_rows, _source_legality,
        _load_spellbook_observed_scope_facts)
    from src.game.data.forever.registry import build_game_ir_slice
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    rows=_source_rows(DEFAULT_DB,'druid',30)
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DEFAULT_DB)
    _,meta=_source_legality(ROOT,ir,'druid',30,DEFAULT_DB)
    facts=_load_spellbook_observed_scope_facts(ROOT,meta['spellbook_file'],rows)
    assert facts[740]['roles']==['healing']      # Tranquility: not P1 combat scope
    assert facts[780]['roles']==['damage']       # Swipe
    assert facts[783]['roles']==['buff']         # Travel Form
    assert facts[1850]['roles']==['buff']        # Dash
    assert facts[6798]['roles']==['cc']          # Bash
    assert facts[6809]['roles']==['damage']      # Maul
    assert facts[24974]['roles']==['damage','debuff']  # Talent-granted rank
    # Role evidence does NOT fabricate the absent GameIR executor.
    report=run_live(ROOT,'druid',30)
    assert not any('P1_EFFECT_SCOPE_UNRESOLVED:' in reason and
                   any(reason.split(':')[1]==str(sid) for sid in
                       (740,780,783,1850,6798,6809))
                   for reason in report['reasons'])
    assert any(reason.startswith('MISSING_GAME_IR_ACTION:780:') for reason in report['reasons'])


def test_spellbook_observed_role_rejects_wrong_exact_source_identity(tmp_path):
    from wf_gate_p1_live import (_source_rows, _load_spellbook_observed_scope_facts,
                                 P1SetupError)
    from src.game.data.forever.sqlite_talents import DEFAULT_DB
    rows=_source_rows(DEFAULT_DB,'druid',30)
    document=json.loads((ROOT/'evidence/wf348/druid_spellbook_70338_level1_30.json').read_text())
    document['observed_rank_numeric_by_id']['780']['name']='Not Swipe'
    (tmp_path/'altered.json').write_text(json.dumps(document))
    with pytest.raises(P1SetupError,match='P1_SPELLBOOK_OBSERVED_SCOPE_IDENTITY_DRIFT:780'):
        _load_spellbook_observed_scope_facts(tmp_path,'altered.json',rows)
