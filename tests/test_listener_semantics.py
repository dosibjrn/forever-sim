from src import listener


def test_listener_normalizes_git_bash_msys_open_path_conversion():
    assert listener._normalize_open_path('C:/Program Files/Git/decisions') == '/decisions'
    assert listener._normalize_open_path(r'C:\Program Files\Git\fast') == '/fast'
    assert listener._normalize_open_path('/decisions') == '/decisions'
    assert listener._normalize_open_path('/unexpected') == '/unexpected'


def test_mc_viewer_uses_workload_mob_terminology_and_fields():
    html = listener.HTML
    assert 'equal-level mobs' not in html
    assert 'estimated_workload_mobs' in html
    assert 'L+1/L+2' in html


def test_mc_viewer_uses_canonical_path_id_for_selection():
    html = listener.HTML
    assert 'function cid(c)' in html
    assert 'path_id||' in html


def test_mc_viewer_explains_fast_vs_mc_delta():
    html = listener.HTML
    assert 'fast_analytic_hours' in html
    assert 'fast_vs_mc_delta_hours' in html


def test_decisions_view_exposes_single_route_workbench_and_never_autoruns_search():
    html = listener.DECISIONS_HTML
    assert 'Endpoint route transitions' in html
    assert 'Class comparison' in html
    assert 'Spec comparison' in html
    assert 'Continue from my current talents' in html
    assert 'Route stat trends' not in html
    assert 'matrixPick' not in html
    assert "fetch('/api/decisions/constraint'" in html
    assert 'src.v2.runner' not in html
    assert "fetch('/api/decisions',{cache:'no-store'})" in html
    assert "fetch('/api/decisions'+" not in html

def _get_from_handler(path, monkeypatch):
    import json
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import urlopen

    seen = []

    def fake_seed_bank(level, water_mode='buy_water', school=None):
        seen.append((level, water_mode, school))
        return {'level': level, 'candidates': []}

    monkeypatch.setattr(listener, 'seed_bank', fake_seed_bank)
    server = ThreadingHTTPServer(('127.0.0.1', 0), listener.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f'http://127.0.0.1:{server.server_port}{path}', timeout=2) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
            status = resp.status
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return status, payload, seen


def test_seed_api_without_school_passes_none_for_active_school_resolution(monkeypatch):
    status, payload, seen = _get_from_handler('/api/seeds?level=20&water=buy_water', monkeypatch)
    assert status == 200
    assert payload['level'] == 20
    assert seen == [(20, 'buy_water', None)]


def test_seed_api_forwards_explicit_school(monkeypatch):
    status, payload, seen = _get_from_handler('/api/seeds?level=20&water=buy_water&school=frost', monkeypatch)
    assert status == 200
    assert payload['level'] == 20
    assert seen == [(20, 'buy_water', 'frost')]


def test_decisions_view_surfaces_stat_weights_and_supports_mature_schema():
    html = listener.DECISIONS_HTML
    assert 'stat weights' in html
    assert 'function statWeightSummary' in html
    assert 'sw.stats' in html
    assert 'points_per_one_intellect' in html
    assert 'normalized_to_reference' in html
    assert "sw.analytical?'analytic · ':''" in html
    assert 'equal_item_budget' in html
    assert 'seconds_saved_per_100_per_equal_budget' in html
    assert 'equal-budget' in html


def test_decisions_view_exposes_per_level_gear_weights_talents_and_lazy_item_details():
    html = listener.DECISIONS_HTML
    assert '<b>stat weights</b>' in html
    assert 'row.allocation' in html
    assert 'row.rotation||row.policy' in html
    assert 'gearDetailsHtml(row)' in html
    assert 'Missing catalogue coverage:' in html
    assert 'Open to load item details.' in html
    assert "addEventListener('toggle'" in html
    assert 'gear_selection_method' in html
    assert 'rerolled independently each level' in html


def test_decisions_focus_consumes_canonical_route_rows_and_structured_talents():
    html = listener.DECISIONS_HTML
    assert 'data?.route_rows?.[state.cls]' in html
    assert 'row?.talent_trees' in html
    assert 'row?.tree_points' in html
    assert 'row?.talent_ranks' in html
    assert "cov.used.map(slot=>({slot,...(slots[slot]||{})}))" in html
    assert "v<=0?0" in html  # zero stat weight must render as a true zero-width bar
    assert 'missing.stat_weights' in html
    assert 'missing.gear' in html
    assert 'missing.timing' in html


def test_spec_comparison_distinguishes_cumulative_optimum_from_terminal_throughput():
    html = listener.DECISIONS_HTML
    assert 'CUMULATIVE OPTIMUM' in html
    assert 'terminal throughput' in html
    assert 'at L${target} only' in html
    assert 'L${target} FASTEST' in html
    assert 'unconstrained · cumulative optimum' in html


def test_decisions_listener_refreshes_only_when_service_publication_changes():
    html = listener.DECISIONS_HTML
    assert "let decisionsPublicationId=null;" in html
    assert "async function reloadDecisions()" in html
    assert "const publicationId=String(j.latest_publication?.id||'')" in html
    assert "publicationId!==decisionsPublicationId" in html
    assert "await reloadDecisions()" in html
    assert "setInterval(loadServiceStatus,2000)" in html
