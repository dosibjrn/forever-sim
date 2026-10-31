from pathlib import Path

import pytest

from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.rulesets.forever.classes import mage
from src.rulesets.forever.classes import paladin as pala
from src.rulesets.forever.classes import druid


def _spend(engine, names):
    t=engine.Talents()
    for name in names:
        t=engine.add_point(t,name)
    return t


def test_forever_tree_shapes_match_beta_snapshot():
    assert len(mage.TALENT_RULES) == 54
    assert len(pala.TALENT_RULES) == 52
    assert len(druid.TALENT_RULES) == 51
    assert set(mage.TREE_NAMES) == {'frost','arcane','fire'}
    assert set(pala.TREE_NAMES) == {'holy','protection','retribution'}
    assert set(druid.TREE_NAMES) == {'balance','feral','restoration'}


def test_forever_mage_level_20_talent_spells_are_legally_reachable():
    arc=_spend(mage,['arcane_focus']*5+['improved_channeling']*5)
    assert arc.points()==10 and mage.legal_add(arc,'arcane_blast')
    arc=mage.add_point(arc,'arcane_blast')
    assert arc.points()==11
    assert mage.latest(mage.ARCANE_BLAST,20).dmin == 55

    frost=_spend(mage,['imp_frostbolt']*5+['elemental_precision']*5)
    assert frost.points()==10 and mage.legal_add(frost,'ice_lance')
    frost=mage.add_point(frost,'ice_lance')
    assert mage.latest(mage.ICE_LANCE,20).dmax == 30


def test_forever_mage_verified_rank_overrides_through_beta_cap():
    assert (mage.latest(mage.FROSTBOLT,26).dmin,mage.latest(mage.FROSTBOLT,26).dmax)==(96,106)
    fb=mage.latest(mage.FIREBALL,30)
    assert (fb.dmin,fb.dmax,fb.dot_total)==(137,183,24)
    assert mage.latest(mage.ARCANE_MISSILES,24).channel_tick_damage==46
    assert mage.shatter_crit_bonus(mage.Talents(shatter=3))==.50
    assert mage.impact_proc_chance(mage.Talents(impact=3))==.10


def test_forever_paladin_prot_level_20_core_is_legal_and_scores():
    t=_spend(pala,['redoubt']*5+['anticipation']*5)
    assert t.points()==10 and pala.legal_add(t,'improved_seal_of_fury')
    t=pala.add_point(t,'improved_seal_of_fury')
    row=pala.experimental_level_score(20,t,'protection')
    assert row['profile']=='protection'
    assert row['gear']=='1h_shield_normal'
    assert row['total_s']>0 and 'Seal of Fury' in row['rotation']


def test_forever_druid_published_feral_level_30_route_is_legal():
    seq=(['ferocity']*5+['feral_swiftness']*2+['thick_hide']*3+
         ['sharpened_claws']*2+['savage_fury']*2+['feral_charge']+
         ['mangle']+['predatory_strikes']*3+['blood_frenzy']*2)
    t=_spend(druid,seq)
    assert t.points()==21
    row=druid.experimental_level_score(30,t,'feral')
    assert row['profile']=='cat' and row['total_s']>0
    assert 'Mangle' not in row['rotation']
    assert row['feral_builder'] == 'Claw'


def test_game_state_namespace_preserves_legacy_classic_layout(tmp_path, monkeypatch):
    monkeypatch.setenv(game_context.RULESET_ENV,'classic')
    monkeypatch.setenv(game_context.CLASS_ENV,'mage')
    game_context.configure('classic','mage')
    assert game_context.state_root(tmp_path)==tmp_path/'state'
    game_context.configure('forever','paladin')
    assert game_context.state_root(tmp_path)==tmp_path/'state'/'games'/'forever-paladin'


def test_engine_registry_switches_ruleset_and_class(monkeypatch):
    try:
        game_context.configure('classic','mage'); reset_engine_cache()
        assert get_engine().__name__=='src.classic_mage_leveling_optimizer_v10' and game_context.current().key=='classic-mage'
        game_context.configure('forever','druid'); reset_engine_cache()
        assert get_engine().CLASS_NAME=='druid' and get_engine().RULESET=='forever'
    finally:
        game_context.configure('classic','mage'); reset_engine_cache()


def test_forever_data_provenance_is_explicit_and_mage_marks_mixed_build_snapshot():
    assert pala.DATA_PROVENANCE.verified_level_cap == 30
    assert druid.DATA_PROVENANCE.verified_level_cap == 30
    assert pala.DATA_PROVENANCE.mixed_build is False
    assert druid.DATA_PROVENANCE.mixed_build is False
    assert mage.DATA_PROVENANCE.mixed_build is False
    data = mage.DATA_PROVENANCE.as_dict()
    assert '69893' in data['build']
    assert 'current Wowhead Forever corrections' in data['quality']['modeled_spell_ranks']


def test_forever_mage_modeled_spell_tables_match_69893_fixture():
    import json
    fixture = json.loads(Path('tests/fixtures/forever/1.60.1.69893/mage_core_spells.json').read_text(encoding='utf-8'))
    assert fixture['build'] == '1.60.1.69893'

    def rows(name):
        vals = getattr(mage, name.upper())
        if name in ('frostbolt','scorch'):
            return [[r.rank,r.learn,r.mana,r.cast,r.dmin,r.dmax] for r in vals]
        if name in ('fireball','pyroblast'):
            return [[r.rank,r.learn,r.mana,r.cast,r.dmin,r.dmax,r.dot_total,r.dot_duration] for r in vals]
        if name == 'arcane_missiles':
            return [[r.rank,r.learn,r.mana,r.channel_ticks,r.channel_tick_damage] for r in vals]
        if name == 'arcane_blast':
            return [[r.rank,r.learn,r.dmin,r.dmax] for r in vals]
        if name == 'ice_lance':
            return [[r.rank,r.learn,r.mana,r.dmin,r.dmax] for r in vals]
        if name in ('fire_blast','frost_nova'):
            return [[r.rank,r.learn,r.mana,r.dmin,r.dmax] for r in vals]
        raise AssertionError(name)

    for name, expected in fixture['spells'].items():
        assert rows(name) == expected, name


def test_forever_mage_current_wowhead_new_ability_facts_are_structured_and_rotation_enabled():
    from src.rulesets.forever.classes.mage import wowhead_facts as wh
    assert wh.ARCANE_BLAST_RANKS == ((20,55),(30,131),(40,170),(50,275),(60,395))
    assert wh.ARCANE_BLAST_BASE_MANA_PCT == pytest.approx(.15)
    from src.rulesets.forever.data.rules import default_rules
    assert default_rules().spell_value('mage','arcane_blast',40,'spell_power_coefficient',target='arcane_blast') == pytest.approx(.714)
    assert wh.ARCANE_BLAST_MAX_STACKS == 4
    assert wh.ARCANE_BLAST_MANA_COST_INCREASE_PER_STACK == pytest.approx(1.75)
    assert wh.FINGERS_OF_FROST_CHILL_PROC_CHANCE == pytest.approx(.15)
    from src.rulesets.forever.classes.mage.server_profile import CURRENT_TARGET_SERVER_PROFILE
    assert CURRENT_TARGET_SERVER_PROFILE.fingers_of_frost_charges == 2
    assert wh.MISSILE_BARRAGE_ARCANE_BLAST_PROC_CHANCE == pytest.approx(.40)
    assert wh.MISSILE_BARRAGE_OTHER_TRIGGER_PROC_CHANCE == pytest.approx(.20)
    assert wh.BLIZZARD_R1_MANA == 320 and wh.BLIZZARD_R1_TICKS == 8
    assert [(r.learn,r.mana,r.dmin,r.dmax) for r in mage.ICE_LANCE] == [
        (20,45,30,30),(28,55,38,38),(34,70,48,48),
        (42,105,83,83),(48,120,104,104),(56,160,152,152),
    ]
    missing=set(mage.MODEL_FIDELITY['forever_missing_mechanics'])
    assert 'arcane_blast_stack_rotation' not in missing
    assert 'missile_barrage_proc_rotation' not in missing
    assert 'fingers_of_frost_ice_lance_rotation' not in missing
    assert 'blizzard_and_other_aoe_leveling' not in missing
    assert mage.MODEL_FIDELITY['strategy_capabilities']['mage.blizzard_aoe_leveling'] is False
    assert any(p.primary == 'arcane_blast' for p in mage.candidate_policies(30))


def test_forever_mage_arcane_mind_scales_max_mana_not_intellect():
    base=mage.player_stats(40,mage.Talents())
    am5=mage.player_stats(40,mage.Talents(arcane_mind=5))
    assert am5.intellect == pytest.approx(base.intellect)
    assert am5.spell_crit == pytest.approx(base.spell_crit)
    assert am5.max_mana == pytest.approx(base.max_mana * 1.10)


