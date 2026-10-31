import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from copy import deepcopy
from http.server import ThreadingHTTPServer

import pytest

from src import listener
from src.v2.icon_provenance import item_icon, rotation_icon, talent_icon


def _talent_icon(key):
    return talent_icon('paladin', key)


def _rotation_icon(label):
    return rotation_icon('paladin', label, level=20)


def _item_icon(name):
    return item_icon(name)


def _route(name, mph, family):
    return {
        'status': 'available',
        'path': {
            'mobs_per_hour': mph,
            'talent_family': family,
            'steps': [{'level': 20, 'mobs_per_hour': mph, 'talent_family': family}],
        },
        'transitions': [],
    }


def _payload():
    talents = {
        'holy': {'points': 0, 'talents': []},
        'protection': {'points': 0, 'talents': []},
        'retribution': {'points': 11, 'talents': [
            {'name': 'deflection', 'rank': 5, 'icon': _talent_icon('deflection')},
            {'name': 'benediction', 'rank': 1, 'icon': _talent_icon('benediction')},
            {'name': 'conviction', 'rank': 4, 'icon': _talent_icon('conviction')},
            {'name': 'seal_of_command', 'rank': 1, 'icon': _talent_icon('seal_of_command')},
        ]},
    }
    row = {
        'level': 20,
        'allocation': 'holy(0) / protection(0) / retribution(11)[deflection:5,benediction:1,conviction:4,seal_of_command:1]',
        'talent_ranks': {'deflection':5,'benediction':1,'conviction':4,'seal_of_command':1},
        'tree_points': {'holy':0,'protection':0,'retribution':11},
        'talent_family': 'retribution',
        'talent_trees': talents,
        'mobs_per_hour': 295.6,
        'seconds_per_mob': 13.17,
        'kill_seconds_per_mob': 9.65,
        'recovery_seconds_per_mob': 3.52,
        'travel_seconds_per_mob': 0.0,
        'pull_size': 3,
        'combat_profile': 'retribution',
        'gear': '2h_normal',
        'aura': 'retribution',
        'mana_plan': 'full',
        'policy': 'aggressive',
        'rotation': 'Seal of Command up; Judgement on CD; Holy Strike on CD; melee weave',
        'rotation_steps': [
            {'label':'Seal of Command up', 'icon': _rotation_icon('Seal of Command up')},
            {'label':'Judgement on CD', 'icon': _rotation_icon('Judgement on CD')},
            {'label':'Holy Strike on CD', 'icon': _rotation_icon('Holy Strike on CD')},
            {'label':'melee weave'},
        ],
        'stat_weights': {'stats': {
            'strength': {'seconds_saved_per_100_per_point': 3.2},
            'spell_power': {'seconds_saved_per_100_per_point': 2.2},
            'spirit': {'seconds_saved_per_100_per_point': 1.1},
            'stamina': {'seconds_saved_per_100_per_point': 0.5},
            'intellect': {'seconds_saved_per_100_per_point': 0.0},
        }},
        'gear_stats': {'slots': {
            'waist': {'name':"Crusader's Chain Belt", 'strength':3, 'stamina':4, 'icon':_item_icon("Crusader's Chain Belt")},
            'legs': {'name':"Crusader's Chain Leggings", 'strength':5, 'stamina':5, 'icon':_item_icon("Crusader's Chain Leggings")},
            'feet': {'name':"Crusader's Boots", 'strength':4, 'stamina':4, 'icon':_item_icon("Crusader's Boots")},
        }},
        'missing': {},
    }
    routes = {
        'unconstrained': _route('unconstrained', 295.6, 'holy'),
        'holy': _route('holy', 297.0, 'holy'),
        'protection': _route('protection', 309.9, 'protection'),
        'retribution': _route('retribution', 318.5, 'retribution'),
    }
    # Keep focus identity consistent with the canonical row while reproducing the
    # user's exact confusing comparison: cumulative optimum is not terminal fastest.
    routes['unconstrained']['path']['talent_family'] = 'retribution'
    routes['unconstrained']['path']['steps'] = [deepcopy(row)]
    reg = {
        'unconstrained': {'status':'available','regret_percent':0.0,'objective_seconds':1000.0},
        'holy': {'status':'available','regret_percent':0.08,'objective_seconds':1000.8},
        'protection': {'status':'available','regret_percent':2.61,'objective_seconds':1026.1},
        'retribution': {'status':'available','regret_percent':2.68,'objective_seconds':1026.8},
    }
    return {
        'schema_version': 1,
        'ruleset': 'forever',
        'selected_level': 20,
        'levels': [20],
        'cards': [],
        'endpoint_paths': {'paladin': {'targets': {'20': {'status':'available','target_level':20,'routes':routes}}}},
        'spec_regret': {'paladin': {'targets': {'20': {'status':'available','target_level':20,'routes':reg}}}},
        'dual_spec': {},
        'spec_matrix': {'paladin': {'matrices': {'20:unconstrained': {'status':'available','target_level':20,'route':'unconstrained','rows':[deepcopy(row)]}}}},
        'route_rows': {'paladin': {'20': {'routes': {'unconstrained': {'status':'available','rows':[deepcopy(row)]}}}}},
        'comparability_note': 'fixture',
        'authority_note': 'fixture',
    }


