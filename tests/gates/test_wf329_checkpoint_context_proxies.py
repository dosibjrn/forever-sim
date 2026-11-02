"""Source-text L0 proxies; deliberately not L2 legality or new damage spells."""
from src.game.data.forever.source_checkpoint_context_proxy import source_context_evidence
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_l0 import action_frontier


def test_reactive_damage_is_not_direct_cast_damage():
    p=source_context_evidence('Thorns sprout from the friendly target causing 9 Nature damage to attackers when hit. Lasts 10 min.',target_hp=100)
    assert p['numeric_context_features']['reactive_damage_per_incoming_hit']==9
    assert p['numeric_context_features']['reactive_damage_fraction_target_hp_per_hit']==.09
    assert {'buff_active','self_or_buff_target_is_hit'} <= set(p['context_requirements'])


def test_source_heal_over_time_and_defensive_debuff_have_quantitative_context():
    hot=source_context_evidence('Heals the target for 48 over 12 sec.',target_hp=150)
    assert hot['numeric_context_features']['periodic_heal_total']==48
    assert hot['numeric_context_features']['periodic_heal_duration_s']==12
    roar=source_context_evidence("The druid roars, decreasing nearby enemies' melee attack power by 56. Lasts 30 sec.",target_hp=150)
    assert roar['numeric_context_features']['enemy_melee_attack_power_reduction']==56
    assert 'enemy_melee_damage' in roar['context_requirements']


def test_survival_buff_and_noncombat_utility_keep_appropriate_context():
    p=source_context_evidence('When activated, this grants you 30% of your maximum health for 20 sec.',target_hp=200)
    assert p['numeric_context_features']['temporary_max_health_percent']==30
    r=source_context_evidence('Brings a dead player back to life with 70 health and 135 mana. Cannot be cast when in combat.',target_hp=200)
    assert {'dead_friendly_target','out_of_combat'}<=set(r['context_requirements'])
    q=source_context_evidence('',target_hp=200)
    assert not q['effect_candidates'] and not q['source_text_available']


def test_druid_l20_real_source_frontier_thorns_and_covered_context():
    ir=build_game_ir_slice(class_key='druid',level=20)
    r=action_frontier(ir,class_key='druid',level=20)
    by_id={x['spell_id']:x for x in r['records'] if 'spell_id' in x}
    assert by_id[782]['source_text_context_evidence']['numeric_context_features']['reactive_damage_per_incoming_hit']==9
    assert by_id[467]['index_features']['direct_damage']==0
    assert by_id[99]['source_text_context_evidence']['numeric_context_features']['enemy_melee_attack_power_reduction']==56
    assert by_id[1058]['source_text_context_evidence']['numeric_context_features']['periodic_heal_total']==48
    assert by_id[774]['sibling_rank_context_only']
    assert r['potential_ranks_assessed_by_numeric_ir_or_text_role']>r['potential_ranks_with_numeric_or_ir_proxy']
    assert r['PASS1'] is False


def test_no_class_or_spell_id_triggers_special_evaluation():
    from src.game.data.forever.source_checkpoint_context_proxy import source_context_evidence
    text='A spell gives 48 healing over 12 sec; it is useful when damaged.'
    p=source_context_evidence(text,target_hp=100)
    assert p['effect_candidates']==[]  # unsupported wording stays explicitly unknown