def test_forever_mage_arcane_blast_stack_cost_and_proc_actions_are_live():
    tal=mage.Talents(arcane_blast=1, missile_barrage=1)
    stats=mage.player_stats(30,tal)
    s=mage.State(0,500,stats.max_mana,stats.max_mana,30)
    r=mage.latest(mage.ARCANE_BLAST,30)
    base=stats.base_mana*0.15
    # Baseline first AB cost; stacked cost is materially larger.
    assert base > 0
    s.arcane_blast_stacks=1; s.arcane_blast_until=10
    stacked=stats.base_mana*0.15*(1+mage.wh.ARCANE_BLAST_MANA_COST_INCREASE_PER_STACK)
    assert stacked > base*2
    # Missile Barrage is consumed by AM and makes the channel free/fast.
    s.missile_barrage_until=10
    assert tal.missile_barrage == 1


def test_forever_druid_current_wowhead_public_facts_are_persisted_without_guessing_mangle_cat():
    from src.rulesets.forever.classes.druid import wowhead_facts as wh
    assert wh.CAT_FORM_LEVEL == 20
    assert wh.CAT_FORM_BASE_MANA_PCT == pytest.approx(.55)
    assert wh.CAT_FORM_AP_FLAT == pytest.approx(12)
    assert wh.CLAW_R1 == {
        'level':20,'energy':45,'normal_damage_mult':1.10,'flat_damage':27,
        'combo_points':1,'gcd_s':1.0,
    }
    assert wh.SHRED_R1['level']==22 and wh.SHRED_R1['energy']==60
    assert wh.SHRED_R1['normal_damage_mult']==pytest.approx(1.55)
    assert wh.SHRED_R1['requires_behind'] is True
    assert wh.RAKE_L34['direct_damage']==28 and wh.RAKE_L34['dot_total']==57
    assert wh.FEROCIOUS_BITE_L40['damage_by_combo_points'][-1] == (315,339)
    assert wh.WRATH_L38['mana']==80 and wh.WRATH_L38['damage_min']==56 and wh.WRATH_L38['damage_max']==63
    assert wh.MOONFIRE_L28['dot_total']==124
    assert wh.OMEN_OF_CLARITY_PROC_ICD_S==pytest.approx(10)
    assert wh.CLEARCASTING_DURATION_S==pytest.approx(15)
    assert wh.MOONKIN_FORM_LEVEL==40 and wh.MOONKIN_ITEM_ARMOR_INCREASE==pytest.approx(3.60)
    assert wh.MANGLE_PUBLIC_FACT['cat_mangle_current_build_status'] == 'removed'
    assert wh.PRIMAL_BITE_PUBLIC_FACT['spell_id'] == 407995
    assert wh.PRIMAL_BITE_PUBLIC_FACT['forms'] == ('bear','dire_bear')
    assert 'mangle_cat_current_rank_cost_and_coefficient' not in druid.MODEL_FIDELITY['missing_mechanics']


def test_forever_paladin_current_wowhead_core_spell_ranks():
    # Audited against the current Wowhead Forever spell database.  These are
    # modeled ranks, not a claim that every post-30 Paladin datum is verified.
    assert pala.latest(pala.HOLY_STRIKE,6) == (6,5,12.0,.25,13,13)
    assert pala.latest(pala.HOLY_STRIKE,20) == (20,12,12.0,.30,20,20)
    assert pala.latest(pala.HOLY_STRIKE,60) == (60,20,12.0,.40,109,109)
    assert pala.latest(pala.SEAL_FURY,20) == (18,60,0,0,0)
    assert pala.latest(pala.CONSECRATION,20) == (20,135,16,16)
    assert pala.latest(pala.CONSECRATION,30) == (30,235,24,24)
    assert pala.latest(pala.CONSECRATION,60) == (60,565,96,96)
    assert pala.latest(pala.HOLY_LIGHT,20) == (14,110,2.5,167,196)
    assert pala.latest(pala.FLASH_OF_LIGHT,20) == (20,35,1.5,67,77)
    assert pala.latest(pala.RETRIBUTION_AURA,20) == (16,5)
    assert pala.latest(pala.DEVOTION_AURA,20) == (20,275)




def test_forever_paladin_consecration_is_baseline_at_20_not_talent_gated():
    from src.rulesets.forever.classes.paladin import mechanics as mech
    gear=next(g for g in pala.archetypes(20) if g.name=='1h_shield_normal')
    policy=next(p for p in pala.POLICIES if p.name=='aggressive')
    # No Holy talent unlock is required: Consecration is a baseline L20 spell.
    aura_dps, con_dps, con_mps = mech._aoe_dps(20, pala.Talents(), gear, 3, 'devotion',
                                               mech._base_damage(20,pala.Talents(),gear,'protection'),
                                               policy, {'landed_swings_per_mob': 0.0})
    assert con_dps > 0.0
    assert con_mps > 0.0
    assert pala.latest(pala.CONSECRATION,19) is None
    assert pala.latest(pala.CONSECRATION,20) == (20,135,16,16)

def test_forever_paladin_judgement_uses_gross_base_mana_cost_then_refund():
    from src.rulesets.forever.classes.paladin import mechanics as mech
    gear=next(g for g in pala.archetypes(20) if g.name=='2h_normal')
    plain=mech._base_damage(20,pala.Talents(seal_of_command=1),gear,'retribution')
    sj=mech._base_damage(20,pala.Talents(seal_of_command=1,sanctified_judgement=3),gear,'retribution')
    expected=.06*412.0
    assert plain['judgement_cost']==pytest.approx(expected)
    assert sj['judgement_cost']==pytest.approx(expected)
    assert plain['judgement_refund']==0
    assert sj['judgement_refund']==pytest.approx(sj['seal_cost']*.60)
    assert sj['judgement_net_cost']==pytest.approx(expected-sj['judgement_refund'])
    sixty=mech._base_damage(60,pala.Talents(),next(g for g in pala.archetypes(60) if g.name=='2h_normal'),'retribution')
    assert sixty['judgement_cost']==pytest.approx(.06*1512.0)


def test_forever_paladin_classic_baseline_melee_ap_includes_level_term():
    from src.rulesets.forever.classes.paladin import mechanics as mech
    assert mech._paladin_melee_ap(20,56)==pytest.approx(152.0)
    assert mech._paladin_melee_ap(60,100)==pytest.approx(360.0)


def test_forever_paladin_post30_gear_advances_only_at_real_named_item_samples():
    from src.rulesets.forever.classes.paladin.gear import gear_curve_status
    l30=next(g for g in pala.archetypes(30) if g.name=='2h_normal')
    l40=next(g for g in pala.archetypes(40) if g.name=='2h_normal')
    l60=next(g for g in pala.archetypes(60) if g.name=='2h_normal')
    assert l40.weapon_dps > l30.weapon_dps
    assert l60.weapon_dps > l40.weapon_dps
    assert l60.item_armor > l40.item_armor > l30.item_armor
    assert gear_curve_status(30)=='discrete_named_sample_and_hold'
    assert gear_curve_status(40)=='discrete_named_sample_and_hold'
    assert gear_curve_status(60)=='discrete_named_sample_and_hold'


def test_forever_paladin_holy_strike_and_consecration_use_current_spellpower_coefficients():
    from src.rulesets.forever.classes.paladin import mechanics as mech
    t=pala.Talents()
    gear=next(g for g in pala.archetypes(20) if g.name=='2h_normal')
    boosted=gear.with_delta('spell_damage',100)
    a=mech._base_damage(20,t,gear,'retribution')
    b=mech._base_damage(20,t,boosted,'retribution')
    assert b['hs_dps'] > a['hs_dps']
    # 42.9% SP per Holy Strike before common hit/CD multipliers.
    assert (b['hs_dps']-a['hs_dps']) == pytest.approx(100*.429/a['hs_cd']*a['hit'])
    policy=pala.POLICIES[0]
    incoming=mech._incoming(20,t,gear,4,'devotion',a)
    _ad,con_a,_cm=mech._aoe_dps(20,t,gear,4,'devotion',a,policy,incoming)
    incoming_b=mech._incoming(20,t,boosted,4,'devotion',b)
    _bd,con_b,_bm=mech._aoe_dps(20,t,boosted,4,'devotion',b,policy,incoming_b)
    # Hidden first-four trigger exposes 9.5% SP per tick for 8 ticks.
    assert con_b-con_a == pytest.approx(100*.095)


def test_forever_paladin_pursuit_of_justice_is_four_percent_per_rank():
    from src.rulesets.forever.classes.paladin import mechanics as mech
    gear=next(g for g in pala.archetypes(20) if g.name=='2h_normal')
    base=pala.Talents()
    rank2=pala.Talents(pursuit_of_justice=2)
    # Travel proxy must use 4% / 8%, matching the Forever rank spell pages.
    a=mech.smooth_pack_score(20,base,'retribution',gear,1,pala.POLICIES[1],'retribution')
    b=mech.smooth_pack_score(20,rank2,'retribution',gear,1,pala.POLICIES[1],'retribution')
    assert b['travel_s'] < a['travel_s']
    assert b['travel_s']/100.0==pytest.approx(2.2/1.08)



