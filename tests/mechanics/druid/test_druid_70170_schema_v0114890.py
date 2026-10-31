import pytest

from src.rulesets.forever.classes.druid import mechanics
from src.rulesets.forever.classes.druid import wowhead_facts as wh
from src.rulesets.forever.classes.druid.reference_builds import reference_build_snapshot
from src.rulesets.forever.classes.druid.talents import (
    TALENT_RULES, TALENT_SCHEMA_BUILD, Talents, add_point,
    allocation_schema_errors, expected_points_for_level, final_allocation,
    legal_add, level_points_complete, tree_points, validate_current_schema,
)


def _add_many(t, name, count):
    for _ in range(count):
        assert legal_add(t, name), (name, final_allocation(t))
        t = add_point(t, name)
    return t


def _balance_reference_prefix(level: int) -> Talents:
    # Source-backed leveling order supplied by TalentsForever for the exact
    # 36/0/15 Balance reference. Prefixes through L40 are enough for I02's
    # current-schema/point-budget contract.
    order = [
        *("improved_wrath" for _ in range(5)),
        *("moonglow" for _ in range(3)),
        *("improved_moonfire" for _ in range(2)),
        *("natures_majesty" for _ in range(2)),
        *("natures_reach" for _ in range(2)),
        "natures_splendor", "insect_swarm",
        *("vengeance" for _ in range(5)),
        *("improved_starfire" for _ in range(5)),
        "natures_grace",
        *("eclipse" for _ in range(3)),
        "moonfury",
    ]
    t = Talents()
    for name in order[: expected_points_for_level(level)]:
        assert legal_add(t, name), (level, name, final_allocation(t))
        t = add_point(t, name)
    return t


def test_70170_feral_tree_shape_and_removed_king_of_the_jungle():
    assert TALENT_SCHEMA_BUILD == "1.60.1.70170"
    assert sum(1 for v in TALENT_RULES.values() if v[0] == "feral") == 20
    assert "king_of_the_jungle" not in TALENT_RULES
    assert TALENT_RULES["shredding_attacks"] == ("feral", 3, 10, None)
    assert TALENT_RULES["shifting_power"] == ("feral", 1, 15, ("shredding_attacks", 3))
    assert TALENT_RULES["improved_shifting_power"] == ("feral", 2, 20, ("shifting_power", 1))


def test_current_balance_reference_prefix_spends_every_point_at_l30_and_l40():
    l30 = _balance_reference_prefix(30)
    l40 = _balance_reference_prefix(40)
    assert l30.points() == 21 and level_points_complete(30, l30)
    assert l40.points() == 31 and level_points_complete(40, l40)
    assert tree_points(l30, "balance") == 21
    assert tree_points(l40, "balance") == 31
    assert not allocation_schema_errors(l30)
    assert not allocation_schema_errors(l40)


def test_shifting_power_legality_and_improved_cooldown_chain():
    t = Talents()
    t = _add_many(t, "ferocity", 5)
    t = _add_many(t, "heart_of_the_wild", 5)
    t = _add_many(t, "shredding_attacks", 3)
    t = _add_many(t, "savage_fury", 2)
    assert t.points() == 15
    assert legal_add(t, "shifting_power")
    t = add_point(t, "shifting_power")
    # Need four more points in the tree before the 20-point row opens.
    t = _add_many(t, "predatory_strikes", 3)
    t = _add_many(t, "feral_charge", 1)
    assert t.points() == 20
    assert legal_add(t, "improved_shifting_power")
    t1 = add_point(t, "improved_shifting_power")
    t2 = add_point(t1, "improved_shifting_power")
    r0 = mechanics._cat_single(30, t)
    r1 = mechanics._cat_single(30, t1)
    r2 = mechanics._cat_single(30, t2)
    assert r0["shifting_power_cooldown_s"] == pytest.approx(16.0)
    assert r1["shifting_power_cooldown_s"] == pytest.approx(12.0)
    assert r2["shifting_power_cooldown_s"] == pytest.approx(8.0)
    assert r0["shifting_power_energy_per_s_ev"] > 0.0
    assert r2["energy_regen_per_s"] >= r1["energy_regen_per_s"] >= r0["energy_regen_per_s"]
    assert "Shifting Power on sustainable CD" in r2["rotation"]
    assert "Tiger's Fury" not in r2["rotation"]
    assert r2["tigers_fury_status"] == "removed_in_1.60.1.70170"
    assert wh.SHIFTING_POWER_ENERGY == pytest.approx(40.0)


def test_old_king_of_the_jungle_input_is_rejected_not_silently_translated():
    old = Talents(king_of_the_jungle=3)
    with pytest.raises(ValueError, match="king_of_the_jungle_removed"):
        validate_current_schema(old)
    with pytest.raises(ValueError, match="king_of_the_jungle_removed"):
        mechanics.experimental_level_score(30, old, "feral")


def test_exact_talentsforever_balance_reference_is_current_schema_valid():
    snap = reference_build_snapshot()
    ref = next(x for x in snap["builds"] if x["id"] == "tf-druid-balance-36-0-15")
    v = ref["runtime_schema_validation"]
    assert v["ok"] is True
    assert v["schema_build"] == "1.60.1.70170"
    assert v["points"] == 51
    assert v["tree_points"] == {"balance": 36, "feral": 0, "restoration": 15}


def test_listener_contract_rejects_partial_l30_druid_route_state():
    from src.v2.decision_dashboard import _talent_point_contract

    partial = {
        "level": 30,
        "talent_ranks": {
            "improved_wrath": 5,
            "genesis": 3,
            "moonglow": 1,
            "improved_moonfire": 2,
            "natures_majesty": 2,
        },
    }
    pc = _talent_point_contract("druid", partial)
    assert pc == {"ok": False, "expected": 21, "recognized": 13, "unknown": []}

    full = _balance_reference_prefix(30)
    pc2 = _talent_point_contract("druid", {
        "level": 30,
        "talent_ranks": {k: int(getattr(full, k)) for k in TALENT_RULES if int(getattr(full, k)) > 0},
    })
    assert pc2["ok"] is True
    assert pc2["recognized"] == 21
