"""Cross-class admission/encounter contract, not simulated success theater."""
from dataclasses import replace
import pytest

from src.game.checkpoint_pipeline import checkpoint_enemy, checkpoint_preflight, checkpoint_recovery_probe
from src.game.data.forever import build_game_ir_slice
from src.game.model import PolicyDefinition,PolicyRuleDefinition

@pytest.mark.parametrize('cls,level,hp', [('druid',20,484),('druid',30,955),('mage',30,955),('warrior',30,955)])
def test_preflight_resolves_same_enemy_without_per_class_switch(cls,level,hp):
    r=checkpoint_preflight(class_key=cls, level=level)
    assert r['enemy']['hp']==hp
    assert r['enemy']['enemy_level']==level
    assert r['enemy']['combat_capture_id']
    assert r['enemy']['armor']>0
    assert r['incoming_attack_count']>0
    if cls != 'warrior':
        assert r['equipment_l0_inventory']['legal_items']>0
        # Legacy class-list rows are NOT a complete class-filtered capture.
        assert not r['equipment_l0_inventory']['source_membership_verified']
        assert not r['equipment_l0_inventory']['l0_universe_pass']
    else:
        assert r['equipment_l0_inventory']['legal_items'] is None
    assert ('P3_ILVL_TOP5_CONTEXTUAL_SMOKE_NOT_RUN' if cls!='warrior'
            else 'P3_NO_AVAILABLE_LEGAL_ITEM_SAMPLE') in {x['code'] for x in r['blockers']}
    assert not r['equipment_l0_inventory']['is_build_specific_top5']
    assert not r['eligible_for_checkpoint_acceptance']
    assert {'FOREVER_NAMED_ENEMY_UNVERIFIED','JOINT_BUILD_OPTIMUM_NOT_CERTIFIED'} <= {x['code'] for x in r['blockers']}


def test_mismatched_level_or_missing_profile_fail_closed():
    ir=build_game_ir_slice(class_key='mage',level=30)
    with pytest.raises(ValueError,match='LEVEL_IR_MISMATCH'):
        checkpoint_enemy(ir=ir,level=20)
    with pytest.raises(ValueError,match='TARGET_COMBAT_NOT_SOURCED'):
        checkpoint_enemy(ir=replace(ir,provenance={}),level=30)
    with pytest.raises(ValueError,match='CLASS_IR_MISMATCH'):
        checkpoint_preflight(class_key='druid',level=30,ir=ir)


def test_checkpoint_probe_rejects_handpicked_hp_and_uses_paid_incoming(monkeypatch):
    # Monkeypatch the shared 100mob entrypoint ONLY to validate the wired
    # scenario envelope, avoiding 100mob runtime in a unit contract test.
    observed={}
    def evaluator(**kw):
        observed.update(kw)
        return {'best':{'seconds_per_mob':21.},'evaluated':1}
    monkeypatch.setattr('src.game.checkpoint_pipeline.search_recovery_thresholds', evaluator)
    ir=build_game_ir_slice(class_key='mage',level=30)
    spell=next(a for a in ir.actions if a.family_key=='frostbolt')
    policy=PolicyDefinition(id='probe',label='source spell',rules=(PolicyRuleDefinition('spell',spell.id),))
    with pytest.raises(TypeError):
        checkpoint_recovery_probe(class_key='mage',level=30,policy=policy,ir=ir,target_health=150)
    result=checkpoint_recovery_probe(class_key='mage',level=30,policy=policy,ir=ir)
    assert observed['target_health']==955.
    assert observed['count']==100 and observed['schedule_incoming_attacks'] is True
    assert observed['apply_target_defense'] is True
    assert result['diagnostic_only'] and not result['eligible_for_checkpoint_acceptance']
    assert result['enemy']['hp_authority'].startswith('CMANGOS_')

@pytest.mark.parametrize('cls,level', [('mage',30),('druid',20),('druid',30)])
def test_generic_seed_actions_discovered_for_all_caster_checkpoints(cls,level):
    from src.game.checkpoint_pipeline import discover_source_damage_seeds
    ir=build_game_ir_slice(class_key=cls,level=level)
    seeds=discover_source_damage_seeds(ir)
    assert seeds and len(seeds)>=2
    ids={action.id for action in ir.actions}
    assert all(r.action_id in ids for policy in seeds for r in policy.rules)
    assert all(not p.provenance['complete_apl_search'] for p in seeds)


def test_no_initial_legal_direct_damage_seed_is_not_fake_success():
    from src.game.checkpoint_pipeline import checkpoint_auto_screen
    result=checkpoint_auto_screen(class_key='warrior',level=30)
    assert result['status']=='BLOCKED_NO_LEGAL_DIRECT_DAMAGE_SEED'
    assert not result['eligible_for_checkpoint_acceptance']
    assert 'P3_NO_AVAILABLE_LEGAL_ITEM_SAMPLE' in {x['code'] for x in result['preflight']['blockers']}

@pytest.mark.parametrize('cls', ['priest','shaman','hunter','warlock','rogue'])
def test_missing_provider_has_typed_blocker_instead_of_crashing(cls):
    r=checkpoint_preflight(class_key=cls, level=30)
    assert r['enemy'] is None
    assert r['further_gates']=='NOT_EVALUATED_NO_GAME_IR'
    assert r['blockers'][0]['code']=='NO_EXECUTABLE_GAME_IR_AT_CHECKPOINT'
    assert not r['eligible_for_checkpoint_acceptance']

@pytest.mark.parametrize('cls,level,hp', [('mage',30,955.0),('druid',20,484.0)])
def test_paid_100mob_source_profile_end_to_end(cls,level,hp):
    from src.game.checkpoint_pipeline import checkpoint_auto_screen
    r=checkpoint_auto_screen(class_key=cls,level=level,max_policies=1)
    assert r['status']=='SCREENED_SOURCE_PROXY'
    assert r['enemy']['hp']==hp
    assert r['best']['best']['mobs_killed']==100
    assert r['best']['best']['seconds_per_mob']>0
    assert not r['eligible_for_checkpoint_acceptance']