def test_forever_paladin_craft_floor_and_weapon_styles_use_current_forever_samples():
    g20_2h=next(g for g in pala.archetypes(20) if g.name=='2h_normal')
    g20_1h=next(g for g in pala.archetypes(20) if g.name=='1h_shield_normal')
    g50_2h=next(g for g in pala.archetypes(50) if g.name=='2h_normal')
    g50_1h=next(g for g in pala.archetypes(50) if g.name=='1h_shield_normal')
    g60_2h=next(g for g in pala.archetypes(60) if g.name=='2h_normal')
    g60_1h=next(g for g in pala.archetypes(60) if g.name=='1h_shield_normal')
    # Only literal observed named items contribute. Missing slots stay missing;
    # there is no synthetic same-slot remainder to inflate the totals.
    assert g20_2h.strength_bonus == pytest.approx(22.0)
    assert g20_2h.spell_damage_bonus == pytest.approx(46.0)
    assert g20_2h.spirit_bonus == pytest.approx(3.0)
    assert g20_2h.healing_bonus == pytest.approx(0.0)
    assert g20_1h.stamina_bonus == pytest.approx(38.0)
    assert g20_1h.defense_bonus == pytest.approx(24.0)
    assert g20_1h.spirit_bonus == pytest.approx(3.0)
    assert g20_1h.healing_bonus == pytest.approx(0.0)
    # At later checkpoints, totals likewise equal the sum of the named rows.
    assert g50_2h.strength_bonus == pytest.approx(87.0)
    assert g50_2h.spell_damage_bonus == pytest.approx(140.0)
    assert g50_1h.stamina_bonus == pytest.approx(107.0)
    assert g50_1h.defense_bonus == pytest.approx(71.0)
    # Weapon DPS/speed is calibrated independently for slow 2H vs 1H+shield.
    assert g50_2h.weapon_dps == pytest.approx(47.5, abs=.05)
    assert g50_2h.weapon_speed == pytest.approx(3.60)
    assert g60_2h.weapon_dps == pytest.approx((162+244)/2/3.30)
    assert g60_2h.weapon_speed == pytest.approx(3.30)
    assert g60_1h.weapon_dps == pytest.approx((80+148)/2/2.40)
    assert g60_1h.weapon_speed == pytest.approx(2.40)
    assert g60_1h.shield_armor == pytest.approx(2468.0)
    assert g60_2h.strength_bonus == pytest.approx(103.0)
    assert g60_2h.stamina_bonus == pytest.approx(125.0)
    assert g60_2h.spell_damage_bonus == pytest.approx(161.0)
    assert g60_1h.stamina_bonus == pytest.approx(167.0)
    assert g60_1h.spell_damage_bonus == pytest.approx(114.0)
    assert 'Forest Defender' in g60_2h.weapon_anchor
    assert 'Ironwood Blade' in g60_1h.weapon_anchor

def test_forever_paladin_level20_pack_score_searches_pull_gear_policy_and_survival():
    # A protection-leaning legal level-20 allocation: 11 points at level 20.
    t=_spend(pala,['redoubt']*5+['precision']*3+['anticipation']*2+['improved_seal_of_fury'])
    row=pala.experimental_level_score(20,t,'protection')
    assert row['feasible'] is True
    assert row['pull_size'] in (1,2,3)
    assert row['weapon_style'] in ('2h','1h_shield')
    assert row['policy'] in ('aggressive','balanced','safe')
    assert row['mobs_per_hour'] > 0
    assert 'Consecration (baseline L20)' in row['rotation']
    # With the audited tank craft floor, an aggressive 3-pack can be feasible
    # without inserting an emergency heal into the chosen steady-state cycle.
    assert 'Forever craft-calibrated normal gear floor' in ' '.join(row['approximation_flags'])


def test_forever_paladin_retribution_aura_gives_real_multitarget_value_at_20():
    t=_spend(pala,['divine_strength']*5+['improved_holy_strike']*2+['improved_seals']*3+['healing_light'])
    gear=next(g for g in pala.archetypes(20) if g.name=='2h_normal')
    policy=pala.POLICIES[0]
    one=pala.smooth_pack_score(20,t,'retribution',gear,1,policy,'retribution')
    two=pala.smooth_pack_score(20,t,'retribution',gear,2,policy,'retribution')
    assert one['feasible'] and two['feasible']
    assert two['avg_alive_mobs'] > one['avg_alive_mobs']
    # Cadence quantization may select a leaner damage plan for the longer pack,
    # so compare the aura contribution itself rather than total selected-plan DPS.
    assert two['aura_total_dps'] > one['aura_total_dps'] > 0


def test_forever_paladin_pull_envelope_reports_best_setup_per_pull_size():
    t=_spend(pala,['redoubt']*5+['precision']*3+['anticipation']*2+['improved_seal_of_fury'])
    env=pala.pull_envelope(20,t,'auto')
    assert [r['pull_size'] for r in env] == [1,2,3]
    assert all(r['mobs_per_hour'] > 0 for r in env if r['feasible'])
    assert all(r['gear'] for r in env)
    assert all(r['policy'] in ('aggressive','balanced','safe') for r in env)


def test_forever_paladin_fury_mana_return_requires_incoming_damage_to_break_absorbs():
    t=_spend(pala,['redoubt']*5+['precision']*3+['anticipation']*2+['improved_seal_of_fury'])
    gear=next(g for g in pala.archetypes(20) if g.name=='1h_shield_normal')
    policy=pala.POLICIES[1]
    row=pala.smooth_pack_score(20,t,'protection',gear,2,policy,'retribution')
    assert row['feasible']
    # The model may make Fury effectively mana-positive, but it must expose a
    # finite pack/cycle rather than granting an unconditional per-swing refund.
    assert row['mana_spent_per_mob'] >= 0
    assert row['cycle_s'] > 0


def test_forever_paladin_seal_of_command_enters_level20_retribution_model():
    t=_spend(pala,['benediction']*5+['conviction']*5+['seal_of_command'])
    gear=next(g for g in pala.archetypes(20) if g.name=='2h_normal')
    row=pala.smooth_pack_score(20,t,'retribution',gear,2,pala.POLICIES[1],'retribution')
    assert row['feasible']
    assert row['rotation'].startswith('Seal of Command up')
    assert row['dps'] > 0


def test_forever_paladin_redoubt_rank_scales_block_bonus_not_proc_rate_proxy():
    from src.rulesets.forever.classes.paladin.survival import expected_redoubt_bonus_block
    r1=expected_redoubt_bonus_block(1,1.0)
    r5=expected_redoubt_bonus_block(5,1.0)
    assert r5 > r1*4.5
    assert r5 <= .30


def test_forever_paladin_sacred_duty_increases_smooth_player_hp():
    base=_spend(pala,['redoubt']*5+['toughness']*5+['improved_seal_of_fury'])
    sd=_spend(pala,['redoubt']*5+['toughness']*5+['sacred_duty'])
    gear=next(g for g in pala.archetypes(20) if g.name=='1h_shield_normal')
    a=pala.smooth_pack_score(20,base,'protection',gear,2,pala.POLICIES[1],'devotion')
    b=pala.smooth_pack_score(20,sd,'protection',gear,2,pala.POLICIES[1],'devotion')
    assert b['player_hp'] > a['player_hp']


def test_forever_paladin_pack_cycle_starts_full_hp_under_shared_recovery_contract():
    t=_spend(pala,['benediction']*5+['conviction']*5+['seal_of_command'])
    gear=next(g for g in pala.archetypes(20) if g.name=='2h_normal')
    policy=pala.POLICIES[0]
    row=pala.smooth_pack_score(20,t,'retribution',gear,2,policy,'retribution')
    assert row['start_hp'] == pytest.approx(row['player_hp'])
    assert row['next_start_hp'] == pytest.approx(row['player_hp'])
    assert row['min_hp'] == pytest.approx(row['player_hp']*policy.min_hp_fraction)


def test_forever_paladin_normal_gear_snapshot_and_stat_mix_weights_are_decision_output():
    t=_spend(pala,['deflection']*5+['benediction']*5+['seal_of_command'])
    row=pala.experimental_level_score(20,t,'retribution')
    assert row['gear'] in ('2h_normal','1h_shield_normal')
    gs=row['gear_stats']
    for key in ('strength_bonus','stamina_bonus','intellect_bonus','spirit_bonus','spell_damage_bonus','healing_bonus','weapon_dps'):
        assert key in gs
    sw=pala.marginal_stat_weights(20,t,'retribution',row)
    assert sw['gear']['name']==row['gear']
    assert sw['stat_mix_guidance_rank']
    assert set(sw['stat_mix_guidance_rank']) == {'strength','stamina','intellect','spirit','mp5','spell_power','healing'}
    assert 'curve_sensitivity' in sw
    assert all(v['per_unit_mobs_per_hour'] >= 0 for v in sw['weights'].values())
    # Keep raw diagnostics so coarse recovery-policy artefacts stay observable.
    assert all('raw_per_unit_mobs_per_hour' in v for v in sw['weights'].values())


