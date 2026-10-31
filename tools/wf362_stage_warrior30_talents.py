"""Stage source-observed Warrior L30 talent ranks in isolated canonical SQLite.

Source: talentsforever.com/export/warrior.json (CC BY 4.0), beta client
70291, checked by publisher against 70338. The compact rank vectors below
are transcriptions of the 14 Oct 2026 per-rank readable source, not engine rules.
Unreachable post-L30 ranks retain identity and source row but are not scored.
"""
from __future__ import annotations
import hashlib,json,shutil,sqlite3
from pathlib import Path
from src.game.data.forever.sqlite_talents import _slug
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/forever/catalogue/forever_abilities.sqlite'
TARGET=ROOT/'data/forever/staged_warrior_l30_talents_70338.sqlite'
SOURCE=ROOT/'evidence/wf362/warrior_l30_source_talent_catalogue_70338.json'
SOURCE_URL='https://talentsforever.com/export/warrior.json'
REFERENCE_URL='https://talentsforever.com/warrior/talents'
# name | 1-based row | full rank cap | feature domain | context target | rank values
# Source-backed numeric feature magnitudes are L0 features, NOT s/mob or paid effects.
ROWS={
'arms':[
('Improved Heroic Strike',1,3,'resource_cost_flat','heroic_strike',[1,2,3]),
('Deflection',1,5,'parry_chance_pct','incoming_melee',[1,2,3,4,5]),
('Improved Rend',1,3,'effect_damage_pct','rend',[12,23,35]),
('Improved Charge',2,2,'resource_generation_flat','charge',[3,6]),
('Improved Tactical Mastery',2,5,'stance_retained_rage','stance_change',[3,6,9,12,15]),
('Improved Overpower',2,2,'critical_chance_pct','overpower',[25,50]),
('Anger Management',3,1,'rage_per_3s_combat','rage',[1]),
('Deep Wounds',3,3,'crit_proc_weapon_bleed_pct','melee_critical',[20,40,60]),
('Spearing Strike',4,1,'weapon_damage_pct','spearing_strike',[40]),
('Two-Handed Weapon Specialization',4,3,'two_handed_damage_pct','two_handed_melee',[1,2,3]),
('Impale',4,2,'critical_damage_bonus_pct','abilities',[10,20]),
('Bloodthrill',5,5,'rend_overpower_proc_chance_pct','rend_melee',[4,8,12,16,20]),
('Sweeping Strikes',5,1,'additional_target_attacks','sweeping_strikes',[5]),
('Weaponmaster',5,5,'weapon_conditional_crit_pct','weapon_type',[1,2,3,4,5]),
('Improved Slam',6,2,None,None,None),('Improved Hamstring',6,3,None,None,None),
('Mortal Strike',7,1,None,None,None)],
'fury':[
('Booming Voice',1,5,'shout_rage_cost_reduction_pct','shouts',[5,10,15,20,25]),
('Cruelty',1,5,'melee_crit_chance_pct','melee',[1,2,3,4,5]),
('Lingering Rage',2,5,'out_of_combat_rage_decay_delay_s','rage',[2,4,6,8,10]),
('Unbridled Wrath',2,5,'rage_proc_chance_pct','weapon_melee',[12,24,36,48,60]),
('Furious Precision',3,3,'offhand_hit_chance_pct','offhand',[4,7,10]),
('Piercing Howl',3,1,'movement_slow_pct','enemy_movement',[50]),
('Blood Craze',3,3,'conditional_health_regen_pct','incoming_critical_or_heavy',[1,2,3]),
('Dual Wield Specialization',4,5,'offhand_damage_pct','offhand',[5,10,15,20,25]),
('Raging Blows',4,1,'resource_cost_flat','cleave_whirlwind',[3]),
('Enrage',4,5,'conditional_physical_damage_pct','incoming_hit_proc',[2,4,6,8,10]),
('Improved Execute',4,2,'resource_cost_flat','execute',[3,5]),
('Improved Berserker Rage',5,2,'resource_generation_flat','berserker_rage',[5,10]),
('Death Wish',5,1,'physical_damage_pct','death_wish',[20]),
('Improved Intercept',5,2,'cooldown_reduction_s','intercept',[5,10]),
('Flurry',6,5,None,None,None),('Gore Drinker',6,2,None,None,None),
('Bloodthirst',7,1,None,None,None)],
'protection':[
('Improved Bloodrage',1,2,'rage_generation_pct','bloodrage',[25,50]),
('Shield Specialization',1,5,'block_chance_pct','shield_block',[1,2,3,4,5]),
('Iron Will',1,5,'stun_fear_duration_reduction_pct','incoming_control',[3,6,9,12,15]),
('Anticipation',2,5,'defense_skill_flat','defense',[4,8,12,16,20]),
('Improved Revenge',2,3,'effect_damage_pct','revenge',[20,40,60]),
('Improved Thunder Clap',2,3,'resource_cost_flat','thunder_clap',[2,4,6]),
('Last Stand',3,1,'temporary_max_health_pct','last_stand',[30]),
('Master of Defense',3,2,'shield_dodge_parry_rage_proc_pct','incoming_avoidance',[50,100]),
('Improved Disarm',3,3,'cooldown_reduction_s','disarm',[7,13,20]),
('Defiance',3,3,'shield_defensive_stance_threat_pct','threat',[5,10,15]),
('Improved Sunder Armor',4,3,'resource_cost_flat','sunder_armor',[1,2,3]),
('Vanguard',4,1,'stance_permission_boolean','defensive_charge',[1]),
('Improved Shield Bash',4,2,'silence_proc_chance_pct','shield_bash',[50,100]),
('Improved Shield Wall',5,2,'cooldown_reduction_minutes','shield_wall',[5.5,11]),
('Concussion Blow',5,1,'stun_duration_s','concussion_blow',[5]),
('Focused Rage',5,3,'resource_cost_flat','offensive_abilities',[1,2,3]),
('Bastion',6,5,None,None,None),('Shield Slam',7,1,None,None,None)],
}
PREREQ={'anger_management':('improved_tactical_mastery',5),
'deep_wounds':('improved_rend',3),'impale':('deep_wounds',3),
'mortal_strike':('sweeping_strikes',1),'flurry':('death_wish',1),
'gore_drinker':('enrage',5),'master_of_defense':('shield_specialization',5),
'shield_slam':('concussion_blow',1)}
# The four indexed historical identities are absent from the current client tree.
RETIRED=['toughness','improved_cleave','precision','boundless_rage']
EXTRA={
'booming_voice':('shout_area_increase_pct','shouts',[10,20,30,40,50]),
'shield_specialization':('block_rage_proc_chance_pct','shield_block',[20,40,60,80,100]),
'dual_wield_specialization':('offhand_rage_generation_pct','offhand',[10,20,30,40,50]),
'weaponmaster':('weapon_conditional_armor_ignore_pct','mace_staff',[3,6,9,12,15]),
'enrage':('incoming_hit_proc_chance_pct','incoming_hit',[30]*5),
'death_wish':('incoming_damage_increase_pct','incoming_damage',[5]),
}
MORE_EFFECTS={
    'weaponmaster':[('weapon_conditional_extra_attack_chance_pct','sword',[1,2,3,4,5])],
    'anger_management':[('out_of_combat_rage_loss_reduction_pct','rage',[30])],
    'spearing_strike':[('bonus_weapon_damage_pct_vs_giant_dragonkin_mounted',
                        'conditional_enemy_type',[80])],
    'improved_berserker_rage':[('movement_impair_removal_chance_pct',
                                'berserker_rage',[50,100])],
    'unbridled_wrath':[('rage_amount_per_proc','weapon_melee',[1]*5)],
    'master_of_defense':[('rage_amount_per_proc','incoming_avoidance',[5,5])],
}
CONTEXT_ZERO_SOLO={'sweeping_strikes','piercing_howl','defiance'}
# Source action availability and item type remain conditional, not silently zero.
ACTION_DEPENDENT={'improved_heroic_strike','improved_rend','improved_charge','improved_overpower',
    'improved_revenge','improved_thunder_clap','improved_execute','improved_intercept',
    'improved_shield_bash','improved_shield_wall','improved_disarm','improved_sunder_armor',
    'improved_berserker_rage','raging_blows'}

