"""P1 generic runner contracts backed by actual sourced L20 Druid runtime."""
from pathlib import Path
import pytest

from tools.p1_ability_inventory import source_inventory
from tools.wf_p1_toy_ablation import run_gsim

ROOT = Path(__file__).resolve().parents[1]


def test_checkpoint_identity_not_hardcoded_to_druid_feral():
    baseline = run_gsim(ROOT, class_key="druid", level=20, spec="feral-cat")
    other_spec = run_gsim(ROOT, class_key="druid", level=20, spec="balance")
    assert baseline["spec"] == "feral-cat" and other_spec["spec"] == "balance"
    assert {r["spell_id"] for r in baseline["results"]} == {
        r["spell_id"] for r in other_spec["results"]
    }
    assert baseline["checked"] == other_spec["checked"]
    assert baseline["observed"] == other_spec["observed"]
    assert baseline["observed"] > 0
    assert baseline["effect_probe_progress_naksut"] == 9
    assert baseline["effect_probe_progress_max_before_full_gate"] == 9
    assert baseline["hybrid_rust_executed"] is False
    assert other_spec["p1_certified"] is False
    assert other_spec["spec_ability_scope"].endswith("no_fixed_talent_allocation")


def test_all_nonrelevant_not_counted_in_numerator_or_denominator():
    result = run_gsim(ROOT, class_key="druid", level=20, spec="feral-cat")
    excluded = {x["spell_id"] for x in result["not_relevant"]}
    measured = {x["spell_id"] for x in result["results"]}
    assert excluded.isdisjoint(measured)
    assert result["not_relevant_count"] == len(excluded) == 7
    assert result["checked"] == len(measured)
    assert result["observed"] == sum(x["status"] == "EFFECT_OBSERVED" for x in result["results"])


def test_inventory_unknown_class_fails_not_empty_green():
    with pytest.raises(ValueError, match="UNKNOWN_CLASS"):
        source_inventory(ROOT, "made_up_class", 20)


def test_inventory_unknown_level_fails_not_empty_green():
    with pytest.raises(ValueError, match="LEVEL_OUT_OF_RANGE"):
        source_inventory(ROOT, "druid", 99)


def test_mage_l20_frost_nova_source_area_control_uses_same_real_runtime():
    report = run_gsim(ROOT, class_key="mage", level=20, spec="frost")
    source = [x for x in report["results"] if x["name"] == "Frost Nova"]
    assert len(source) == 1
    assert source[0]["status"] == "EFFECT_OBSERVED", source
    assert report["p1_certified"] is False


def test_warrior_l20_uses_same_source_derived_runner_without_class_branches():
    report = run_gsim(ROOT, class_key="warrior", level=20, spec="arms")
    assert report["checked"] > 0
    assert report["observed"] > 0
    assert report["class"] == "warrior"
    assert report["hybrid_rust_executed"] is False


def test_druid_l60_source_unknowns_are_reported_not_silently_removed():
    report = run_gsim(ROOT, class_key="druid", level=60, spec="feral-cat")
    assert report["level"] == 60
    assert report["checked"] >= report["observed"] > 0
    assert report["source_acquisition_unresolved_count"] > 0
    assert report["p1_certified"] is False
