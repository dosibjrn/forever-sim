"""G39: same canonical LevelFrontier -> route DP for two new classes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

from src.game.data.forever import build_game_ir_slice
from src.game.talents import apply_talent_selection, available_talent_points
from src.listener import DECISIONS_HTML
from src.version import SOFTWARE_VERSION
from src.v2.generic_frontier import GenericTalentRouteModel, ROUTE_AUTHORITY
from src.v2.generic_melee_routes import (
    MELEE_CORRIDORS, _fingerprint, build_generic_melee_route_publication,
    build_melee_level_frontier, generic_melee_route_publication, solve_generic_melee_routes,
    write_generic_melee_route_publication_cache,
)

CANONICAL_ITEM_SHA='d7d5a8519b227a761312bf4d1da56955b58184239a5a2ed7a06f84eb134dc854'


def test_g39_warrior_and_rogue_same_generic_frontier_and_dp():
    assert MELEE_CORRIDORS == {'warrior':(10,11,12),'rogue':(10,11,12,13,14)}
    assert GenericTalentRouteModel.name == 'generic-talent-route'
    for cls,levels in MELEE_CORRIDORS.items():
        result = solve_generic_melee_routes(cls)
        assert result.authority == ROUTE_AUTHORITY
        assert tuple(f.level for f in result.frontiers) == levels
        for frontier in result.frontiers:
            assert frontier.candidates
            for candidate in frontier.candidates:
                assert candidate.build.spent_points == available_talent_points(frontier.level)
                assert candidate.metadata['legacy_fallback'] is False
                assert candidate.loadout['selection_method'] == 'explicit_scenario_proxy_not_named_gear'
        path = result.targets[levels[-1]]['unconstrained'].path
        assert path is not None and path.respecs_used==0
        assert len(path.steps) == len(levels)
        assert [x.node.level for x in path.steps] == list(levels)
        model = GenericTalentRouteModel()
        for a,b in zip(path.steps,path.steps[1:]):
            assert model.legal_one_point_transition(a.node.talents,b.node.talents)==b.talent_added


def test_g39_named_constraints_and_no_higher_level_claims():
    warrior=solve_generic_melee_routes('warrior')
    rogue=solve_generic_melee_routes('rogue')
    assert warrior.targets[12]['arms'].status == 'available'
    assert rogue.targets[14]['assassination'].status == 'available'
    assert rogue.targets[14]['combat'].status == 'available'
    for cls in MELEE_CORRIDORS:
        result=solve_generic_melee_routes(cls)
        assert 15 not in result.targets


def test_g39_actual_action_modifiers_not_naming_only():
    warrior=build_game_ir_slice(class_key='warrior',level=12)
    rogue=build_game_ir_slice(class_key='rogue',level=14)
    def applied(ir,selection,level):
        changed,report=apply_talent_selection(ir,selection,level=level)
        return changed,report
    w, wreport=applied(warrior,{'improved_rend':3},12)
    base_rend=next(x for x in warrior.actions if x.family_key=='rend')
    new_rend=next(x for x in w.actions if x.family_key=='rend')
    assert new_rend.effects[0].total_base_damage>base_rend.effects[0].total_base_damage
    assert wreport.applied_modifiers[0]['action_id']==new_rend.id
    r, rreport=applied(rogue,{'improved_eviscerate':3,'improved_sinister_strike':2},14)
    base_evis=next(x for x in rogue.actions if x.family_key=='eviscerate')
    new_evis=next(x for x in r.actions if x.family_key=='eviscerate')
    base_builder=next(x for x in rogue.actions if x.family_key=='sinister_strike')
    new_builder=next(x for x in r.actions if x.family_key=='sinister_strike')
    assert new_evis.effects[0].base_min_by_resource_amount[2]>base_evis.effects[0].base_min_by_resource_amount[2]
    assert new_builder.costs[0].amount<base_builder.costs[0].amount
    assert len(rreport.applied_modifiers)==2


def test_g39_route_publication_native_rows_have_proxy_qualified_weights_and_noop_disclosure():
    publication=build_generic_melee_route_publication()
    assert publication['software_version'] == SOFTWARE_VERSION
    assert publication['route_authority'] == ROUTE_AUTHORITY
    assert set(publication['classes'])==set(MELEE_CORRIDORS)
    for cls,scope in publication['classes'].items():
        assert scope['normal_route_selectable']
        target=str(scope['target_level'])
        selected=scope['route_rows'][target]['routes']['unconstrained']
        assert selected['status']=='available'
        assert len(selected['rows']) == len(MELEE_CORRIDORS[cls])
        path=scope['endpoint_report']['targets'][target]['routes']['unconstrained']['path']
        for row,step in zip(selected['rows'],path['steps']):
            assert row['decision_contract']['backend']['id']=='generic'
            assert row['legacy_fallback'] is False
            assert row['stat_weights']['stats']
            assert row['talent_points_contract_ok'] and row['stat_weights_contract_ok']
            assert row['gear_stats']['slots']=={}
            assert abs(row['score_s_per_100']-step['score_s_per_100'])<1e-6
        assert not scope['quality_warnings'] or 'proxy_weapon_and_primary_stats' in scope['quality_warnings']
        assert scope['route_blocker_above_level']==MELEE_CORRIDORS[cls][-1]
    warrior=publication['classes']['warrior']['route_rows']['12']['routes']['unconstrained']['rows']
    assert all(not row['talent_effect_executed'] for row in warrior)
    assert all('allocated_talent_effect_not_executed_in_selected_combat' in row['quality_warnings'] for row in warrior)


def test_g39_versioned_cache_accepts_valid_and_rejects_stale_source(tmp_path,monkeypatch):
    from src.v2 import generic_melee_routes as module
    cache=tmp_path/'route.json'
    write_generic_melee_route_publication_cache(cache)
    loaded,metadata=generic_melee_route_publication(cache)
    assert metadata['status']=='validated_release_snapshot'
    assert len(loaded['rogue']['route_rows']['14']['routes']['unconstrained']['rows'])==5
    monkeypatch.setattr(module,'_fingerprint',lambda:'changed_source')
    loaded,metadata=generic_melee_route_publication(cache)
    assert metadata['status']=='live_canonical_solve'
    assert 'source_code_fingerprint' in metadata['reason']
    assert loaded['warrior']['legacy_fallback'] is False


def test_g39_decision_payload_normal_route_picker_and_listener():
    from src.v2.decision_dashboard import _generic_decision_payload
    p=_generic_decision_payload(14)
    assert p['active_backend']=='generic'
    assert p['generic_routes']['publication_cache']['status']=='validated_release_snapshot'
    assert p['product_surface']['status']=='generic_multi_class_bounded_routes'
    assert p['route_rows']['warrior']['12']['routes']['unconstrained']['status']=='available'
    assert p['route_rows']['rogue']['14']['routes']['combat']['status']=='available'
    assert p['generic_class_routes']['rogue']['publication_cache']['status']=='validated_release_snapshot'
    assert p['generic_class_routes']['warrior']['normal_route_selectable'] is True
    for cls in ('warrior','rogue'):
        record=next(x for x in p['decisions'] if x['identity']['class_name'].lower()==cls)
        assert record['capability']['normal_route_selectable'] is True
        assert record['provenance']['generic_route_solve']['legacy_fallback'] is False
    assert 'const cls=String(r?.identity?.class_name||\'\').toLowerCase(),gr=data?.generic_class_routes?.[cls]' in DECISIONS_HTML
    assert f"const CURRENT_SOFTWARE_VERSION='{SOFTWARE_VERSION}';" in DECISIONS_HTML
    assert 'function routesFor(cls,target)' in DECISIONS_HTML
    assert 'route?.status===\'available\'&&rows.length&&rows.every(hasStatWeights)' in DECISIONS_HTML


def test_g39_real_http_generic_routes_preserve_abilities_listener(tmp_path):
    from src.service.store import QueueStore
    from src.service.http_api import OptimizerHTTPServer
    from src.service.client import ServiceClient
    server=OptimizerHTTPServer(('127.0.0.1',0),QueueStore(tmp_path/'queue.sqlite3'),project_root=Path.cwd())
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        host=f'http://127.0.0.1:{server.server_address[1]}'
        p=ServiceClient(host,timeout=45).decisions(level=14,backend_id='generic')
        assert p['active_backend']=='generic'
        assert p['route_rows']['rogue']['14']['routes']['unconstrained']['status']=='available'
        assert len(p['route_rows']['warrior']['12']['routes']['unconstrained']['rows'])==3
        assert p['generic_class_routes']['rogue']['publication_cache']['status']=='validated_release_snapshot'
        assert 'Refresh all 9 class indexes' in DECISIONS_HTML
        assert 'Fetch next 20 tooltips' in DECISIONS_HTML
    finally:
        server.shutdown();server.server_close();worker.join(timeout=3)


def test_g39_canonical_item_database_unchanged_and_ability_capture_present():
    root=Path('data/forever/catalogue')
    assert hashlib.sha256((root/'items_2026-09-29.sqlite').read_bytes()).hexdigest()==CANONICAL_ITEM_SHA
    assert (root/'forever_abilities.sqlite').is_file()
    assert (root/'wowhead_abilities_manifest_20261008T145657Z.json').is_file()
