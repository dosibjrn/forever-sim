from __future__ import annotations

import pytest

from src.rulesets.forever.classes.mage import engine as mage
from src.v2.mature_decision_artifacts import _gear_stats
from src.v2.spec_matrix import _mature_score


def test_mature_decision_gear_stats_use_discrete_real_items_not_owl_or_modeled_curve():
    cfg = mage.SimConfig(use_best_water=True)
    gear = _gear_stats(mage, 40, cfg)
    assert gear['provenance'] == 'canonical_sqlite_forever_catalogue'
    assert gear['slots']['wrist']['name'] == 'Mindthrust Bracers'
    assert not gear['slots']['wrist'].get('modeled', False)


def test_route_matrix_mage_row_has_listener_rate_timing_and_per_slot_gear_fields():
    score, _policy, _cfg = _mature_score(mage, 40, mage.Talents(), cfg=mage.SimConfig(use_best_water=True))
    assert score['gear_stats']['provenance'] == 'discrete_named_forever_items'
    assert score['mobs_per_hour'] > 0
    assert score['seconds_per_mob'] == pytest.approx(
        score['kill_seconds_per_mob'] + score['recovery_seconds_per_mob'], abs=1e-9
    )
    assert score['gear_stats']['slots']['back']['name'] == 'Heavy Woolen Cloak'
    assert score['gear_stats']['slots']['back']['effective_level'] < 40
