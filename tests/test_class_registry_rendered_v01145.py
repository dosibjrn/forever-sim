from __future__ import annotations

import json
import os
import shutil

import pytest

from src import listener
from src.v2.icon_provenance import decorate_rotation_steps, decorate_talent_trees


def _payload():
    trees = decorate_talent_trees('warrior', {
        'arms': {'points': 11, 'talents': [
            {'name':'improved_heroic_strike','rank':3},
            {'name':'improved_rend','rank':3},
            {'name':'deflection','rank':5},
        ]},
        'fury': {'points': 0, 'talents': []},
        'protection': {'points': 0, 'talents': []},
    })
    row = {
        'level':20,
        'allocation':'arms(11)[improved_heroic_strike:3,improved_rend:3,deflection:5] / fury(0) / protection(0)',
        'talent_ranks':{'improved_heroic_strike':3,'improved_rend':3,'deflection':5},
        'tree_points':{'arms':11,'fury':0,'protection':0},
        'talent_family':'arms',
        'talent_trees':trees,
        'mobs_per_hour':208.7,
        'seconds_per_mob':17.25,
        'kill_seconds_per_mob':15.7,
        'recovery_seconds_per_mob':0.35,
        'travel_seconds_per_mob':1.2,
        'pull_size':1,
        'combat_profile':'single_target_proof',
        'gear':'proof_level_curve',
        'policy':'heroic_strike_rage_filler',
        'rotation':'Auto Attack; Heroic Strike when rage allows',
        'rotation_steps':decorate_rotation_steps('warrior','Auto Attack; Heroic Strike when rage allows',level=20),
        'stat_weights':{'schema_version':3,'reference_stat':'weapon_dps','stats':{
            'weapon_dps':{'status':'measured','seconds_saved_per_100_per_point':5.0},
            'strength':{'status':'measured','seconds_saved_per_100_per_point':0.6},
            'stamina':{'status':'measured','seconds_saved_per_100_per_point':0.2},
            'armor':{'status':'measured','seconds_saved_per_100_per_point':0.01},
            'defense':{'status':'not_modeled','reason':'M45 proof excludes Defense items'},
        }},
        'gear_stats':{'model':'proof_level_curve','strength':44,'stamina':54,'armor':700,'weapon_dps':22.4,'slots':{}},
        'missing':{'gear':'named gear snapshot unavailable for proof backend'},
    }
    route={'status':'available','path':{'mobs_per_hour':208.7,'talent_family':'arms','steps':[row]},'transitions':[]}
    return {
        'schema_version':1,'ruleset':'forever','selected_level':20,'levels':[20],
        'cards':[{'class':'warrior','available':True,'level':20}],
        'class_metadata':{'warrior':{
            'display_name':'Warrior','tree_names':['arms','fury','protection'],
            'primary_profiles':['all','arms','fury','protection'],
            'capabilities':{'decision_artifacts':True,'replay':False,'named_gear':False},
            'accent':'#c79c6e','proof_only':True,
        }},
        'endpoint_paths':{'warrior':{'targets':{'20':{'status':'available','target_level':20,'routes':{'unconstrained':route,'arms':route}}}}},
        'spec_regret':{'warrior':{'targets':{'20':{'routes':{'unconstrained':{'status':'available','regret_percent':0},'arms':{'status':'available','regret_percent':0}}}}}},
        'dual_spec':{'warrior':{'status':'unlock_after_target','unlock_level':40,'target_level':20,'reason':'proof target ends before unlock'}},
        'spec_matrix':{'warrior':{'matrices':{'20:unconstrained':{'status':'available','target_level':20,'route':'unconstrained','rows':[row]}}}},
        'route_rows':{'warrior':{'20':{'routes':{'unconstrained':{'status':'available','rows':[row]}}}}},
        'comparability_note':'proof fixture','authority_note':'common decision contract fixture',
    }


def _chromium():
    return shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome')


def test_warrior_proof_renders_from_common_decision_contract():
    chrome=_chromium()
    if not chrome:
        if os.environ.get('REQUIRE_CHROMIUM')=='1':
            pytest.fail('Chromium is required by the M45 rendered listener release gate')
        pytest.skip('Chromium not installed')
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        if os.environ.get('REQUIRE_CHROMIUM')=='1':
            pytest.fail('Playwright is required by the M45 rendered listener release gate')
        pytest.skip('Playwright not installed')

    remote='<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>'
    fixture_json=json.dumps(_payload(),ensure_ascii=False).replace('</','<\\/')
    storage_shim=(
        "<script>Object.defineProperty(window,'localStorage',{value:{getItem(){return null},setItem(){},removeItem(){},clear(){}}});"
        f"window.__DECISION_FIXTURE__={fixture_json};</script>"
    )
    html=listener.DECISIONS_HTML.replace(remote,'')
    html=html.replace('</head>',storage_shim+'</head>',1)
    html=html.replace("fetch('/api/decisions',{cache:'no-store'})","Promise.resolve({json:async()=>window.__DECISION_FIXTURE__})",1)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=chrome,headless=True,args=['--no-sandbox','--disable-gpu','--disable-dev-shm-usage'])
        page=browser.new_page(viewport={'width':1440,'height':1100})
        page.set_content(html,wait_until='domcontentloaded',timeout=10000)
        page.wait_for_selector('#focusBoard .talent-tree',timeout=5000)
        dom=page.content()
        selected=page.locator('#classPick option:checked').inner_text()
        browser.close()

    assert selected == 'Warrior · proof'
    assert 'Arms (11)' in dom and 'Fury (0)' in dom and 'Protection (0)' in dom
    assert 'Improved Heroic Strike' in dom and 'Deflection' in dom
    assert 'Heroic Strike when rage allows' in dom
    assert 'data-icon-provider="talentsforever_data"' in dom
    assert 'Availability · not modeled: defense' in dom
    assert 'named gear snapshot unavailable for proof backend' in dom
