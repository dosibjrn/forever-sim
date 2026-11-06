"""Clean regression: signed paid scorer observations are not P3 acceptance vetoes."""
from src.game.checkpoint_p3_smoke import fast_p3_smoke
from src.rulesets.forever.items.catalogue import ItemRecord
from tools.wf_gate_p3_live import _p3_executable_weight_witness_axes


def test_legacy_finite_signed_scores_count_with_real_scorer(monkeypatch):
    item = ItemRecord(991105, "Test chest", "chest", item_level=20,
                      required_level=20, stamina=4, intellect=5)
    monkeypatch.setattr(
        "src.game.checkpoint_p3_smoke.available_items",
        lambda *args, **kwargs: (item,))
    report = fast_p3_smoke(
        class_key="mage", level=20,
        weights={"stamina": -0.25, "intellect": 0.0},
        weight_evidence_kind="MEASURED_SOURCE_CONTEXT",
        weapon_damage_dependent=False)
    assert report["blockers"] == []
    assert report["p3_pass"] is True
    assert report["tested_stat_assertions"] == 2
    assert report["verified_stat_assertions"] == 2
    scored = report["slots"]["chest"]["items"][0]
    assert scored["score"] == -1.0
    assert scored["contributions"] == {"intellect": 0.0, "stamina": -1.0}


def test_measured_zero_or_negative_never_triggers_extra_positive_witness():
    assert _p3_executable_weight_witness_axes(
        ["NONPOSITIVE_RELEVANT_WEIGHT:intellect",
         "NEGATIVE_WEIGHT:stamina", "MISSING_WEIGHT:spirit"],
        {"intellect": 0.0, "stamina": -0.4},
        ("intellect", "stamina", "spirit"),
        ("intellect", "spirit", "stamina")) == ["spirit"]