def _chromium():
    return shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome')


def test_decisions_rendered_contract_semantics_and_entity_links(monkeypatch):
    chrome = _chromium()
    if not chrome:
        if os.environ.get('REQUIRE_CHROMIUM') == '1':
            pytest.fail('Chromium is required by the rendered listener release gate')
        pytest.skip('Chromium not installed')

    monkeypatch.setattr(listener, 'decision_snapshot', lambda level=None: _payload())
    # External Wowhead JS is production behavior, but rendered correctness must
    # not depend on internet access.  Keep the exact listener implementation and
    # only suppress the remote script load for this local DOM gate.
    remote = '<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>'
    monkeypatch.setattr(listener, 'DECISIONS_HTML', listener.DECISIONS_HTML.replace(remote, ''))

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        if os.environ.get('REQUIRE_CHROMIUM') == '1':
            pytest.fail('Playwright is required by the rendered listener release gate')
        pytest.skip('Playwright not installed')

    fixture_json = json.dumps(_payload(), ensure_ascii=False).replace('</', '<\\/')
    storage_shim = (
        "<script>Object.defineProperty(window,'localStorage',{value:{"
        "getItem(){return null},setItem(){},removeItem(){},clear(){}}});"
        f"window.__DECISION_FIXTURE__={fixture_json};</script>"
    )
    test_html = listener.DECISIONS_HTML.replace(remote, '')
    test_html = test_html.replace('</head>', storage_shim + '</head>', 1)
    test_html = test_html.replace(
        "fetch('/api/decisions',{cache:'no-store'})",
        "Promise.resolve({json:async()=>window.__DECISION_FIXTURE__})",
        1,
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome,
            headless=True,
            args=['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
        )
        page = browser.new_page(viewport={'width': 1440, 'height': 1200})
        page.set_content(test_html, wait_until='domcontentloaded', timeout=10000)
        page.wait_for_selector('.spec-row[data-route="retribution"]', timeout=5000)
        dom = page.content()
        browser.close()

    # The exact bug reported by the user: cumulative optimum must not look like
    # a claim that 295.6 is faster than 318.5 at L20.
    assert 'CUMULATIVE OPTIMUM' in dom
    assert 'L20 FASTEST' in dom
    assert 'L20 terminal throughput' in dom
    unconstrained = re.search(r'<div class="spec-row sel" data-route="unconstrained">(.*?)</div>\s*</div>', dom, re.S)
    assert unconstrained and '295.6 mobs/h' in unconstrained.group(1) and 'CUMULATIVE OPTIMUM' in unconstrained.group(1)
    retri = re.search(r'<div class="spec-row " data-route="retribution">(.*?)</div>\s*</div>', dom, re.S)
    assert retri and '318.5 mobs/h' in retri.group(1) and 'L20 FASTEST' in retri.group(1)

    # Truthful focus data cannot silently collapse back into placeholders.
    for text in ('Deflection', 'Holy Strike on CD', "Crusader's Chain Belt", '13.17', '3.52', 'Intellect'):
        assert text in dom
    assert re.search(r'>Intellect</span><b>0</b>', dom)

    # Talent/spell icons are data-driven client icon keys, not a hand-maintained
    # image registry. Item links still use exact Wowhead entity identity/tooltips.
    ids = set(re.findall(r'data-entity-id="(\d+)"', dom))
    assert {'20064','20101','20121','20375','20271','1866','250517','250497','250507'} <= ids
    assert dom.count('data-icon-provider="talentsforever_data"') >= 7
    assert 'data-icon-key="ability_parry"' in dom
    assert 'data-icon-key="classicon_paladin"' in dom
    assert 'https://wow.zamimg.com/images/wow/icons/small/ability_parry.jpg' in dom
    assert 'https://wow.zamimg.com/images/wow/icons/small/classicon_paladin.jpg' in dom
