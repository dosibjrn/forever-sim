from src.rulesets.forever.fidelity import PRODUCTION_CLASSES, inventory_report, issues_for, validate_inventory


def test_fidelity_inventory_is_structurally_valid_and_covers_every_production_class():
    assert validate_inventory() == []
    report = inventory_report()
    assert report["ok"] is True
    assert tuple(report["classes"]) == PRODUCTION_CLASSES
    assert all(issues_for(class_key) for class_key in PRODUCTION_CLASSES)


def test_known_material_gaps_cannot_silently_disappear():
    ids = {row.issue_id for class_key in PRODUCTION_CLASSES for row in issues_for(class_key)}
    assert "mage.blizzard_aoe_leveling" in ids
    assert "paladin.seal_of_fury_absorb_replacement" in ids
    assert "druid.incoming_damage_rage" in ids


def test_every_high_or_medium_gap_has_an_explicit_resolution_path():
    rows = [row for class_key in PRODUCTION_CLASSES for row in issues_for(class_key)]
    assert all(row.resolution.strip() for row in rows if row.severity in {"high", "medium"})


def test_registry_fidelity_exposes_inventory_to_decision_artifact_consumers():
    from src.class_registry import get_definition
    for class_key in PRODUCTION_CLASSES:
        fidelity = get_definition("forever", class_key).fidelity()
        assert fidelity["open_issue_count"] == len(issues_for(class_key))
        assert {x["issue_id"] for x in fidelity["open_issues"]} == {x.issue_id for x in issues_for(class_key)}
    assert "open_issues" not in get_definition("forever", "warrior").fidelity()


def test_bear_swipe_hidden_scaling_gap_is_closed_by_forever_rank_pages():
    ids = {row.issue_id for row in issues_for("druid")}
    assert "druid.swipe_hidden_scaling" not in ids
