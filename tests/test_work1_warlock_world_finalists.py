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


def test_native_paid_gear_uses_prepared_stats_mana_not_missing_mana_object(
        monkeypatch, tmp_path):
    """Forward actual native prepared scalars; no Python gameplay model.

    A valid Rust response stores max mana in player.stats.Mana. Gear DPS
    ties must reach the existing native-health/armor/mana tie-break rather
    than rejecting both paid requests as missing player.mana.max.
    """
    import json
    from pathlib import Path
    from tools import wf_warlock_native_optimizer as optimizer

    def native_response(command, *, seconds=45):
        command = list(map(str, command))
        outfile = Path(command[command.index("--outfile") + 1])
        if "prepare" in command:
            request = json.loads(
                Path(command[command.index("--request") + 1]).read_text())
            item_id = optimizer.actor(request)["equipment"]["items"][0]["id"]
            outfile.write_text(json.dumps({"player": {
                "class": "ClassWarlock", "level": 55,
                "stats": {"Health": 700 + (20 if item_id == 901 else 0),
                          "Mana": 1200, "Armor": 110}}}))
        elif "sim" in command:
            outfile.write_text(json.dumps({"result": {
                "raidMetrics": {"parties": [{"players": [
                    {"dps": {"avg": 100.0}}]}]}}}))
        else:
            raise AssertionError(command)
        return ""

    monkeypatch.setattr(optimizer, "call", native_response)
    source = {"raid": {"parties": [{"players": [{"equipment": {"items": []}}]}]}}
    options = {"items": [{
        "item_id": 901, "eligibility": "native_eligible",
        "native": {"item_id": 901, "slot": "head", "item_level": 57,
                   "name": "Native head slot", "required_level": 55}}]}

    equipped, audit = optimizer.native_level_equipment(
        Path("native-binary"), source, options, tmp_path, level=55)

    assert optimizer.actor(equipped)["equipment"]["items"][0]["id"] == 901
    assert audit["native_paid_requests"] == 2
    assert audit["evaluated_equipment_requests"] == 2
    assert audit["native_refusal_samples"] == []
    assert audit["native_paid_initial_gear_dps"] == 100.0
    assert json.loads((tmp_path / "native_gear.json").read_text())["equipped"][0]["item_id"] == 901
