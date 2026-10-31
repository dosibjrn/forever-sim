from src.rulesets.forever.classes.paladin.gear import archetypes, gear_snapshot
from src.rulesets.forever.items.runtime_selection import available_items


def test_paladin_runtime_gear_is_sqlite_backed_and_reconciles():
    rows = available_items('paladin', 20)
    ids = {x.item_id for x in rows}
    assert rows
    for gear in archetypes(20):
        assert gear.selected_catalogue_items
        assert all(item_id in ids for _, item_id in gear.selected_catalogue_items)
        snap = gear_snapshot(gear)
        assert snap['catalogue_mode'] == 'sqlite_runtime_authority'
        assert snap['reconciliation_ok'] is True
        assert snap['items']
        assert all(x['model_kind'] == 'canonical_sqlite_item' for x in snap['items'])
        assert all(x['modeled'] is False for x in snap['items'])


def test_paladin_weapon_style_is_selected_from_catalogue():
    ret, tank = archetypes(20)
    ret_snap, tank_snap = gear_snapshot(ret), gear_snapshot(tank)
    assert ret_snap['hand_setup'] == '2H'
    assert 'offhand' not in ret_snap['slots']
    assert tank_snap['hand_setup'] == '1H + shield'
    assert tank_snap['slots']['offhand']['armor_type'] == 'shield'
    assert ret_snap['slots']['weapon']['item_id'] == dict(ret.selected_catalogue_items)['weapon']
    assert tank_snap['slots']['weapon']['item_id'] == dict(tank.selected_catalogue_items)['weapon']
