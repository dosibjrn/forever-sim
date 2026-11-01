from src.rulesets.forever.classes import druid
from src.rulesets.forever.classes.druid import mechanics as dm
from src.rulesets.forever.classes.druid import wowhead_facts as wh
from src.rulesets.forever.fidelity import issues_for


def test_current_build_has_no_cat_mangle_proxy():
    t = druid.Talents(ferocity=5, savage_fury=2, sharpened_claws=2, mangle=1)
    row = druid.experimental_level_score(40, t, "feral")
    assert row["profile"] == "cat"
    assert row["feral_builder"] == "Claw"
    assert "Mangle" not in row["rotation"]
    assert all("Mangle" not in flag for flag in row["approximation_flags"])


def test_primal_bite_is_bear_only_current_spell_family():
    assert wh.PRIMAL_BITE_PUBLIC_FACT["cat_mangle_current_build_status"] == "removed"
    assert wh.PRIMAL_BITE_PUBLIC_FACT["forms"] == ("bear", "dire_bear")
    t = druid.Talents(ferocity=5, savage_fury=2, sharpened_claws=2, mangle=1)
    row = dm._bear_pack(40, t, 1)
    assert "Primal Bite on CD" in row["rotation"]
    assert row["primal_bite_rank_level"] == 36
    assert row["primal_bite_flat_damage"] == 38
    # old detail keys remain only as compatibility aliases
    assert row["mangle_rank_level"] == row["primal_bite_rank_level"]


def test_cat_mangle_fidelity_gap_is_closed_not_renamed():
    ids = {row.issue_id for row in issues_for("druid")}
    assert "druid.cat_mangle_incomplete_row" not in ids