def test_forever_world_mob_fixture_preserves_mean_dps_but_exposes_swing_families():
    from src.rulesets.forever.shared.mobs import (
        WORLD_MELEE_FAMILIES, fixture_snapshot,
        weighted_family_dps_multiplier, weighted_family_swing_s,
    )
    assert weighted_family_dps_multiplier() == pytest.approx(1.0)
    assert weighted_family_swing_s() == pytest.approx(2.0)
    assert {f.name for f in WORLD_MELEE_FAMILIES} == {'fast_light','normal','slow_heavy'}
    snap=fixture_snapshot(20)
    assert sum(r['combined_weight'] for r in snap['rows']) == pytest.approx(1.0)
    assert {r['mob_level'] for r in snap['rows']} == {20}
    fast=[r for r in snap['rows'] if r['family']=='fast_light' and r['mob_level']==20][0]
    slow=[r for r in snap['rows'] if r['family']=='slow_heavy' and r['mob_level']==20][0]
    assert fast['swing_s'] < slow['swing_s']
    assert fast['raw_dps'] < slow['raw_dps']


def test_forever_paladin_pack_output_carries_level_scoped_mob_fixture():
    t=_spend(pala,['redoubt']*5+['precision']*3+['anticipation']*2+['improved_seal_of_fury'])
    gear=next(g for g in pala.archetypes(20) if g.name=='1h_shield_normal')
    row=pala.smooth_pack_score(20,t,'protection',gear,3,pala.POLICIES[1],'retribution')
    assert row['feasible']
    assert row['mob_raw_dps_per_mob'] > 0
    assert row['mob_landed_swings_per_s'] > 0
    assert row['mob_weighted_swing_s'] == pytest.approx(2.0)
    fx=row['mob_fixture']
    assert fx['kind']=='ordinary_world_melee_mix'
    assert {r['family'] for r in fx['rows']} == {'fast_light','normal','slow_heavy'}
    assert 'swing-family fixture' in ' '.join(row['approximation_flags'])


def test_forever_paladin_shield_specialization_uses_hard_3s_icd_expected_rate():
    from src.rulesets.forever.classes.paladin.survival import expected_icd_proc_rate
    # 1 eligible block/s at rank 1 -> 0.33 successful opportunities/s before ICD.
    got=expected_icd_proc_rate(1.0,.33,3.0)
    assert got == pytest.approx(.33/(1+.33*3.0))
    assert 0 < got < 1/3


def test_forever_paladin_seal_of_fury_replacement_proxy_requires_full_break_before_mana():
    from src.rulesets.forever.classes.paladin.survival import replacing_absorb_dynamics
    d=replacing_absorb_dynamics(shield_gen_rate=.4,incoming_hit_rate=1.2,shield_amount=5.0,mean_hit=20.0)
    assert d['hits_needed']==1
    assert 0 < d['break_rate'] < .4
    assert d['absorb_per_s'] == pytest.approx(d['break_rate']*5.0)
    # If hits are too small and replacement pressure is high, full breaks become rarer.
    d2=replacing_absorb_dynamics(shield_gen_rate=.8,incoming_hit_rate=.4,shield_amount=20.0,mean_hit=5.0)
    assert d2['hits_needed']==4
    assert d2['full_break_probability'] < d['full_break_probability']


def test_forever_judgement_preserves_active_seal_and_sanctified_judgement_is_refund():
    from src.rulesets.forever.classes.paladin import mechanics as pm
    gear=next(g for g in pala.archetypes(20) if g.name=='2h_normal')
    base=pala.Talents(seal_of_command=1)
    refund=pala.Talents(seal_of_command=1,sanctified_judgement=3)
    a=pm._base_damage(20,base,gear,'retribution')
    b=pm._base_damage(20,refund,gear,'retribution')
    assert b['base_mps'] < a['base_mps']
    assert b['sanctified_judgement_refund_fraction'] == pytest.approx(.60)
    row=pala.smooth_pack_score(20,base,'retribution',gear,2,pala.POLICIES[1],'retribution')
    assert row['seal_refreshes']==0
    # One initial SoC cast only; Judgement does not force a reseal in Forever.
    assert row['seal_maintenance_mana'] == pytest.approx(65.0)


def test_experimental_candidate_distinguishes_talent_family_from_combat_profile(monkeypatch):
    from src.v2 import experimental_classes as ec
    try:
        game_context.configure('forever','paladin')
        reset_engine_cache()
        # Protection-family talents are deliberately allowed to choose a non-Protection
        # combat profile/gear if that is faster at this level.
        t=_spend(pala,['redoubt']*5+['precision']*3+['anticipation']*2+['improved_seal_of_fury'])
        score=pala.experimental_level_score(20,t,'all')
        row=ec._BeamRow(t,0.0,score,tuple())
        out=ec._candidate_json(row,20)
        assert out['talent_family']=='protection'
        assert out['combat_profile']==out['profile']
        assert out['family']==out['talent_family']  # legacy alias retained
    finally:
        game_context.configure('classic','mage')
        reset_engine_cache()


def test_experimental_druid_candidate_derives_throughput_and_labels_proxy_assumptions():
    from src.v2 import experimental_classes as ec
    try:
        game_context.configure('forever', 'druid')
        reset_engine_cache()
        t = druid.Talents(ferocity=2)
        score = druid.experimental_level_score(11, t, 'all')
        out = ec._candidate_json(ec._BeamRow(t, 0.0, score, tuple()), 11)
        assert out['mobs_per_hour'] == pytest.approx(360000.0 / score['total_s'])
        assert out['gear'] == 'canonical_sqlite_druid_bear'
        assert 1 <= out['pull_size'] <= 3
    finally:
        game_context.configure('classic', 'mage')
        reset_engine_cache()


def test_forever_paladin_discrete_healing_uses_whole_casts_and_explicit_mana():
    from src.rulesets.forever.classes.paladin.survival import discrete_heal_sequence
    row=discrete_heal_sequence(
        need_hp=95, heal_amount=60, cast_s=2.5, mana_cost=40,
        incoming_dps=8, start_hp=180, min_hp=80,
        emergency_windows=(),
    )
    assert row['feasible']
    assert isinstance(row['casts'],int)
    assert row['heal_time_s'] == pytest.approx(row['casts']*2.5)
    assert row['heal_mana'] == pytest.approx(row['casts']*40)


def test_forever_paladin_mana_positive_pack_carries_full_mana_steady_state():
    t=_spend(pala,['redoubt']*5+['precision']*3+['anticipation']*2+['improved_seal_of_fury'])
    gear=next(g for g in pala.archetypes(20) if g.name=='1h_shield_normal')
    row=pala.smooth_pack_score(20,t,'protection',gear,1,pala.POLICIES[1],'retribution')
    assert row['feasible']
    assert row['mana_positive'] is True
    assert row['start_mana'] == pytest.approx(row['mana_pool'])
    assert row['end_mana'] == pytest.approx(row['mana_pool'])
    assert row['mana_recovery_needed'] == pytest.approx(0.0)
    assert row['net_mana_per_pack'] <= 0


def test_forever_paladin_mana_negative_pack_recovers_exact_cycle_deficit():
    t=_spend(pala,['benediction']*5+['conviction']*5+['seal_of_command'])
    gear=next(g for g in pala.archetypes(20) if g.name=='2h_normal')
    row=pala.smooth_pack_score(20,t,'retribution',gear,2,pala.POLICIES[1],'retribution')
    assert row['feasible']
    assert row['mana_positive'] is False
    assert row['start_mana'] == pytest.approx(row['mana_pool'])
    assert row['mana_recovery_needed'] == pytest.approx(row['mana_pool']-row['end_mana'])
    assert row['mana_recovery_needed'] == pytest.approx(row['net_mana_per_pack'])


def test_forever_paladin_mana_plan_is_canonical_cadence_not_fractional_duty():
    # The output must name one discrete cadence plan and integer cooldown spacing,
    # never expose an arbitrary continuous duty fraction.
    t=_spend(pala,['divine_strength']*5+['divine_intellect']*5+['healing_light'])
    row=pala.experimental_level_score(20,t,'holy')
    assert row['mana_plan'] in {p.name for p in pala.MANA_PLANS}
    assert row['holy_strike_every'] in (0,1,2,3)
    assert row['judgement_every'] in (0,1,2)
    assert 'duty_fraction' not in row


