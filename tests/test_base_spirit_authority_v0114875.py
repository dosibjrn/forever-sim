import pytest

from src.rulesets.forever.shared.base_stats import (
    BASE_STAT_AUTHORITY_ID,
    base_spirit,
    spirit_provenance,
)


def test_l20_target_race_base_spirit_is_pinned_and_separate_from_gear():
    assert base_spirit("druid", 1, race="tauren") == 22
    assert base_spirit("druid", 20, race="tauren") == 37
    assert base_spirit("paladin", 1, race="undead") == 21
    assert base_spirit("paladin", 20, race="undead") == 34
    assert spirit_provenance("druid",20,race="tauren")["authority_id"] == BASE_STAT_AUTHORITY_ID
    assert spirit_provenance("paladin",20,race="undead")["authority_id"] == BASE_STAT_AUTHORITY_ID


def test_paladin_recovery_uses_base_plus_item_spirit_through_shared_solver():
    from src.rulesets.forever.classes.paladin import mechanics as pm
    heal={"heal":0.0,"mana":0.0,"cast":0.0,"name":"none"}
    base=pm._recovery(20,0.0,500.0,1000.0,heal,spirit_bonus=0.0,mp5_bonus=0.0)
    plus=pm._recovery(20,0.0,500.0,1000.0,heal,spirit_bonus=10.0,mp5_bonus=0.0)
    d0=base[2]; d1=plus[2]
    assert d0["base_spirit"] == 34.0
    assert d0["item_spirit"] == 0.0
    assert d0["total_spirit"] == 34.0
    assert d0["base_mana_regen_per_s"] == pytest.approx(7.5)
    assert d0["passive_mana_regen_per_s"] == pytest.approx(10.9)
    assert d1["total_spirit"] == 44.0
    assert d1["passive_mana_regen_per_s"] == pytest.approx(11.9)
    assert plus[0] < base[0]


def test_druid_recovery_uses_base_plus_item_spirit_and_spirit_mutation_reaches_score():
    from src.rulesets.forever.classes.druid import mechanics as dm
    from src.rulesets.forever.classes.druid.talents import Talents
    low=dm._druid_mana_regen_decomposition(20,{"spirit":0.0,"mp5":0.0})
    high=dm._druid_mana_regen_decomposition(20,{"spirit":10.0,"mp5":0.0})
    assert low["base_spirit"] == 37.0
    assert low["passive_mana_regen_per_s"] == pytest.approx(11.2)
    assert high["passive_mana_regen_per_s"] == pytest.approx(12.2)

    t=Talents(improved_wrath=5,moonglow=2,improved_moonfire=2,natures_majesty=2)
    row=dm.experimental_level_score(20,t,"balance")
    weights=dm.marginal_stat_weights(20,t,"balance",row)
    assert row["base_stat_authority_id"] == BASE_STAT_AUTHORITY_ID
    assert row["base_spirit"] == 37.0
    assert weights["stats"]["spirit"]["seconds_saved_per_100_per_point"] > 0


def test_paladin_production_score_publishes_base_spirit_decomposition():
    from src.rulesets.forever.classes.paladin import mechanics as pm
    from src.rulesets.forever.classes.paladin.talents import Talents
    t=Talents(deflection=3,benediction=4,improved_judgement=2,holy_conduit=1,seal_of_command=1)
    row=pm.experimental_level_score(20,t,"retribution")
    assert row["base_stat_authority_id"] == BASE_STAT_AUTHORITY_ID
    assert row["base_spirit"] == 34.0
    assert row["total_spirit"] == pytest.approx(row["base_spirit"] + row["item_spirit"])
    assert row["passive_mana_regen_per_s"] == pytest.approx(
        row["base_mana_regen_per_s"] + row["spirit_recovery_mps"] + row["mp5_recovery_mps"]
    )
