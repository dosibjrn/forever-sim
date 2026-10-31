from pathlib import Path

from src.listener import DECISIONS_HTML
from src.class_registry import get_definition
from src.rulesets.forever.classes.druid import engine as druid
from src.rulesets.forever.classes.hunter.profile import MODEL_FIDELITY as HUNTER_FIDELITY
from src.rulesets.forever.classes.mage import engine as mage


def test_four_current_scope_classes_expose_user_fidelity_and_stat_weight_capability():
    for name in ('mage','paladin','druid','hunter'):
        d = get_definition('forever', name)
        caps = d.capabilities
        assert caps.decision_artifacts is True
        assert caps.stat_weights is True
        assert caps.fidelity is True
        assert d.route_definitions


def test_planning_caps_are_explicit_not_silent_l60_claims():
    assert druid.VERIFIED_LEVEL_CAP == 30
    assert druid.PLANNING_LEVEL_CAP == 40
    assert mage.VERIFIED_LEVEL_CAP == 30
    assert mage.PLANNING_LEVEL_CAP == 40
    assert HUNTER_FIDELITY['verified_level_cap'] == 20
    assert HUNTER_FIDELITY['planning_level_cap'] == 40


def test_i16_i19_surface_is_co_located_in_focus_view():
    html = DECISIONS_HTML
    # I16 constrained regret, I17 dual spec, I18 continuation, I19 one-view/compare.
    for token in ('Constrained regret','Dual-spec plan','Next talent','focusBoard','focusCompareBuildUrl'):
        assert token in html
    # The one-view must expose core decision data without inventing a second scorer.
    for token in ('stat weights','rotation','items used','fidelity','provenance'):
        assert token.lower() in html.lower()


def test_post_i20_backlog_is_preserved_after_done_done_closure():
    plan = Path('OVERALL_PLAN_DONE_DONE_v0.11.48.88.2.md').read_text()
    for item in ('I21','I22','I23','I24'):
        assert item in plan
