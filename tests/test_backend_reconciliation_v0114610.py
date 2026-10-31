from tools.report_backend_reconciliation import build_report


def test_backend_reconciliation_distinguishes_classic_mc_from_forever_equivalent_gate():
    report = build_report()
    assert report["release"]["existing_release_mc_scope"] == "classic_mage_only"
    assert report["release"]["forever_release_validation"] == "production_decision_equivalent_gate"
    assert report["release"]["status"] == "forever_equivalent_gate_passed"
    assert report["release"]["forever_release_gate"]["ok"] is True
    assert "forever_release_mc_or_equivalent_gate_missing" not in report["blocking_items"]


def test_mage_fast_event_differences_are_explicitly_classified():
    report = build_report()
    assert report["mage"]["levels"]
    for row in report["mage"]["levels"]:
        assert row["shared_candidate_count"] > 0
        if not row["exact_top_match"]:
            assert row["explanations"] or row["unexplained_material_difference"]
    assert not report["mage"]["unexplained_levels"]


def test_druid_has_independent_equivalent_validation_path():
    report = build_report()
    assert report["druid"]["status"] == "independently_checked"
    assert report["druid"]["reference"]["ok"] is True
    assert "druid_independent_backend_validation_missing" not in report["blocking_items"]
    assert "forever_release_mc_or_equivalent_gate_missing" not in report["blocking_items"]
    assert report["release"]["status"] == "forever_equivalent_gate_passed"
    assert report["ready_for_m46_done"] is True


def test_review_handoff_fidelity_reclassifications_are_machine_readable():
    from src.rulesets.forever.fidelity import issues_for
    mage = {x.issue_id: x for x in issues_for("mage")}
    druid = {x.issue_id: x for x in issues_for("druid")}
    assert mage["mage.blizzard_aoe_leveling"].severity != "high"
    assert mage["mage.ice_lance_spell_power_coefficient"].severity == "low"
    assert druid["druid.incoming_damage_rage"].severity == "low"
