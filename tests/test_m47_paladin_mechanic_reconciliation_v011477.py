import pytest


def test_paladin_outgoing_scheduler_keeps_autos_running_during_active_gcd():
    from src.rulesets.forever.classes.paladin.mechanics import _discrete_damage_kill_s
    cadence={
        'pull_size':1,'hp_per_mob':80.0,
        'auto_first':2.0,'auto_period':2.0,'auto_damage':40.0,
        'consecration_period':8.0,'consecration_tick_damage':0.01,
        'consecration_min_mobs':1,'seal_duration_s':30.0,'gcd_s':1.5,
    }
    # Seal GCD 0-1.5 and Consecration GCD 1.5-3.0 must not delay the t=2 auto.
    got=_discrete_damage_kill_s(80.0,1.0,1.0,cadence)
    assert got == pytest.approx(4.0)


def test_paladin_consecration_is_eight_timed_ticks_not_cast_time_packet():
    from src.rulesets.forever.classes.paladin.mechanics import _discrete_damage_kill_s
    cadence={
        'pull_size':1,'hp_per_mob':100.0,
        'consecration_period':8.0,'consecration_tick_damage':15.0,
        'consecration_min_mobs':1,'seal_duration_s':30.0,'gcd_s':1.5,
    }
    # Consecration is cast at 1.5; 7th 15-damage tick kills at 8.5.
    got=_discrete_damage_kill_s(100.0,1.0,1.0,cadence)
    assert got == pytest.approx(8.5)


def test_event_validation_rehydrates_named_body_items(monkeypatch):
    from src.rulesets.forever.classes.paladin import event_replay
    captured={}
    def fake_replay(level,talents,profile,gear,pull_size,policy,aura,plan,**kwargs):
        captured['gear']=gear
        return {'complete':True,'kill_s':1.0,'player_hp_end':1.0,'mana_end':1.0,
                'heal_casts_requested':0,'heal_casts_completed':0,'emergency_actions_used':[],
                'fury_breaks':0,'shield_spec_procs':0}
    monkeypatch.setattr(event_replay,'replay_pack',fake_replay)
    from src.rulesets.forever.classes.paladin.talents import Talents
    # Use a real archetype plus a real named body-item reroll.
    from src.rulesets.forever.classes.paladin.gear import archetypes, gear_snapshot, apply_body_item_names
    base=archetypes(20)[0]
    rerolled=apply_body_item_names(base,20,("Crusader's Chain Belt",),selection_method='test',selection_weights={})
    snap=gear_snapshot(rerolled)
    names=tuple(snap.get('selected_body_items') or ())
    row={'gear':base.name,'gear_stats':snap,'policy':'balanced','mana_plan':'full','profile':'retribution','pull_size':1,'aura':'devotion'}
    event_replay.validate_smooth_row(20,Talents(),row)
    assert tuple(captured['gear'].selected_body_items)==names
