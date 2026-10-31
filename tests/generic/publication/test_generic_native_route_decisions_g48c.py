"""G48c: canonical native route score is a separate backend-neutral level decision."""
from copy import deepcopy

import pytest

from src.v2.backend_decision import records_from_native_generic_route_rows
from src.v2.decision_dashboard import _generic_decision_payload
from src.listener import DECISIONS_HTML
from src.version import SOFTWARE_VERSION


@pytest.fixture(scope="module")
def publication():
    return _generic_decision_payload(10)


def test_native_decisions_are_distinct_and_match_route_authority(publication):
    assert tuple(map(int, SOFTWARE_VERSION.split("."))) >= (0, 11, 48, 175)
    assert len(publication["decisions"]) == 7
    assert len(publication["native_route_decisions"]) == 26
    source = {r["identity"]["class_name"]: r for r in publication["decisions"]}
    for cls in ("druid", "warrior", "rogue"):
        assert source[cls]["identity"]["level"] == 10
        assert source[cls]["publication_availability"]["route"] == "not_in_level_record"
        assert source[cls]["identity"].get("route_scored") is not True
    for r in publication["native_route_decisions"]:
        i = r["identity"]
        canonical = publication["route_rows"][i["class_name"]][str(i["target_level"])]["routes"][i["route"]]
        assert canonical["status"] == "available"
        row = next(x for x in canonical["rows"] if x["level"] == i["level"])
        assert i["route_scored"] is True
        assert r["publication_availability"]["route"] == "available"
        assert r["objective"]["score_s_per_100"] == row["score_s_per_100"]
        assert r["objective"]["mobs_per_hour"] == row["mobs_per_hour"]
        assert r["talents"]["allocation"] == row["allocation"]
        assert r["talents"]["ranks"] == row["talent_ranks"]
        assert r["policy"]["label"] == row["policy_ir"]["label"]
        assert r["stat_weights"]["stats"] == row["stat_weights"]["stats"]
        assert r["timing"]["seconds_per_mob"] == row["seconds_per_mob"]
        assert r["timing"]["travel_seconds_per_mob"] is None
        assert r["timing"]["complete"] is False
        assert r["objective"]["cross_class_comparable"] is False
        assert r["provenance"]["legacy_fallback"] is False
        assert r["compatibility"] == {}
        if i["class_name"] == "druid":
            assert r["gear"]["status"] == "selected_named_catalogue_gear"
            assert r["gear"]["slots"] == row["gear_stats"]["slots"]
            assert r["stat_weights"]["scope"] == "native_named_gear_state"
        else:
            assert r["gear"]["status"] == "scenario_proxy_no_named_items"
            assert r["gear"]["slots"] == {}
            assert r["stat_weights"]["scope"] == "proxy_scenario_only"
            assert r["timing"]["kill_seconds_per_mob"] is None
            assert r["timing"]["recovery_seconds_per_mob"] is None
    assert not any(r["identity"]["class_name"] in {"mage", "priest", "shaman", "warlock"}
                   for r in publication["native_route_decisions"])


def test_native_route_adapter_fails_closed_on_invalid_score_and_gear(publication):
    route = deepcopy({"warrior": publication["route_rows"]["warrior"]})
    row = route["warrior"]["12"]["routes"]["unconstrained"]["rows"][0]
    row["mobs_per_hour"] *= 2
    with pytest.raises(ValueError, match="inconsistent native route score"):
        records_from_native_generic_route_rows(route)
    row["mobs_per_hour"] /= 2
    row["gear_stats"]["slots"] = {"head": {"name": "invented"}}
    with pytest.raises(ValueError, match="ambiguous named/proxy gear provenance"):
        records_from_native_generic_route_rows(route)


def test_real_chromium_route_focus_switches_scored_record_without_overwriting_source(publication):
    from playwright.sync_api import sync_playwright

    html = DECISIONS_HTML.replace(
        '<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>', ''
    ).replace(
        "load().catch(e=>$('authority').textContent='Decisions unavailable: '+e);",
        '// G48c supplies real service publication'
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
                    return {level:state.level,route:state.route,
                        scored:document.querySelector('#nativeRouteDecision')?.innerText||'',
                        source:document.querySelector('#backendPublication')?.innerText||''};
                }''', {'payload': publication, 'cls': cls})
            warrior = select('warrior')
            assert 'warrior L12 / target L12' in warrior['scored']
            assert 'scenario proxy; no named gear' in warrior['scored']
            assert 'travel unmodeled' in warrior['scored']
            assert 'DecisionRecord L10 · route focus L12' in warrior['source']
            page.locator('button[data-native-route-level="11"]').first.click()
            focused = page.locator('#nativeRouteDecision').inner_text()
            assert 'warrior L11 / target L12' in focused
            assert 'talents:' in focused
            assert 'Native route score' in focused or 'NATIVE ROUTE SCORE' in focused
            assert 'DecisionRecord L10 · route focus L11' in page.locator('#backendPublication').inner_text()
            rogue = select('rogue')
            assert 'rogue L14 / target L14' in rogue['scored']
            druid = select('druid')
            assert 'druid L14 / target L14' in druid['scored']
            assert 'named catalogue slots' in druid['scored']
            assert 'Exact-state stat weights' in druid['scored']
            mage = select('mage')
            assert mage['scored'] == ''
            assert page.locator('#nativeRouteDecision').count() == 0
            assert not errors, errors
        finally:
            browser.close()
