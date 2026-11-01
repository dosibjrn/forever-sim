"""G46i: Chromium executes the real listener renderer with canonical generic data.

The local browser cannot navigate localhost in some sandboxes. set_content avoids
network navigation; the payload comes from the production decision builder.
"""
from src.listener import DECISIONS_HTML
from src.v2.decision_dashboard import build_decision_payload


def test_generic_mage_browser_renderer_with_real_payload():
    from playwright.sync_api import sync_playwright
    payload = build_decision_payload(project_root=__import__('pathlib').Path('.').resolve(), backend_id='generic', selected_level=10)
    assert any(r.get('identity', {}).get('class_name') == 'mage' for r in payload['decisions'])
    html = DECISIONS_HTML.replace('<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>', '')
    html = html.replace("load().catch(e=>$('authority').textContent='Decisions unavailable: '+e);", '// G46i: initialization supplied by test')
    html = html.replace('localStorage.', 'window.__g46Storage.')
    html = html.replace('<head>', '<head><script>window.__g46Storage={getItem:()=>null,setItem:()=>{}};</script>', 1)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                                     args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking'])
        try:
            page = browser.new_page()
            page.set_content(html, wait_until='domcontentloaded', timeout=10000)
            result = page.evaluate('''payload => {
                data = payload;
                state.backend = 'generic'; state.cls = 'mage'; state.level = 10;
                renderBackendPublication();
                return {text: document.getElementById('backendPublication').innerText,
                        meta: document.getElementById('backendPublicationMeta').innerText};
            }''', payload)
            assert 'mage' in result['text'].lower()
            assert 'Decision contract' in result['text']
            assert 'generic' in result['meta']
            assert 'legacy fallback disabled' in result['text'].lower()
            assert 'source IR L10–L20' in result['text']
            assert 'no verified native route' in result['text']
            assert 'Playable race selection: not verified' in result['text']
            assert 'Generic publication coverage' in result['text']
            assert 'Gear: available' in result['text']
            assert 'Route: unavailable' in result['text']
            assert 'Stat weights: available' in result['text']
        finally:
            browser.close()
