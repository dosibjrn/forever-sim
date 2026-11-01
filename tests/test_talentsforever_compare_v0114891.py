import pytest

from src.rulesets.forever.classes.druid import engine
from src.rulesets.forever.classes.druid.talents import (
    Talents, TALENT_RULES, add_point, expected_points_for_level, final_allocation,
    legal_add, tree_points,
)
from src.v2.class_model import Evaluation
from src.v2.talentsforever_compare import (
    TalentsForeverBuildError, TalentsForeverComparisonUnavailable,
    _allocation_at_level, compare_to_talentsforever_build,
    parse_talentsforever_url,
)
from src.listener import DECISIONS_HTML


KNOWN_URL = "https://talentsforever.com/druid/60/5032220115501351--505203-6"


def _reference_prefix(level: int) -> Talents:
    order = [
        *(["improved_wrath"] * 5), *(["moonglow"] * 3),
        *(["improved_moonfire"] * 2), *(["natures_majesty"] * 2),
        *(["natures_reach"] * 2), "natures_splendor", "insect_swarm",
        *(["vengeance"] * 5), *(["improved_starfire"] * 5),
        "natures_grace", *(["eclipse"] * 3), *(["moonfury"] * 5),
        "moonkin_form", *(["natures_focus"] * 5), *(["naturalist"] * 5),
        *(["subtlety"] * 2), *(["reflection"] * 3),
    ]
    t = Talents()
    for name in order[: expected_points_for_level(level)]:
        assert legal_add(t, name), (level, name, final_allocation(t))
        t = add_point(t, name)
    return t


def _ranks(t: Talents):
    return {name: int(getattr(t, name)) for name in TALENT_RULES if int(getattr(t, name)) > 0}


def _optimizer_row(level: int = 30):
    t = _reference_prefix(level)
    raw = dict(engine.experimental_level_score(level, t, "balance"))
    raw["stat_weights"] = engine.marginal_stat_weights(level, t, "balance", baseline=raw)
    ev = Evaluation.from_raw(raw)
    row = {**raw, **ev.published_fields()}
    row.update({
        "level": level,
        "talent_ranks": _ranks(t),
        "tree_points": {tree: tree_points(t, tree) for tree in ("balance", "feral", "restoration")},
        "allocation": final_allocation(t),
        "combat_profile": "balance",
        "stat_weights_contract_ok": True,
    })
    return row


def _decisions(row, target=30, route="balance"):
    return {
        "route_rows": {
            "druid": {str(target): {"routes": {route: {"status": "available", "rows": [row]}}}}
        },
        "per_level_rows": {"druid": [row]},
    }


def test_copied_talentsforever_url_decodes_exact_current_druid_schema():
    c = parse_talentsforever_url(KNOWN_URL, expected_class="druid")
    assert c["encoded_level"] == 60
    assert c["points"] == 51
    assert c["tree_points"] == {"balance": 36, "feral": 0, "restoration": 15}
    assert c["talent_ranks"]["improved_wrath"] == 5
    assert c["talent_ranks"]["moonkin_form"] == 1
    assert c["talent_ranks"]["reflection"] == 3
    assert c["source_url"] == KNOWN_URL
    assert c["progression_status"] == "exact_offline_source"


def test_known_source_backed_reference_can_compare_exact_prefix_per_level():
    c = parse_talentsforever_url(KNOWN_URL, expected_class="druid")
    a = _allocation_at_level(c, 30)
    assert sum(a["talent_ranks"].values()) == 21
    assert a["tree_points"] == {"balance": 21, "feral": 0, "restoration": 0}
    assert a["progression_source"] == "offline_source_leveling_order"


def test_arbitrary_final_build_url_does_not_invent_lower_level_order():
    # Same final allocation, distinct opaque source token: exact URL has no
    # offline captured progression. Final allocation can still be compared at 60.
    c = parse_talentsforever_url(
        "https://talentsforever.com/druid/60/5032220115501351--505203-4",
        expected_class="druid",
    )
    assert c["progression_status"] == "final_allocation_only"
    assert _allocation_at_level(c, 60)["level"] == 60
    with pytest.raises(TalentsForeverComparisonUnavailable, match="not lower-level point order"):
        _allocation_at_level(c, 30)


def test_malformed_or_cross_class_url_fails_clearly():
    with pytest.raises(TalentsForeverBuildError, match="talentsforever.com"):
        parse_talentsforever_url("https://example.com/druid/60/503--", expected_class="druid")
    with pytest.raises(TalentsForeverBuildError, match="listener selected druid"):
        parse_talentsforever_url("https://talentsforever.com/mage/60/---", expected_class="druid")


def test_same_gear_comparison_uses_canonical_scorer_and_has_weights_both_sides():
    row = _optimizer_row(30)
    url = "https://talentsforever.com/druid/30/5032220115--"
    result = compare_to_talentsforever_build(
        _decisions(row), class_name="druid", target_level=30, route="balance",
        selected_level=30, source_url=url, mode="same_gear",
    )
    assert result["status"] == "available"
    assert result["authority"]["challenger_search_authority"] is False
    assert result["optimizer"]["stat_weights"]
    assert result["challenger"]["stat_weights"]
    assert result["challenger"]["comparison_gear_mode"] == "fixed_optimizer_gear"
    assert result["challenger"]["gear_stats"]["slots"].keys() == row["gear_stats"]["slots"].keys()
    assert result["delta"]["challenger_minus_optimizer_percent"] == pytest.approx(0.0, abs=1e-8)



def test_stored_source_backed_l60_url_scores_honest_l30_prefix():
    row = _optimizer_row(30)
    result = compare_to_talentsforever_build(
        _decisions(row), class_name="druid", target_level=30, route="balance",
        selected_level=30, source_url=KNOWN_URL, mode="same_gear",
    )
    assert result["source"]["progression_status"] == "exact_offline_source"
    assert sum(result["challenger"]["talent_ranks"].values()) == 21
    assert result["challenger"]["progression_source"] == "offline_source_leveling_order"
    assert result["challenger"]["stat_weights"]

def test_full_decision_comparison_keeps_build_fixed_but_allows_own_gear():
    row = _optimizer_row(30)
    url = "https://talentsforever.com/druid/30/5032220115--"
    result = compare_to_talentsforever_build(
        _decisions(row), class_name="druid", target_level=30, route="balance",
        selected_level=30, source_url=url, mode="full_decision",
    )
    assert result["challenger"]["comparison_gear_mode"] == "independent_fixed_point"
    assert result["challenger"]["stat_weights"]
    assert result["profile"] == "balance"


def test_listener_has_paste_compare_control_source_link_and_two_modes():
    html = DECISIONS_HTML
    assert 'id="compareBuildUrl"' in html
    assert 'id="compareBuildMode"' in html
    assert 'value="same_gear"' in html and 'value="full_decision"' in html
    assert '/api/decisions/compare-build' in html
    assert 'TalentsForever source ↗' in html
    assert 'Compare this build' in html
    assert 'stat weights</b>' in html
