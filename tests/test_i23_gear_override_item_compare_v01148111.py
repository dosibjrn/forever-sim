from src.rulesets.forever.items.runtime_selection import gear_overrides, select_gear
from src.v2.item_tools import compare_items, wowhead_upgrade_search


def test_runtime_gear_override_pins_one_slot_and_leaves_others_selected():
    base = select_gear('druid', 12, 'druid_balance')
    assert 'hands' in base
    with gear_overrides({'hands': 4310}):
        locked = select_gear('druid', 12, 'druid_balance')
    assert locked['hands'].item_id == 4310
    assert len(locked) >= 2
    # At least one unpinned slot remains the normal selector result.
    common = [k for k in base if k != 'hands' and k in locked]
    assert common
    assert any(locked[k].item_id == base[k].item_id for k in common)


def test_runtime_gear_override_fails_closed_for_illegal_item():
    try:
        with gear_overrides({'hands': 15444}):  # staff in hands slot
            select_gear('druid', 12, 'druid_balance')
    except ValueError as exc:
        assert 'incompatible' in str(exc) or 'legal/available' in str(exc)
    else:
        raise AssertionError('illegal slot override must fail closed')


def test_item_compare_uses_published_weight_approximation():
    result = compare_items(4310, 15444, {'spell_power': 1.0, 'intellect': 0.2, 'spirit': 0.1})
    assert result['authority'] == 'published_stat_weight_approximation'
    assert result['item_a']['item_id'] == 4310
    assert result['item_b']['item_id'] == 15444
    assert isinstance(result['score_delta_b_minus_a'], float)


def test_upgrade_search_does_not_invent_wowhead_stat_filter_ids():
    result = wowhead_upgrade_search('druid', 12, {'spell_power': 1.0}, slot='hands')
    assert 'class:11' in result['url']
    assert result['applied_weight_filters'] == []
    assert 'spell_power' in result['omitted_weight_filters']


def test_listener_exposes_i23_controls_and_endpoints():
    from pathlib import Path
    text = Path('src/listener.py').read_text(encoding='utf-8')
    assert 'My gear / item compare' in text
    assert '/api/decisions/item-compare' in text
    assert '/api/decisions/upgrade-search' in text
    assert 'Lock & recompute' in text
    assert 'gear_overrides' in text


def test_service_executor_forwards_gear_override_json():
    from src.service.executors import V2RunnerExecutor
    job = {
        'request': {
            'ruleset':'forever','class_name':'druid','start_level':12,'end_level':12,
            'objective':'endpoint','endpoint_mode':'smooth','forever_build_as_of':'2026-10-02',
            'config': {'workers':1,'gear_overrides':{'hands':4768}},
        }
    }
    cmd = V2RunnerExecutor().plan(job).command
    assert '--gear-overrides-json' in cmd
    payload = cmd[cmd.index('--gear-overrides-json')+1]
    assert '"hands":4768' in payload
