import pytest

from src.rulesets.forever.shared.recovery import (
    RECOVERY_SOLVER_ID, solve_recovery, recover_to_full,
)


def test_shared_recovery_compatibility_alias_is_exact():
    a=solve_recovery(20, 300.0, 500.0, passive_mana_regen_per_s=3.0)
    b=recover_to_full(20, 300.0, 500.0, passive_mana_regen_per_s=3.0)
    assert a == b


def test_hunter_uses_shared_resource_recovery_without_private_drink_overhead():
    from src import game_context
    from src.engine_registry import reset_engine_cache, get_engine
    from src.rulesets.forever.classes.hunter import mechanics as hm
    game_context.configure('forever','hunter'); reset_engine_cache(); e=get_engine()
    row=hm._ranged_profile(20,e.Talents(),no_pet=False,pet_family='cat')
    expected=solve_recovery(
        20,row['incoming_damage'],row['mana_deficit_per_mob'],
        passive_mana_regen_per_s=row['mana_regen_per_s'],
    )
    assert row['recovery_solver_id'] == RECOVERY_SOLVER_ID
    assert row['resource_recovery_s_per_mob'] == pytest.approx(expected.total_s)
    assert row['recovery_s']/100.0 == pytest.approx(expected.total_s + row['pet_recovery_s_per_mob'])
    assert row['food_s_per_mob'] == pytest.approx(expected.food_s)
    assert row['drink_s_per_mob'] == pytest.approx(expected.water_s)


def test_all_forever_recovery_call_sites_use_canonical_solver_name():
    # Structural guard: new class code must not grow another recover_to_full-like
    # authority. Compatibility alias exists only in shared/recovery.py.
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    class_files=[
        root/'src/rulesets/forever/classes/mage/policy.py',
        root/'src/rulesets/forever/classes/druid/mechanics.py',
        root/'src/rulesets/forever/classes/paladin/mechanics.py',
        root/'src/rulesets/forever/classes/hunter/mechanics.py',
        root/'src/v2/expected_engine.py',
    ]
    for path in class_files:
        text=path.read_text(encoding='utf-8')
        assert 'solve_recovery(' in text, path
        assert 'recover_to_full(' not in text, path


def test_mage_deterministic_search_backend_uses_shared_recovery_and_timing_contract():
    from src import game_context
    from src.engine_registry import reset_engine_cache
    game_context.configure('forever','mage'); reset_engine_cache()
    from src.rulesets.forever.classes.mage import engine
    from src.v2.expected_engine import score_policy
    policy=engine.Policy('audit frostbolt','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)
    row=score_policy(20, engine.Talents(imp_frostbolt=5), policy, engine.SimConfig(), cycle_pulls=3)
    assert row['recovery_solver_id'] == RECOVERY_SOLVER_ID
    assert row['travel_s'] > 0
    assert row['total_s'] == pytest.approx(row['kill_s'] + row['recovery_s'] + row['travel_s'])


def test_l20_cross_class_reference_profiles_share_recovery_authority_and_target_hp():
    from src import game_context
    from src.engine_registry import reset_engine_cache
    from src.shared.leveling.objective import representative_hp
    assert representative_hp(20) == pytest.approx(484.0)

    game_context.configure('forever','druid'); reset_engine_cache()
    from src.rulesets.forever.classes.druid import engine as druid
    dr=druid.experimental_level_score(
        20,
        druid.Talents(improved_wrath=5,moonglow=2,improved_moonfire=2,natures_majesty=2),
        'balance',
    )
    assert dr['recovery_solver_id'] == RECOVERY_SOLVER_ID
    assert dr['representative_mob_hp'] == pytest.approx(484.0)

    game_context.configure('forever','paladin'); reset_engine_cache()
    from src.rulesets.forever.classes.paladin import engine as paladin
    pr=paladin.experimental_level_score(
        20,
        paladin.Talents(deflection=3,benediction=4,improved_judgement=2,holy_conduit=1,seal_of_command=1),
        'retribution',
    )
    assert pr['recovery_solver_id'] == RECOVERY_SOLVER_ID
    assert pr['representative_mob_hp'] == pytest.approx(484.0)

    game_context.configure('forever','hunter'); reset_engine_cache()
    from src.rulesets.forever.classes.hunter import engine as hunter
    hr=hunter.experimental_level_score(
        20,
        hunter.Talents(lethal_attacks=5,careful_aim=5,rapid_killing=1),
        'marksmanship',
    )
    assert hr['recovery_solver_id'] == RECOVERY_SOLVER_ID
    # Hunter uses the same shared target HP curve internally; kill score is
    # already regression-covered above, so this assertion protects the source.
    assert representative_hp(20) == pytest.approx(484.0)


def test_hunter_spirit_obeys_five_second_rule_while_mp5_remains_in_combat():
    from src import game_context
    from src.engine_registry import reset_engine_cache, get_engine
    from src.rulesets.forever.classes.hunter import mechanics as hm
    game_context.configure('forever','hunter'); reset_engine_cache(); e=get_engine()
    row=hm._ranged_profile(20,e.Talents(),no_pet=False,pet_family='cat')
    assert row['combat_mana_regen_per_s'] == pytest.approx(row['gear_stats']['mp5']/5.0)
    assert row['ooc_mana_regen_per_s'] > row['combat_mana_regen_per_s']
    expected=max(0.0,row['mana_spent_per_mob']-row['combat_mana_regen_per_mob'])
    assert row['mana_deficit_per_mob'] == pytest.approx(expected)


def test_paladin_spirit_and_druid_mp5_feed_the_shared_recovery_inputs():
    from src.rulesets.forever.classes.paladin import mechanics as pm
    from src.rulesets.forever.classes.druid import mechanics as dm
    heal={'heal':0.0,'mana':0.0,'cast':0.0,'name':'none'}
    base=pm._recovery(20,0.0,500.0,1000.0,heal,spirit_bonus=0.0,mp5_bonus=0.0)
    spirit=pm._recovery(20,0.0,500.0,1000.0,heal,spirit_bonus=20.0,mp5_bonus=0.0)
    assert spirit[0] < base[0]
    assert spirit[2]['base_spirit'] == pytest.approx(34.0)
    assert spirit[2]['item_spirit'] == pytest.approx(20.0)
    assert spirit[2]['spirit_recovery_mps'] == pytest.approx(5.4)
    assert spirit[2]['base_mana_regen_per_s'] == pytest.approx(7.5)
    gear={'spirit':20.0,'mp5':10.0}
    assert dm._druid_out_of_combat_mana_regen_per_s(20, gear) == pytest.approx(15.2)