def create_source():
    catalogue=[];observations=[]
    for tree,entries in ROWS.items():
        for name,row,cap,domain,target,values in entries:
            tid=_slug(name)
            e={'talent_id':tid,'name':name,'tree_key':tree,'row':row-1,
                'max_rank':cap,'source_url':SOURCE_URL,'source_detail_url':REFERENCE_URL}
            if tid in PREREQ:
                pid,prank=PREREQ[tid];e['prerequisite']={'talent_id':pid,'required_rank':prank}
            catalogue.append(e)
            if row>5:continue
            assert values and len(values)==cap
            capture={**e,'effect_domain':domain,'target':target,
                'rank_values':values,
                'condition':('competing_threat_target' if tid in CONTEXT_ZERO_SOLO
                    else 'relevant_ability_learned_and_executable' if tid in ACTION_DEPENDENT
                    else 'context_dependent_source_proxy')}
            if tid in EXTRA:
                ex_domain,ex_target,ex_values=EXTRA[tid]
                capture.update(additional_effect_domain=ex_domain,additional_target=ex_target,
                               additional_rank_values=ex_values)
            if tid in MORE_EFFECTS:
                capture['extra_effects']=[{'effect_domain':d,'target':target,
                    'rank_values':vs,'condition':'source_context_conditional'}
                    for d,target,vs in MORE_EFFECTS[tid]]
            if tid in {'weaponmaster','enrage','blood_craze','last_stand','vanguard'}:
                capture['context_uncertainty']='CONDITIONAL_EFFECT_REQUIRES_COMBAT_OR_GEAR_CONTEXT'
            observations.append(capture)
    assert len(catalogue)==52 and len(observations)==44
    assert len({e['talent_id'] for e in catalogue})==52
    data={'schema':'forever_checkpoint_talent_catalogue_source_v1',
          'class_key':'warrior','source_build':'1.60.1.70338',
          'talent_source_client_build':'1.60.1.70291',
          'talent_checked_against_build':'1.60.1.70338',
          'source_url':SOURCE_URL,'source_detail_url':REFERENCE_URL,
          'source_credit':'Talents Forever, Chris Baldwin, CC BY 4.0',
          'min_level':30,'replace_indexed_catalogue':True,
          'points_per_row':5,'source_tree_id_to_key':{'161':'arms','164':'fury','163':'protection'},
          'retired_indexed_talent_ids':RETIRED,
          'catalogue':catalogue,'observations':observations,
          'observed_unreachable_talent_positions':[],
          'limitations':('Numeric rank vectors are source tooltip features, not 100-mob forecasts. '
             'Weapon, enemy, ability, stance, group and proc context may suppress or change value. '
             'Eight post-level-30 talents have identities but no L30 rank score because unreachable.')}
    SOURCE.parent.mkdir(parents=True,exist_ok=True)
    SOURCE.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
    return data

def stage():
    data=create_source();raw=SOURCE.read_bytes()
    shutil.copyfile(BASE,TARGET)
    with sqlite3.connect(TARGET) as db:
        db.execute('''CREATE TABLE checkpoint_talent_source_catalogue (
            class_key TEXT NOT NULL, source_build TEXT NOT NULL,
            min_level INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
            source_json TEXT NOT NULL,
            PRIMARY KEY(class_key,source_build,min_level))''')
        db.execute('INSERT INTO checkpoint_talent_source_catalogue VALUES(?,?,?,?,?)',(
            data['class_key'],data['source_build'],data['min_level'],
            hashlib.sha256(raw).hexdigest(),raw.decode()))
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    return {'source_sha256':hashlib.sha256(raw).hexdigest(),
            'staged_sqlite_sha256':hashlib.sha256(TARGET.read_bytes()).hexdigest(),
            'catalogue_count':len(data['catalogue']),
            'reachable_rank_curve_families':len(data['observations'])}
if __name__=='__main__':print(json.dumps(stage(),indent=2))
