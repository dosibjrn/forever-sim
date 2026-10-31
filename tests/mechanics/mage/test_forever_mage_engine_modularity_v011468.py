from pathlib import Path

from src.rulesets.forever.classes.mage import engine


def test_mage_engine_policy_and_analytic_layers_are_extracted():
    assert engine.Policy.__module__.endswith('.mage.policy')
    assert engine.optimize_policy.__module__.endswith('.mage.policy')
    assert engine.optimize_talent_paths.__module__.endswith('.mage.policy')
    assert engine.analytic_stat_gradient.__module__.endswith('.mage.analytic')


def test_mage_engine_does_not_regrow_into_monolith():
    path = Path(engine.__file__)
    lines = path.read_text(encoding='utf-8').splitlines()
    assert len(lines) < 2000, f'mage engine regrew to {len(lines)} lines; keep policy/search/analytic layers extracted'