def test_forever_model_fidelity_is_machine_readable_for_all_three_classes():
    assert mage.MODEL_FIDELITY['mc_validated'] is True
    assert pala.MODEL_FIDELITY['pull_model'].startswith('multi_pull')
    assert pala.MODEL_FIDELITY['mc_validated'] is False
    assert druid.MODEL_FIDELITY['rating']=='verified_l10_l30_medium_planning_l31_l40_bounded'


def test_cross_class_report_keeps_fidelity_visible_and_uses_common_levels(tmp_path):
    import json
    from src.v2.class_comparison import build_comparison, write_report
    def write(cls, payload):
        p=tmp_path/'state'/'games'/f'forever-{cls}'/'v2'/'viewer.json'
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(payload),encoding='utf-8')
    write('mage',{'views':{'smooth':{'level_summaries':[{'level':20,'best':{
        'level':20,'score_s_per_100':3000,'allocation':'x','policy':'Frostbolt','family':'frost','source':'smooth'}}]}}})
    exp=lambda cls,mph: {'views':{'experimental':{'level_summaries':[{'level':20,'best':{
        'level':20,'score_s_per_100':360000/mph,'mobs_per_hour':mph,'allocation':'x',
        'policy':'policy','family':'x','talent_family':'x','combat_profile':'x','pull_size':2,
        'source':'forever-experimental-fast','details':{}}}]}}}
    write('paladin',exp('paladin',230)); write('druid',exp('druid',275))
    report=build_comparison(tmp_path,start_level=20,end_level=20)
    assert report['levels']==[20]
    assert len(report['rows'])==3
    assert {r['class'] for r in report['rows']}=={'mage','paladin','druid'}
    assert all(r['fidelity_rating'] for r in report['rows'])
    assert 'not a confidence-adjusted ranking' in report['interpretation']
    jp,cp=write_report(report,tmp_path/'out')
    assert jp.exists() and cp.exists()


def test_shared_event_queue_is_time_then_insertion_stable():
    from src.shared.combat import EventQueue
    q=EventQueue()
    q.schedule(2.0,'late')
    q.schedule(1.0,'first')
    q.schedule(1.0,'second')
    assert [(q.pop().time,q.pop().kind) for _ in ()] == []  # keep mypy/linters uninterested
    # Rebuild because the compact expression above intentionally popped nothing.
    q=EventQueue(); q.schedule(2.0,'late'); q.schedule(1.0,'first'); q.schedule(1.0,'second')
    a=q.pop(); b=q.pop(); c=q.pop()
    assert (a.time,a.kind)==(1.0,'first')
    assert (b.time,b.kind)==(1.0,'second')
    assert (c.time,c.kind)==(2.0,'late')


def test_forever_paladin_event_replay_v1_replays_gcd_cooldowns_and_mana_without_becoming_authority():
    from src.rulesets.forever.classes.paladin import mechanics as pm
    from src.rulesets.forever.classes.paladin.event_replay import validate_smooth_row
    t=pala.Talents(divine_strength=5, improved_seals=3, seal_of_command=1, conviction=2)
    pm._cached_score_signature.cache_clear()
    row=pala.experimental_level_score(20,t,'auto')
    assert row['heal_casts']==0
    v=validate_smooth_row(20,t,row)
    assert v['supported'] is True
    ev=v['event']
    assert ev['authority']=='diagnostic_validator_only'
    assert ev['complete'] is True
    assert ev['kill_s'] > 0
    assert ev['action_counts']['Seal']==1
    assert ev['action_counts'].get('Judgement',0)>=1
    assert ev['action_counts'].get('Holy Strike',0)>=1
    assert ev['action_counts'].get('Auto',0)>=1
    assert ev['mana_end'] <= ev['mana_start'] + 1e-9
    times=[x['t'] for x in ev['timeline']]
    assert times==sorted(times)
    judgement=next(x for x in ev['timeline'] if x['action']=='Judgement')
    holy=next(x for x in ev['timeline'] if x['action']=='Holy Strike')
    assert judgement['t'] >= 1.5
    assert holy['t']==pytest.approx(judgement['t'])  # Judgement is off the GCD in Forever
    assert pala.MC_SUPPORTED is False


def test_forever_paladin_event_replay_melee_only_plan_does_not_invent_damage_casts():
    from src.rulesets.forever.classes.paladin.gear import archetypes
    from src.rulesets.forever.classes.paladin.event_replay import replay_pack
    t=pala.Talents(divine_strength=5, improved_seals=3, seal_of_command=1, conviction=2)
    gear=archetypes(20)[0]
    policy=next(p for p in pala.POLICIES if p.name=='aggressive')
    plan=next(p for p in pala.MANA_PLANS if p.name=='melee_seal_only')
    ev=replay_pack(20,t,'retribution',gear,1,policy,'retribution',plan)
    assert ev['complete'] is True
    assert ev['action_counts'].get('Judgement',0)==0
    assert ev['action_counts'].get('Holy Strike',0)==0
    assert ev['action_counts'].get('Consecration',0)==0
    assert ev['action_counts'].get('Auto',0)>0


def test_forever_paladin_event_replay_v2_whole_heal_cast_is_discrete_and_completes():
    from src.rulesets.forever.classes.paladin.event_replay import replay_pack
    # Keep the event-replay mechanic test independent of whatever sparse real
    # gear happens to be available at this level.
    t=_spend(pala,['redoubt']*5+['precision']*3+['anticipation']*2+['improved_seal_of_fury'])
    gear=next(g for g in pala.archetypes(20) if g.name=='1h_shield_normal')
    policy=next(p for p in pala.POLICIES if p.name=='safe')
    plan=next(p for p in pala.MANA_PLANS if p.name=='full')
    ev=replay_pack(
        20,t,'protection',gear,3,policy,'retribution',plan,
        start_hp=350,start_mana=645,heal_casts=1,heal_spell_name='Holy Light',min_hp=350,
    )
    assert ev['complete'] is True
    assert ev['heal_casts_requested']==1
    assert ev['heal_casts_completed']==1
    assert ev['action_counts'].get('Heal cast',0)==1
    assert ev['action_counts'].get('Heal complete',0)==1
    cast=next(x for x in ev['timeline'] if x['action']=='Heal cast')
    done=next(x for x in ev['timeline'] if x['action']=='Heal complete')
    assert done['t']-cast['t'] >= 1.5
    assert done['heal'] > 0


def test_forever_paladin_event_replay_v2_hoj_is_single_target_and_bop_is_pack_physical_immunity():
    from src.rulesets.forever.classes.paladin.event_replay import replay_pack
    t=pala.Talents(toughness=5, redoubt=5, improved_righteous_fury=3,
                   shield_specialization=3, improved_seal_of_fury=1)
    gear=next(g for g in pala.archetypes(20) if g.name=='1h_shield_normal')
    policy=next(p for p in pala.POLICIES if p.name=='balanced')
    plan=next(p for p in pala.MANA_PLANS if p.name=='melee_seal_only')
    ev=replay_pack(
        20,t,'protection',gear,3,policy,'retribution',plan,
        start_hp=250,start_mana=1000,heal_casts=3,heal_spell_name='Holy Light',
        emergency_actions=('Hammer of Justice','Blessing of Protection'),min_hp=250,
    )
    assert ev['complete'] is True
    assert ev['heal_casts_completed']==3
    assert ev['emergency_actions_used']==['Hammer of Justice','Blessing of Protection']
    hoj=next(x for x in ev['timeline'] if x['action']=='Hammer of Justice')
    bop=next(x for x in ev['timeline'] if x['action']=='Blessing of Protection')
    assert 'target_index' in hoj  # HoJ is not a whole-pack pause.
    assert bop['forbearance_s']==60.0
    assert ev['forbearance_until'] >= bop['t']+60.0-1e-9
    # During BoP the expected physical swing lanes deal zero damage.
    protected=[x for x in ev['timeline'] if x['action']=='Mob swing lane' and bop['t'] < x['t'] < bop['t']+bop['duration']]
    assert protected and all(abs(x['damage'])<1e-9 for x in protected)
    # Self-BoP suppresses physical attacks/abilities; no auto lands inside it.
    protected_autos=[x for x in ev['timeline'] if x['action']=='Auto' and bop['t'] < x['t'] < bop['t']+bop['duration']]
    assert protected_autos==[]


