"""WF264: reproduce exact Decision L20 gear/talents and validate generic sustained Cat.

These are real sourced IR, source inventory and game-executor tests, not a
synthetic scorer; no assertion of ruleset equivalence to legacy Decision.
"""
import json
from pathlib import Path
import pytest
from src.rulesets.forever.classes.druid.talents import Talents
from src.rulesets.forever.classes.druid.mechanics import score_external_build
from src.game.data.forever.registry import build_game_ir_slice
from src.rulesets.forever.items.runtime_selection import available_items, item_payload, item_vector, effective_level
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection
from src.game.model import PolicyDefinition, PolicyRuleDefinition, PolicyCondition
from src.game.multi_pull import evaluate_repeated_pulls
from src.shared.leveling.objective import representative_hp

ROOT = Path(__file__).resolve().parents[1]

def _case():
    fixture = json.loads((ROOT/'docs/validation/I15/LISTENER_LOCAL_I15_STATE_v0.11.48.103.json').read_text())['cards'][0]['fast_best']
    pool = {item.item_id:item for item in available_items('druid',20,required_level_policy='observed')}
    old_ids = {k:int(v['item_id']) for k,v in fixture['gear_stats']['slots'].items()}
    assert len(old_ids)==15 and all(v in pool for v in old_ids.values())
    selected = {slot:pool[item_id] for slot,item_id in old_ids.items()}
    stats={}
    for item in selected.values():
        for key,val in item_vector(item).items():
            stats[key]=stats.get(key,0.)+float(val)
    base=build_game_ir_slice(class_key='druid',level=20)
    geared,_=apply_gear_selection(base, aggregate_stats=stats, selected_items=tuple(
        item_payload(item,display_slot=slot,effective_level=effective_level(item)) for slot,item in selected.items()),
        source='canonical_sqlite_forever_catalogue')
    geared,_=apply_talent_selection(geared,fixture['talent_ranks'],level=20)
    rules=[PolicyRuleDefinition(id='finisher', action_id='rip:20',conditions=(
        PolicyCondition(kind='resource_threshold',resource_id='combo_points',operator='gte',value=5.),)),
        PolicyRuleDefinition(id='builder',action_id='claw:20')]
    policy=PolicyDefinition(id='held_out_decision_cat',label='actual Cat/Claw/Rip',rules=tuple(rules),
                            provenance={'search_performed':True,'held_out':True})
    return fixture,geared,policy,old_ids

def _run(geared,policy,**overrides):
    opts=dict(ir_slice=geared,policy=policy,level=20,target_health=representative_hp(20),
              pre_combat_action_ids=('cat_form:768',),post_combat_action_ids=('cancel_mode:cat',),
              apply_target_defense=True,schedule_incoming_attacks=True)
    opts.update(overrides)
    return evaluate_repeated_pulls(**opts)

def test_legacy_true_oracle_is_not_fake_old_feral_fixture():
    fixture,gear,policy,ids=_case()
    assert ids['weapon']==270018 and ids['head']==252447 and ids['feet']==252439
    assert fixture['talent_ranks']=={'ferocity':5,'heart_of_the_wild':3,'thick_hide':2,'savage_fury':1}
    old=score_external_build(20,Talents(**fixture['talent_ranks']),'feral',fixture['gear_stats'])
    # Shared canonical Classic-proxy target defense now applies on BOTH engines.
    # The recorded 10.4548465 is an immutable *historical* no-mitigation
    # Decision result, not the current same-ruleset oracle score.
    assert old['total_s']/100==pytest.approx(15.149188674755983,abs=1e-8)
    assert old['outgoing_target_combat']['target_armor']==836.
    assert old['outgoing_target_combat']['application_hit']==.95
    assert old['outgoing_target_combat']['source_status']=='classic_proxy_not_forever_server_verified' 
    assert old['cat_selected_casts']==['Claw','Claw','Claw'] # Shared target defense adds a builder; no Rip.

def test_15_real_pulls_keep_cat_and_regen_energy_in_travel():
    _,gear,policy,_=_case()
    result=_run(gear,policy,count=15,recovery_mode='threshold',retain_mode_between_pulls=True,
                recovery_health_fraction=0.5,recovery_mana_fraction=0.1,travel_time_s=2.2)
    assert len(result.pulls)==15
    assert result.seconds_per_mob==pytest.approx(16.224919334523893,abs=1e-8)
    assert result.pulls[0]['mode_at_next_pull']=='cat'
    assert result.pulls[1]['mode_at_next_pull']=='cat'
    assert result.pulls[0]['energy_at_next_pull'] > 0
    assert all(p['travel_s']==2.2 for p in result.pulls)
    assert any(p['recovery_performed'] for p in result.pulls)
    assert any(not p['recovery_performed'] for p in result.pulls)
    assert all(p['kill_s'] > 0 and p['recovery_s'] >= 0 for p in result.pulls)
    assert result.pulls[0]['recovery_s']==0
    assert result.actor.current_mode_id=='caster' # real exit on last full recovery

def test_missed_recovery_and_mode_reentry_are_not_free():
    _,gear,policy,_=_case()
    a=_run(gear,policy,count=15,recovery_mode='always',travel_time_s=2.2)
    b=_run(gear,policy,count=15,recovery_mode='threshold',retain_mode_between_pulls=True,travel_time_s=2.2)
    assert a.seconds_per_mob==pytest.approx(19.906642594745396,abs=1e-8)
    assert b.seconds_per_mob < a.seconds_per_mob
    assert all(p['recovery_performed'] for p in a.pulls)
    assert all(p['mode_at_next_pull']=='caster' for p in a.pulls)

def test_one_pull_backwards_compatible_and_end_recovery_charged():
    _,gear,policy,_=_case()
    result=_run(gear,policy,count=1)
    assert result.seconds_per_mob==pytest.approx(17.706642594745396,abs=1e-8)
    assert result.pulls[0]['kill_s']==12
    assert result.pulls[0]['recovery_s']>0

def test_invalid_scenario_rejected_before_expensive_simulation():
    _,gear,policy,_=_case()
    for opts in ({'travel_time_s':-1},{'recovery_mode':'none'},
                 {'recovery_health_fraction':1.3},{'recovery_mana_fraction':-0.1},
                 {'retain_mode_between_pulls':True,'post_combat_action_ids':()}):
        with pytest.raises(ValueError):
            _run(gear,policy,count=2,**opts)
