from src.forever_build import configure
from src.v2.decision_result import DecisionResult, reports


def test_decision_reports_expose_active_forever_build():
    configure("2026-09-24", source="test")
    result = DecisionResult(class_name="mage", frontiers=(), targets={})
    routes, regrets = reports(result)
    assert routes["forever_build"]["build_id"] == "forever-beta@2026-09-24"
    assert regrets["forever_build"]["as_of"] == "2026-09-24"


def test_listener_source_surfaces_build_identity():
    from pathlib import Path
    text = Path('src/listener.py').read_text(encoding='utf-8')
    assert 'data?.forever_builds?.[state.cls]' in text
    assert 'legacy ≤.73' in text