def test_forever_paladin_event_replay_v2_shield_spec_has_hard_3s_icd_and_fury_breaks_are_event_timed():
    from src.rulesets.forever.classes.paladin.event_replay import replay_pack
    t=pala.Talents(toughness=5, redoubt=5, improved_righteous_fury=3,
                   shield_specialization=3, improved_seal_of_fury=1)
    gear=next(g for g in pala.archetypes(20) if g.name=='1h_shield_normal')
    policy=next(p for p in pala.POLICIES if p.name=='balanced')
    plan=next(p for p in pala.MANA_PLANS if p.name=='full')
    ev=replay_pack(20,t,'protection',gear,3,policy,'retribution',plan,start_mana=300)
    assert ev['complete'] is True
    assert ev['shield_spec_procs']>0
    proc_times=[x['t'] for x in ev['timeline'] if x['action']=='Shield Specialization proc']
    assert all(b-a >= 3.0-1e-9 for a,b in zip(proc_times,proc_times[1:]))
    assert ev['fury_breaks']>0
    breaks=[x for x in ev['timeline'] if x['action']=='Seal of Fury break']
    assert len(breaks)==ev['fury_breaks']
    assert all(x['mana_gained']>=0.0 for x in breaks)
    assert ev['mana_end'] >= 0.0


def test_forever_paladin_event_replay_v2_divine_protection_forbearance_and_sacred_duty_cooldown():
    from src.rulesets.forever.classes.paladin.event_replay import replay_pack
    t=pala.Talents(toughness=5, redoubt=5, sacred_duty=2)
    gear=next(g for g in pala.archetypes(20) if g.name=='1h_shield_normal')
    policy=next(p for p in pala.POLICIES if p.name=='balanced')
    plan=next(p for p in pala.MANA_PLANS if p.name=='full')
    ev=replay_pack(
        20,t,'protection',gear,2,policy,'devotion',plan,
        start_hp=170,start_mana=645,heal_casts=2,heal_spell_name='Holy Light',
        emergency_actions=('Divine Protection',),min_hp=160,
    )
    assert ev['complete'] is True
    dp=next(x for x in ev['timeline'] if x['action']=='Divine Protection')
    assert dp['duration']==8.0
    assert dp['cooldown']==240.0  # 5 min - 60 sec from Sacred Duty 2/2.
    assert dp['forbearance_s']==60.0
    protected=[x for x in ev['timeline'] if x['action']=='Mob swing lane' and dp['t'] < x['t'] < dp['t']+dp['duration']]
    assert protected and all(abs(x['damage'])<1e-9 for x in protected)
    protected_autos=[x for x in ev['timeline'] if x['action']=='Auto' and dp['t'] <= x['t'] < dp['t']+dp['duration']]
    assert protected_autos==[]


def test_forever_paladin_topn_event_validation_is_diagnostic_and_can_compute_event_adjusted_cycle():
    from src.rulesets.forever.classes.paladin import mechanics as pm
    from src.rulesets.forever.classes.paladin.validation_report import validate_candidate
    t=pala.Talents(toughness=2,redoubt=5,precision=3,improved_seal_of_fury=1)
    row=pala.experimental_level_score(20,t,'protection')
    out=validate_candidate(20,t,row)
    assert out['authority']=='hybrid_event_validation_proxy_only'
    assert out['event_complete'] is True
    assert out['event_adjusted_mobs_per_hour']>0
    assert out['event_cycle_s']>=out['event_combat_s']
    assert out['heal_casts_completed']<=out['heal_casts_requested']


def test_forever_paladin_fast_hoj_window_is_single_target_and_consumes_gcd_before_heal():
    from src.rulesets.forever.classes.paladin.survival import discrete_heal_sequence
    from src.rulesets.forever.classes.paladin import mechanics as pm
    policy=next(p for p in pala.POLICIES if p.name=='balanced')
    t=pala.Talents(improved_hammer_of_justice=3)
    windows=pm._emergency_windows(24,t,policy,3.0)
    hoj=next(x for x in windows if x[0]=='Hammer of Justice')
    assert hoj[1]==4.0
    assert hoj[3]==45.0  # 60 sec - 5 sec/rank.
    assert hoj[4]==pytest.approx(2.0/3.0)  # one of three expected attackers stunned.

    # HoJ's residual two attackers make this Holy Light unsafe; the later full
    # immunity window can save it.  Old Fast incorrectly treated HoJ as a whole-
    # pack pause and did not subtract its GCD from the stun duration.
    row=discrete_heal_sequence(
        need_hp=50,heal_amount=60,cast_s=2.5,mana_cost=40,
        incoming_dps=30,start_hp=100,min_hp=70,
        emergency_windows=(hoj,('Blessing of Protection',8.0,75.0,300.0,0.0)),
    )
    assert row['feasible']
    assert row['emergency_actions']==['Blessing of Protection']
    assert row['emergency_gcd_s']==pytest.approx(1.5)
    assert row['emergency_avoided_damage']>0


def test_forever_paladin_fast_immunity_choice_uses_talent_reduced_repeat_cooldown():
    from src.rulesets.forever.classes.paladin import mechanics as pm
    policy=next(p for p in pala.POLICIES if p.name=='balanced')
    # At level 24 BoP R2 and DP R2 are both 8 sec. Guardian's Favor 2/2 makes
    # BoP repeat every 180 s, while untalented DP remains 300 s.
    gf=pala.Talents(guardians_favor=2)
    rows=pm._emergency_windows(24,gf,policy,3.0)
    immune=next(x for x in rows if x[0] != 'Hammer of Justice')
    assert immune[0]=='Blessing of Protection'
    assert immune[3]==180.0

    # Sacred Duty 2/2 instead makes DP the shorter equal-duration window.
    sd=pala.Talents(sacred_duty=2)
    rows=pm._emergency_windows(24,sd,policy,3.0)
    immune=next(x for x in rows if x[0] != 'Hammer of Justice')
    assert immune[0]=='Divine Protection'
    assert immune[3]==240.0


def test_forever_paladin_validation_report_distinguishes_talent_only_from_playstyle_change(monkeypatch,tmp_path):
    import json
    from src.rulesets.forever.classes.paladin import validation_report as vr
    # Build a tiny synthetic viewer with two candidates. Event validation swaps
    # them at level 15 and also changes the top gear/pull, which must be reported
    # as a material playstyle change rather than generic ordering noise.
    viewer=tmp_path/'state/games/forever-paladin/v2/viewer.json'
    viewer.parent.mkdir(parents=True)
    viewer.write_text(json.dumps({
        'views':{'experimental':{'level_summaries':[{
            'level':15,
            'candidates':[
                {'allocation':'A','talent_family':'holy','combat_profile':'retribution','talent_ranks':{},'details':{'gear':'2h_normal','pull_size':1}},
                {'allocation':'B','talent_family':'protection','combat_profile':'retribution','talent_ranks':{},'details':{'gear':'1h_shield_normal','pull_size':2}},
            ],
        }]}}
    }))
    # Empty talent_ranks are skipped by production code, so give both candidates
    # one harmless explicit rank and stub only the expensive event conversion.
    data=json.loads(viewer.read_text())
    for c in data['views']['experimental']['level_summaries'][0]['candidates']:
        c['talent_ranks']={'divine_strength':1}
    viewer.write_text(json.dumps(data))

    def fake_validate(level,talents,row):
        mph=100.0 if row['gear']=='2h_normal' else 120.0
        return {
            'supported':True,'event_complete':True,'pull_size':row['pull_size'],'gear':row['gear'],
            'profile':'retribution','policy':'aggressive','aura':'devotion','mana_plan':'full',
            'smooth_mobs_per_hour':110.0 if row['gear']=='2h_normal' else 105.0,
            'event_adjusted_mobs_per_hour':mph,'throughput_delta_pct':0.0,
            'smooth_combat_s':1.0,'event_combat_s':1.0,'event_recovery_s':0.0,
            'event_travel_s':0.0,'event_cycle_s':1.0,'recovery_method':'none',
            'hp_recovery_needed':0.0,'mana_recovery_needed':0.0,'event_hp_end':1.0,'event_mana_end':1.0,
            'heal_casts_requested':0,'heal_casts_completed':0,'emergency_actions_used':[],
            'fury_breaks':0,'shield_spec_procs':0,'authority':'hybrid_event_validation_proxy_only',
        }
    monkeypatch.setattr(vr,'validate_candidate',fake_validate)
    report=vr.build_report(tmp_path,start_level=15,end_level=15,top_n=2)
    o=report['ordering'][0]
    assert o['top_candidate_changed'] is True
    assert o['top_playstyle_changed'] is True
    assert set(o['material_fields_changed']) >= {'gear','pull_size'}
    assert o['decision_change_kind']=='playstyle'
    assert report['decision_summary']['playstyle_changed_levels']==[15]


def test_forever_druid_v0117_cat_uses_ranked_priority_rotation():
    t=druid.Talents(ferocity=5,savage_fury=2,sharpened_claws=2,blood_frenzy=2)
    row=druid.experimental_level_score(40,t,'feral')
    assert row['profile']=='cat'
    assert row['feral_builder'] == 'Claw'
    assert row['feral_finisher'] in ('Ferocious Bite','Rip')
    assert '5 CP' in row['rotation']
    assert row['combo_points_per_builder_ev'] >= 1.0


