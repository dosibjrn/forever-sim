from __future__ import annotations

import hashlib
from pathlib import Path

from src.listener import DECISIONS_HTML
from src.v2.decision_dashboard import _generic_decision_payload
from src.v2.generic_frontier import (
    ROUTE_AUTHORITY, GENERIC_DRUID_ROUTE_LEVELS,
    generic_druid_route_publication, publish_generic_druid_route_rows,
)

DB_SHA = 'd7d5a8519b227a761312bf4d1da56955b58184239a5a2ed7a06f84eb134dc854'


def test_g33_normal_listener_route_is_real_generic_candidate_path():
    payload = _generic_decision_payload(12)
    route = payload['route_rows']['druid']['14']['routes']['unconstrained']
    assert route['status'] == 'available', route
    assert payload['generic_routes']['normal_route_selectable'] is True
    assert payload['product_surface']['status'] == 'generic_multi_class_bounded_routes'
    rows = route['rows']
    assert [r['level'] for r in rows] == list(GENERIC_DRUID_ROUTE_LEVELS)
    assert [r['allocation'] for r in rows] == [f'talents:improved_wrath={i}' for i in range(1, 6)]
    path = payload['generic_routes']['path']['steps']
    for row, step in zip(rows, path):
        assert abs(row['score_s_per_100'] - step['score_s_per_100']) < 1e-7
        assert row['decision_contract']['backend']['id'] == 'generic'
        assert row['legacy_fallback'] is False
        assert row['gear_stats']['slots']
        assert row['stat_weights']['method'] == 'generic_exact_state_first_effect_forward_difference'
        assert set(row['stat_weights']['stats']) == {'spell_power', 'intellect', 'spirit', 'mp5'}
        assert row['stat_weights_contract_ok'] and row['talent_points_contract_ok']
        assert row['source'] == ROUTE_AUTHORITY
    assert payload['per_level_rows']['druid'] == rows
    druid = next(r for r in payload['decisions'] if r['identity']['class_name'].lower() == 'druid')
    assert druid['capability']['normal_route_selectable'] is True
    assert payload['cross_class_comparable'] is False
    assert 'upper_talent_tree_unrepresented' in payload['generic_routes']['classified_limitations']


def test_g33_native_route_fail_closed_on_missing_weights_and_mismatched_scores():
    reports, _, meta = generic_druid_route_publication()
    steps = [dict(x) for x in meta['selected_route_steps']]
    assert len(steps) == 5
    no_weights = [dict(x) for x in steps]
    no_weights[0]['stat_weights'] = {}
    row = publish_generic_druid_route_rows(reports, no_weights)['14']['routes']['unconstrained']
    assert row['status'] == 'unavailable'
    assert not row['rows']
    assert 'stat weights' in row['reason']
    bad_score = [dict(x) for x in steps]
    bad_score[0]['score_s_per_100'] += 0.1
    row = publish_generic_druid_route_rows(reports, bad_score)['14']['routes']['unconstrained']
    assert row['status'] == 'unavailable'
    assert not row['rows']
    assert 'diverged' in row['reason']


def test_g33_listener_normal_navigation_enforced_by_real_route_rows():
    assert 'function routesFor(cls,target)' in DECISIONS_HTML
    assert 'route?.status===\'available\'&&rows.length&&rows.every(hasStatWeights)' in DECISIONS_HTML
    assert 'function statWeightSummary(row)' in DECISIONS_HTML
    assert 'normal route ${gr.normal_route_selectable' in DECISIONS_HTML
    assert 'function genericPlayableDruidStepSummary()' in DECISIONS_HTML
    assert 'Playable generic Druid · selected L${esc(row.level)}' in DECISIONS_HTML
    assert "const CURRENT_SOFTWARE_VERSION='0.11.48.157';" in DECISIONS_HTML


def test_g33_canonical_db_unchanged():
    db = Path('data/forever/catalogue/items_2026-09-29.sqlite')
    assert hashlib.sha256(db.read_bytes()).hexdigest() == DB_SHA


def test_g33_comparison_does_not_claim_naked_generic_or_fully_attributed_delta():
    from src.v2.decision_dashboard import build_decision_payload
    comparison = build_decision_payload(selected_level=20, backend_id='compare')['comparisons'][0]
    assert comparison['numeric_scope_audit']['classification'] == 'incomplete_timing_scope'
    assert comparison['numeric_scope_audit']['unexplained_total_delta_bounded'] is False
    assert comparison['categories']['action_damage']['generic']['named_gear_applied'] is True
    assert 'still naked' not in ' '.join(comparison['categories']['action_damage']['classification'])
    assert comparison['authority']['legacy_values_feed_generic_execution'] is False


def test_g33_real_http_api_exposes_a_selectable_native_route(tmp_path):
    from src.service.store import QueueStore
    from src.service.http_api import OptimizerHTTPServer
    from src.service.client import ServiceClient
    import threading

    store = QueueStore(tmp_path / 'queue.sqlite3')
    server = OptimizerHTTPServer(('127.0.0.1', 0), store, project_root=Path.cwd())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ServiceClient(f'http://127.0.0.1:{server.server_address[1]}', timeout=30)
        payload = client.decisions(level=12, backend_id='generic')
        rows = payload['route_rows']['druid']['14']['routes']['unconstrained']
        assert payload['active_backend'] == 'generic'
        assert rows['status'] == 'available'
        assert len(rows['rows']) == 5
        assert payload['generic_routes']['normal_route_selectable'] is True
        assert all(row['decision_contract']['backend']['id'] == 'generic' for row in rows['rows'])
        assert payload['generic_routes']['publication_cache']['status'] == 'validated_release_snapshot'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
