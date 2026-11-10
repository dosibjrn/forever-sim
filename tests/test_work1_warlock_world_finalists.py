"""Work1: actual 100-mob finalist budget is not swallowed by one paid-DPS filler.

These test only Forever's candidate selection over native-paid score receipts;
neither Warcraft mechanics nor any substitute combat model is evaluated.
"""
from tools.wf_warlock_native_optimizer import select_world_finalists


def _paid(talents, tree, apl, dps):
    return {"talents": talents, "talent_label": tree, "apl_label": apl,
            "dps_screen": dps, "apl": [{"action": {"spell": {"spellId": 1}}}]}


def test_paid_finalist_budget_preserves_saved_build_and_sustain_diversity():
    scored = [
        _paid("a0", "tree_Affliction_0", "dots_corruption__drain_life", 120),
        _paid("a1", "tree_Affliction_1", "dots_agony__drain_life", 119),
        _paid("a2", "tree_Affliction_2", "dots_immolate__drain_life", 118),
        _paid("a3", "tree_Affliction_3", "dots_corruption__drain_life", 117),
        _paid("d0", "tree_Demonology_0", "dots_corruption__shoot", 95),
        _paid("x0", "tree_Destruction_0", "dots_agony__searing_pain", 94),
        _paid("x1", "tree_Destruction_1", "dots_immolate__shadow_bolt", 93),
        _paid("a4", "tree_Affliction_4", "dots_corruption__drain_life_tap10", 92),
        _paid("saved", "saved_rust_paid_build", "saved_multi_spell", 70),
    ]

    picked = select_world_finalists(scored, "saved", 6)

    assert len(picked) == 6
    assert picked[0]["talents"] == "saved"  # Actual prior paid lineage survives
    labels = {row["apl_label"] for row in picked}
    assert any("__drain_life" in label for label in labels)
    assert any("__shoot" in label for label in labels)
    assert any("__searing_pain" in label for label in labels)
    assert any("__shadow_bolt" in label for label in labels)
    assert any("_tap10" in label for label in labels)
    assert len({(row["talents"], row["apl_label"]) for row in picked}) == 6
    assert {row["talent_label"] for row in picked} >= {
        "tree_Demonology_0", "tree_Destruction_0",
    }


def test_paid_finalist_budget_is_resumable_without_duplicating_candidates():
    scored = [
        _paid("same", "tree_Affliction_0", "dots__drain_life", 88),
        _paid("same", "tree_Affliction_0", "dots__drain_life", 88),
        _paid("other", "tree_Demonology_0", "dots__shoot", 70),
        _paid("saved", "saved_rust_paid_build", "saved_multi_spell", 50),
    ]
    assert select_world_finalists(scored, "saved", 1)[0]["talents"] == "saved"
    assert len(select_world_finalists(scored, "saved", 10)) == 3
    assert select_world_finalists(scored, "saved", 0) == []
