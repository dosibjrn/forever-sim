import json
import os
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from src import listener
from tests.test_listener_rendered_contract_v01140 import _payload

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / 'docs' / 'validation' / 'LISTENER_I21_HOVER_VENDOR_SHIM_v0.11.48.109.png'
STATE = ROOT / 'docs' / 'validation' / 'LISTENER_I21_HOVER_VENDOR_SHIM_v0.11.48.109.json'


def _chromium():
    return shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome')


def test_i21_item_and_talent_hover_browser_integration():
    chrome = _chromium()
    if not chrome:
        pytest.skip('Chromium unavailable')

    payload = _payload()
    fixture_json = json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')
    storage_shim = (
        "<script>Object.defineProperty(window,'localStorage',{value:{"
        "getItem(){return null},setItem(){},removeItem(){},clear(){}}});"
        f"window.__DECISION_FIXTURE__={fixture_json};</script>"
    )
    # Vendor-behaviour shim: only the unreachable CDN implementation is replaced.
    # The listener's real anchors, refresh call and browser events are untouched.
    vendor_shim = r'''<script>
    window.$WowheadPower={refreshLinks(){
      document.querySelectorAll('a.wowhead-entity').forEach(a=>{
        if(a.dataset.i21Bound)return;a.dataset.i21Bound='1';
        a.addEventListener('mouseenter',()=>{
          document.querySelectorAll('.i21-vendor-tooltip').forEach(x=>x.remove());
          const d=document.createElement('div');d.className='i21-vendor-tooltip';
          d.style='position:fixed;z-index:99999;left:20px;top:20px;background:#09111e;color:#eee;border:1px solid #7385a2;border-radius:8px;padding:12px;font:14px system-ui;box-shadow:0 6px 20px #0009';
          d.textContent=`Wowhead hover integration · ${a.dataset.entityKind} ${a.dataset.entityId} · ${a.textContent.trim()}`;
          document.body.appendChild(d);
        });
        a.addEventListener('mouseleave',()=>document.querySelectorAll('.i21-vendor-tooltip').forEach(x=>x.remove()));
      });
    }};
    </script>'''
    remote = '<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>'
    html = listener.DECISIONS_HTML.replace(remote, vendor_shim)
    html = html.replace('</head>', storage_shim + '</head>', 1)
    html = html.replace(
        "fetch('/api/decisions',{cache:'no-store'})",
        "Promise.resolve({ok:true,status:200,json:async()=>window.__DECISION_FIXTURE__})",
        1,
    )
    errors=[]
    SHOT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome, headless=True, args=['--no-sandbox','--disable-gpu','--disable-dev-shm-usage'])
        page = browser.new_page(viewport={'width':1440,'height':1200})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.set_content(html, wait_until='domcontentloaded', timeout=10000)
        page.wait_for_selector('a.wowhead-entity[data-entity-kind="spell"]', timeout=5000)
        talent = page.locator('a.wowhead-entity[data-entity-kind="spell"]').first
        talent.hover(); page.wait_for_selector('.i21-vendor-tooltip', timeout=2000)
        talent_text=page.locator('.i21-vendor-tooltip').inner_text()
        talent.dispatch_event('mouseleave')
        item = page.locator('a.wowhead-entity[data-entity-kind="item"]').first
        item.hover(); page.wait_for_selector('.i21-vendor-tooltip', timeout=2000)
        item_text=page.locator('.i21-vendor-tooltip').inner_text()
        page.screenshot(path=str(SHOT), full_page=False)
        anchors=page.locator('a.wowhead-entity').count()
        browser.close()
    assert 'spell ' in talent_text
    assert 'item ' in item_text
    assert anchors >= 2
    assert errors == []
    STATE.write_text(json.dumps({'status':'pass','mode':'vendor-shim-browser-integration','anchors':anchors,'talent_hover':talent_text,'item_hover':item_text,'page_errors':errors,'remote_vendor_gate':'blocked_by_execution_environment_network'}, indent=2), encoding='utf-8')