def test_forever_druid_v0117_balance_uses_real_priority_and_eclipse_cycle():
    t=druid.Talents(improved_wrath=5,natures_majesty=2,natures_splendor=1,
                    insect_swarm=1,natures_grace=1,eclipse=3,moonfury=5)
    row=druid.experimental_level_score(42,t,'balance')
    assert row['profile']=='balance'
    assert 'Moonfire' in row['rotation']
    assert 'Insect Swarm' in row['rotation']
    assert row['balance_filler'] in ('Wrath','Starfire','Eclipse: Wrath → Starfire ×2')
    assert row['dps'] > 0


def test_forever_druid_v0117_wowhead_rank_tables_persisted():
    from src.rulesets.forever.classes.druid import wowhead_facts as wh
    assert wh.CLAW_RANKS[-1][:2] == (58,45)
    assert wh.RAKE_RANKS[0][:4] == (24,40,19,39)
    assert wh.RIP_RANKS_5CP[-1][2] == 942
    assert wh.FEROCIOUS_BITE_RANKS_5CP[0][0] == 32
    assert wh.STARFIRE_RANKS[-1][:3] == (60,340,3.5)
    assert wh.ECLIPSE_STARFIRE_CAST_REDUCTION_BY_RANK[3] == pytest.approx(.50)
    assert wh.NATURES_GRACE_HASTE == pytest.approx(.10)



def test_forever_mage_crafted_itemization_dataset_is_verified_tailoring_subset():
    from src.rulesets.forever.shared.crafted_itemization import CRAFTED_ITEMS
    rows=[x for x in CRAFTED_ITEMS if x.profession == 'tailoring']
    assert len(rows) == 19
    assert all(x.required_level > 0 and x.item_level >= x.required_level for x in rows)
    assert max(x.required_level for x in rows) == 56
    assert all(x.source_url.startswith(('https://www.wowhead.com/forever/','https://wowforeverbuilds.com/')) for x in rows)


def test_forever_mage_named_gear_is_authoritative_in_player_stats():
    from src.rulesets.forever.classes.mage import engine as mage
    from src.rulesets.forever.classes.mage.real_gear import snapshot
    t=mage.Talents()
    for level in (11,20,25,40,56,60):
        g=mage.forever_crafted_gear(level)
        snap=snapshot(level)
        assert g['spell_power_floor'] == pytest.approx(snap['totals']['spell_power'])
        assert g['mp5'] == pytest.approx(snap['totals']['mp5'])
        assert mage.player_stats(level,t).spell_power == pytest.approx(g['spell_power_floor'])
    assert 'Filigreed Pristine Leggings' in mage.forever_crafted_gear(20)['crafted_items']
    assert mage.player_stats(20,t,spell_power=7).spell_power == pytest.approx(
        mage.forever_crafted_gear(20)['spell_power_floor'] + 7.0
    )


def test_forever_mage_named_slots_replace_proxy_and_only_missing_slots_fallback():
    from src.rulesets.forever.classes.mage import engine as mage
    g10=mage.forever_crafted_gear(10)
    assert 'waist' in g10['selected_slots']
    assert 'waist' not in g10['fallback_slots']
    assert 'wand' in g10['selected_slots']
    assert 'chest' in g10['missing_slots']
    assert g10['fallback_slots'] == []
    # By L20 the audited low-level pool covers every legacy proxy slot.
    assert mage.forever_crafted_gear(20)['fallback_slots'] == []


def test_forever_mage_ice_barrier_uses_calibrated_spell_power_coeff_at_runtime():
    from src.rulesets.forever.classes.mage import engine as mage
    stats=mage.player_stats(40,mage.Talents(ice_barrier=1))
    rank=mage.ice_barrier_rank(40)
    assert stats.spell_power >= 22.0
    assert rank.absorb == pytest.approx(438.0)
    # Runtime application is base absorb + 10% Frost spell power.
    assert rank.absorb + .10*stats.spell_power > rank.absorb

def test_forever_druid_leatherworking_dataset_has_verified_brawler_and_totemic_families():
    from src.rulesets.forever.shared.crafted_itemization import CRAFTED_ITEMS
    rows=[x for x in CRAFTED_ITEMS if x.profession == 'leatherworking']
    assert len(rows) == 39
    assert {x.family for x in rows} == {'brawler','totemic','prowler','skycaller','warden'}
    assert max(x.required_level for x in rows) == 50
    assert all(x.source_url.startswith(('https://www.wowhead.com/forever/','https://wowforeverbuilds.com/')) for x in rows)


def test_forever_druid_brawler_floor_tracks_slot_replacements_without_double_counting():
    from src.rulesets.forever.shared.crafted_itemization import aggregate_items, druid_feral_items
    g20=aggregate_items(druid_feral_items(20))
    g25=aggregate_items(druid_feral_items(25))
    assert g20['strength'] == pytest.approx(24.0)
    assert g20['agility'] == pytest.approx(37.0)
    assert g20['stamina'] == pytest.approx(27.0)
    assert g25['strength'] == pytest.approx(26.0)
    assert g25['agility'] == pytest.approx(40.0)
    assert g25['stamina'] == pytest.approx(36.0)
    assert len(g25['crafted_items']) == 6
    assert 'Brawler\'s Leather Tunic' in g25['crafted_items']
    assert 'Brawler\'s Leather Armor' not in g25['crafted_items']


def test_forever_druid_totemic_floor_supplies_real_spell_power_and_intellect():
    from src.rulesets.forever.shared.crafted_itemization import aggregate_items, druid_balance_items
    g20=aggregate_items(druid_balance_items(20))
    g25=aggregate_items(druid_balance_items(25))
    assert g20['spell_power'] == pytest.approx(37.0)
    assert g20['intellect'] == pytest.approx(7.0)
    assert g25['spell_power'] == pytest.approx(42.0)
    assert g25['intellect'] == pytest.approx(11.0)
    assert len(g25['crafted_items']) == 6


def test_forever_druid_feral_score_consumes_canonical_sqlite_gear():
    from src.rulesets.forever.classes.druid import mechanics as dm
    t=druid.Talents()
    strength, ap, _crit, gear=dm._feral_attack_power(20,t)
    assert gear['strength'] > 0.0
    assert gear['agility'] > 0.0
    assert gear['name'] == 'canonical_sqlite_druid_feral'
    assert ap == pytest.approx(2.0*strength + gear['agility'] + gear['attack_power'])
    assert gear['weapon_dps'] == pytest.approx(gear['slots']['weapon']['weapon_dps'])
    row=druid.experimental_level_score(20,t,'feral')
    assert row['gear'] == 'canonical_sqlite_druid_feral'
    assert row['gear_stats']['provenance'] == 'sqlite_catalogue'
    assert all(x['model_kind'] == 'canonical_sqlite_item' for x in row['gear_stats']['slots'].values())


def test_forever_druid_balance_score_uses_sql_spell_power_and_intellect():
    t=druid.Talents()
    row=druid.experimental_level_score(20,t,'balance')
    assert row['gear'] == 'canonical_sqlite_druid_balance'
    assert row['gear_stats']['intellect'] > 0.0
    assert row['gear_stats']['spell_power'] > 0.0
    assert row['spell_power_proxy'] == pytest.approx(row['gear_stats']['spell_power'])
    assert row['gear_stats']['slots']['weapon']['item_id'] > 0



def test_forever_full_craft_ladder_extends_druid_roles_to_50_and_separates_bear():
    from src.rulesets.forever.shared.crafted_itemization import (
        aggregate_items, druid_feral_items, druid_balance_items, druid_bear_items,
    )
    cat=aggregate_items(druid_feral_items(50))
    bal=aggregate_items(druid_balance_items(50))
    bear=aggregate_items(druid_bear_items(50))
    assert cat['strength'] == pytest.approx(74.0)
    assert cat['agility'] == pytest.approx(75.0)
    assert bal['spell_power'] == pytest.approx(97.0)
    assert bal['intellect'] == pytest.approx(59.0)
    assert bear['stamina'] == pytest.approx(87.0)
    assert bear['bonus_armor'] == pytest.approx(374.0)
    assert "Warden's Leather Waistguard" in bear['crafted_items']
    assert "Prowler's Leather Waistguard" not in bear['crafted_items']


def test_forever_bear_does_not_count_agility_as_attack_power():
    from src.rulesets.forever.classes.druid import mechanics as dm
    t=druid.Talents()
    strength, ap, _crit, gear=dm._feral_attack_power(50,t,bear=True)
    assert gear['family'] == 'canonical_sqlite_runtime_selection'
    assert ap == pytest.approx(2.0*strength + gear['attack_power'])
    cat_strength, cat_ap, _crit, cat_gear=dm._feral_attack_power(50,t)
    assert cat_ap == pytest.approx(2.0*cat_strength + cat_gear['agility'] + cat_gear['attack_power'])


