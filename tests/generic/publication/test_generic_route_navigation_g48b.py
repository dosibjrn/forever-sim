"""G48b: backend-neutral native route navigation and explicit proxy fidelity.

Exercises real generic payload, canonical release snapshots and actual Chromium
listener JS. The route rows are not replaced by legacy rows or invented gear.
"""
from pathlib import Path

from src.game.data.forever.registry import registered_class_keys
from src.listener import DECISIONS_HTML
from src.v2.decision_dashboard import _generic_decision_payload
from src.version import SOFTWARE_VERSION


def test_g48b_reconciled_g48a_contract_and_native_route_rows():
    payload = _generic_decision_payload(10)
    assert tuple(map(int, SOFTWARE_VERSION.split("."))) >= (0, 11, 48, 174)
    assert f"const CURRENT_SOFTWARE_VERSION='{SOFTWARE_VERSION}';" in DECISIONS_HTML
    assert set(x["identity"]["class_name"] for x in payload["decisions"]) == set(registered_class_keys())
    for record in payload["decisions"]:
        assert set(record["publication_availability"]) == {
            "selected_build", "gear", "stat_weights", "policy", "timing", "route"
        }
        assert record["publication_availability"]["route"] == "not_in_level_record"
        assert len(record["capability"]["publication_sections"]["sections"]) == 7
    for cls, end, count in (("warrior", 12, 3), ("rogue", 14, 5), ("druid", 14, 5)):
        route = payload["generic_class_routes"][cls]
        assert route["normal_route_selectable"] is True
        rows = payload["route_rows"][cls][str(end)]["routes"]["unconstrained"]["rows"]
        assert [r["level"] for r in rows] == list(range(10, end + 1))
        assert len(rows) == count
        assert all(r["legacy_fallback"] is False for r in rows)
        if cls in ("warrior", "rogue"):
            assert all(r["gear_stats"]["slots"] == {} for r in rows)
            assert all(r["gear_stats"]["selection_method"] == "explicit_scenario_proxy_not_named_gear" for r in rows)
            assert all("proxy_scenario" in r["stat_weights"]["method"] for r in rows)
        else:
            assert rows[-1]["gear_stats"]["slots"]
    for cls in ("mage", "priest", "shaman", "warlock"):
        assert cls not in payload["route_rows"]
        assert payload["class_metadata"][cls]["planning_levels"] == []


def test_g48b_real_chromium_native_route_level_clicks_and_capability_only_classes():
    from playwright.sync_api import sync_playwright

    payload = _generic_decision_payload(10)
    html = DECISIONS_HTML.replace(
        '<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>', ''
    ).replace(
        "load().catch(e=>$('authority').textContent='Decisions unavailable: '+e);",
        '// test supplies the real payload'
    ).replace('localStorage.', 'window.__g48Storage.').replace(
        '<head>', '<head><script>window.__g48Storage={getItem:()=>null,setItem:()=>{}};</script>', 1
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path='/usr/bin/chromium', headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking'],
        )
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.set_content(html, wait_until='domcontentloaded', timeout=12000)

            def select(cls):
                return page.evaluate('''({payload,cls}) => {
                    data=payload;state.backend='generic';state.cls=cls;
                    state.level=NaN;state.route='';state.target='';
                    syncState();renderAll();
                    return {className:state.cls,level:state.level,
                            buttons:document.querySelectorAll('.native-route-jump').length,
                            scope:document.getElementById('nativeRouteScope')?.innerText||'',
                            summary:document.getElementById('routeSummary').innerText,
                            display:document.querySelector('.route-product').style.display};
                }''', {'payload': payload, 'cls': cls})

            warrior = select('warrior')
            assert warrior['level'] == 12 and warrior['buttons'] == 3
            assert 'L10–L12' in warrior['scope']
            assert 'no named gear' in warrior['summary']
            assert 'Cross-class scores are not comparable' in warrior['scope']
            page.locator('button[data-native-route-level="11"]').first.click()
            result = page.evaluate('''() => ({level:state.level,
                focus:document.getElementById('focusTitle').innerText,
                record:document.getElementById('backendPublication').innerText,
                highlighted:document.querySelector('.level-card.focus')?.id,
                scopes:document.querySelectorAll('#nativeRouteScope').length})''')
            assert result['level'] == 11 and result['highlighted'] == 'route-L11'
            assert 'Level 11' in result['focus']
            assert 'DecisionRecord L10 · route focus L11' in result['record']
            assert 'Level-record fields:' in result['record']
            assert result['scopes'] == 1

            rogue = select('rogue')
            assert rogue['level'] == 14 and rogue['buttons'] == 5
            assert 'L10–L14' in rogue['scope']
            assert 'no named gear' in rogue['summary']
            druid = select('druid')
            assert druid['buttons'] == 5 and 'L10–L14' in druid['scope']
            assert 'named-gear snapshots' in druid['scope']
            assert 'Scenario proxy' not in druid['scope']
            mage = select('mage')
            assert mage['display'] == 'none'
            assert not mage['scope']
            assert page.locator('#nativeRouteScope').count() == 0
            assert 'no verified native route' in page.locator('#backendPublication').inner_text()
            assert not errors, errors
        finally:
            browser.close()
