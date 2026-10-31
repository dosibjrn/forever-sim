from src.rulesets.forever.classes.druid.reference_builds import reference_build_snapshot
from src.v2.reference_builds import reference_build_snapshot as load_reference_builds
from src.listener import DECISIONS_HTML


def test_talentsforever_druid_reference_snapshot_is_source_honest():
    snap = reference_build_snapshot()
    assert snap["requested_per_build_type"] == 3
    assert snap["groups"]["feral"]["available"] == 3
    assert snap["groups"]["feral"]["coverage_complete"] is True
    assert snap["groups"]["balance"]["available"] == 1
    assert snap["groups"]["restoration"]["available"] == 1
    assert snap["groups"]["balance"]["coverage_complete"] is False
    assert snap["groups"]["restoration"]["coverage_complete"] is False
    assert [x["overall_rank"] for x in snap["builds"]] == [1, 2, 3, 4, 5]


def test_supplied_balance_reference_has_exact_machine_readable_ranks():
    snap = reference_build_snapshot()
    ref = next(x for x in snap["builds"] if x["id"] == "tf-druid-balance-36-0-15")
    assert ref["allocation_detail_status"] == "exact"
    assert sum(ref["talent_ranks"].values()) == 51
    assert ref["tree_points"] == {"balance": 36, "feral": 0, "restoration": 15}
    assert ref["talent_ranks"]["moonkin_form"] == 1
    assert ref["talent_ranks"]["reflection"] == 3


def test_generic_reference_loader_has_no_druid_branch_contract():
    snap = load_reference_builds("druid")
    assert snap["class"] == "druid"
    assert snap["source"]["provider"] == "Talents Forever"


def test_listener_exposes_explicit_reference_comparison_ui():
    html = DECISIONS_HTML
    assert 'id="referencePanel"' in html
    assert 'id="referencePick"' in html
    assert 'function renderReferenceCompare()' in html
    assert 'reference_builds' in html
    assert 'Exact talent delta' in html