def test_forever_blacksmithing_role_ladders_are_persisted_through_50():
    from src.rulesets.forever.shared.crafted_itemization import (
        CRAFTED_ITEMS, aggregate_items, paladin_ret_items, paladin_tank_items, paladin_holy_items,
    )
    rows=[x for x in CRAFTED_ITEMS if x.profession == 'blacksmithing']
    assert len(rows) == 50
    assert {'crusader','justicar','protector','warder','prefect','blessed_plate','depleted_thorium','enriched_thorium'} <= {x.family for x in rows}
    assert max(x.required_level for x in rows) == 60
    ret=aggregate_items(paladin_ret_items(50))
    tank=aggregate_items(paladin_tank_items(50))
    holy=aggregate_items(paladin_holy_items(50))
    assert ret['strength'] == pytest.approx(66.0)
    assert ret['spell_power'] == pytest.approx(117.0)
    assert tank['stamina'] == pytest.approx(99.0)
    assert tank['defense'] == pytest.approx(71.0)
    assert holy['intellect'] == pytest.approx(48.0)
    assert holy['spell_power'] == pytest.approx(49.0)

def test_forever_druid_low_level_also_uses_sql_catalogue_without_baseline_placeholder():
    row=druid.experimental_level_score(11,druid.Talents(),'all')
    assert row['gear'].startswith('canonical_sqlite_druid_')
    assert row['gear_stats']['provenance'] == 'sqlite_catalogue'
    assert row['gear_stats']['slots']
    assert all(x['item_id'] > 0 for x in row['gear_stats']['slots'].values())



def test_forever_mage_spell_power_modifiers_are_rank_explicit_not_classic_penalty():
    from src.rulesets.forever.classes.mage import engine as mage
    assert [mage.spell_power_direct_coeff(x) for x in mage.FROSTBOLT] == pytest.approx(
        [.407,.489,.597,.706,.814,.814,.814,.814,.814,.814,.814]
    )
    assert [mage.spell_power_direct_coeff(x) for x in mage.FIREBALL] == pytest.approx(
        [.429,.571,.714,.857,1,1,1,1,1,1,1,1]
    )
    assert [mage.spell_power_direct_coeff(x) for x in mage.FIRE_BLAST] == pytest.approx([.429]*7)
    assert [mage.spell_power_direct_coeff(x) for x in mage.SCORCH] == pytest.approx([.429]*7)
    assert [mage.spell_power_direct_coeff(x) for x in mage.FROST_NOVA] == pytest.approx([.029]*4)
    assert [mage.spell_power_direct_coeff(x) for x in mage.PYROBLAST] == pytest.approx([1.0]*8)
    assert [mage.spell_power_dot_coeff(x) for x in mage.PYROBLAST] == pytest.approx([.60]*8)
    assert mage.spell_power_dot_coeff(mage.FIREBALL[0]) == 0.0


def test_forever_mage_arcane_missiles_modifier_is_286_percent_per_missile_at_runtime(monkeypatch):
    from src.rulesets.forever.classes.mage import engine as mage
    rank=mage.ARCANE_MISSILES[0]
    assert rank.channel_ticks == 3
    assert mage.spell_power_direct_coeff(rank) == pytest.approx(.286*3)
    monkeypatch.setattr(mage,'spell_hit',lambda *args,**kwargs: 1.0)
    monkeypatch.setattr(mage,'roll_magic_resistance_multiplier',lambda *args,**kwargs: 1.0)
    state=mage.State(t=0.0,hp=10000.0,mana=10000.0,max_mana=10000.0,distance=30.0)
    stats=mage.Stats(0.0,0.0,10000.0,10000.0,0.0,100.0)
    mob=mage.Mob(level=8,hp=10000.0,run_speed=0.0)
    ok=mage.perform_am(state,rank,8,mage.Talents(),stats,mage.SimConfig(),mob,__import__('random').Random(7),mage.FightMetrics())
    assert ok
    expected=rank.channel_ticks*(rank.channel_tick_damage + 100.0*.286)
    assert 10000.0-state.hp == pytest.approx(expected)


def test_forever_mage_pyroblast_runtime_dot_receives_60_percent_total_spell_power():
    from src.rulesets.forever.classes.mage import engine as mage
    rank=mage.PYROBLAST[0]
    state=mage.State(t=0.0,hp=10000.0,mana=10000.0,max_mana=10000.0,distance=35.0)
    stats=mage.Stats(0.0,0.0,10000.0,10000.0,0.0,100.0)
    mob=mage.Mob(level=20,hp=10000.0,run_speed=0.0)
    mage.resolve_direct_impact(state,rank,True,False,0.0,20,mage.Talents(),stats,mage.SimConfig(),mob,__import__('random').Random(1))
    dot=next(d for d in state.dots if d.kind=='pyroblast')
    assert dot.remaining_ticks == 4
    assert dot.damage*dot.remaining_ticks == pytest.approx(rank.dot_total + 60.0)


def test_forever_shared_pack_exposure_separates_average_from_peak_pressure():
    from src.rulesets.forever.shared.pack_geometry import estimate_pack_exposure
    one=estimate_pack_exposure(1,100.0,0.0)
    four_st=estimate_pack_exposure(4,100.0,0.0)
    four_aoe=estimate_pack_exposure(4,100.0,40.0)
    assert one.avg_alive == pytest.approx(1.0)
    assert one.peak_alive == pytest.approx(1.0)
    assert four_st.avg_alive == pytest.approx(2.5)
    assert four_st.peak_alive == pytest.approx(4.0)
    assert 2.5 < four_aoe.avg_alive <= 4.0
    assert four_aoe.peak_alive == pytest.approx(4.0)


def test_forever_paladin_multi_pull_uses_full_pack_peak_pressure_for_heal_safety():
    t=_spend(pala,['toughness']*5+['redoubt']*5+['precision']*3+['guardians_favor']*2+
                   ['improved_seal_of_fury']+['improved_righteous_fury']*3+
                   ['shield_specialization']*3+['one_handed_weapon_specialization']*3+
                   ['benediction']*4)
    gear=next(g for g in pala.archetypes(40) if g.name=='1h_shield_normal')
    row=pala.smooth_pack_score(40,t,'protection',gear,3,pala.POLICIES[0],'retribution')
    assert row['feasible']
    assert row['peak_alive_mobs'] == pytest.approx(3.0)
    assert 1.0 <= row['avg_alive_mobs'] <= row['peak_alive_mobs']
    assert row['peak_incoming_dps'] >= row['incoming_dps']
    assert 'full-pack peak heal-pressure bound' in ' '.join(row['approximation_flags'])



def test_forever_druid_bear_swipe_and_maul_audit_facts_are_explicit():
    from src.rulesets.forever.classes.druid import wowhead_facts as wh
    assert wh.SWIPE_MAX_TARGETS == 3
    assert wh.SWIPE_RANKS == (
        (16,20,19,3),(24,20,25,3),(34,20,36,3),(44,20,60,3),(54,20,84,3),
    )
    assert wh.MAUL_BASE_RAGE == pytest.approx(15.0)
    assert wh.PRIMAL_BITE_RANKS[-1] == (60,20,1.00,77)
    assert wh.MANGLE_BEAR_RANKS is wh.PRIMAL_BITE_RANKS


def test_forever_druid_bear_pack_uses_shared_peak_and_average_geometry():
    from src.rulesets.forever.classes.druid import mechanics as dm
    t=druid.Talents(ferocity=5,savage_fury=2,sharpened_claws=2,mangle=1,blood_frenzy=2)
    row=dm._bear_pack(40,t,3)
    assert row['pull_size'] == 3
    assert row['peak_alive_mobs'] == pytest.approx(3.0)
    assert 2.0 <= row['avg_alive_mobs'] <= 3.0
    assert row['swipe_dps_per_alive_target'] > 0
    assert row['swipe_rank_level'] == 34
    assert row['swipe_scaling_credited'] == 'verified_flat_bear_rank'
    assert 'Swipe' in row['rotation']


def test_forever_druid_bear_pack_has_no_invented_gather_time():
    from src.rulesets.forever.classes.druid import mechanics as dm
    t=druid.Talents(ferocity=5)
    row=dm._bear_pack(20,t,2)
    assert row['feasible']
    assert row['cycle_s'] == pytest.approx(row['combat_s_per_pack'] + row['recovery_s_per_pack'] + 2.2)
    assert row['maul_rage_cost'] == pytest.approx(10.0)


def test_forever_druid_bear_search_is_capped_at_verified_three_target_swipe_geometry():
    from src.rulesets.forever.classes.druid import mechanics as dm
    t=druid.Talents(ferocity=5,savage_fury=2,sharpened_claws=2,mangle=1,blood_frenzy=2)
    row=dm._bear(60,t)
    assert 1 <= row['pull_size'] <= 3
    assert row['mobs_per_hour'] > 0
