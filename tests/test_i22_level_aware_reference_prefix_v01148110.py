from src.v2.reference_builds import reference_build_snapshot
from src.v2.talentsforever_compare import compare_to_talentsforever_build
from tests.test_talentsforever_compare_v0114891 import KNOWN_URL, _optimizer_row, _decisions
from src.listener import DECISIONS_HTML


def test_stored_exact_reference_materializes_source_order_prefixes():
    snap = reference_build_snapshot('druid')
    exact = next(b for b in snap['builds'] if b.get('allocation_detail_status') == 'exact')
    p12 = exact['prefixes_by_level']['12']
    assert p12['points'] == 3
    assert p12['tree_points'] == {'balance': 3, 'feral': 0, 'restoration': 0}
    assert p12['talent_ranks'] == {'improved_wrath': 3}
    assert p12['progression_source'] == 'talentsforever_leveling_order'


def test_l60_reference_compares_only_through_selected_l23_prefix():
    row = _optimizer_row(23)
    result = compare_to_talentsforever_build(
        _decisions(row, target=23), class_name='druid', target_level=23,
        route='balance', selected_level=23, source_url=KNOWN_URL, mode='same_gear',
    )
    assert result['status'] == 'available'
    assert result['level'] == 23
    assert sum(result['challenger']['talent_ranks'].values()) == 14
    assert result['challenger']['progression_source'] == 'offline_source_leveling_order'
    assert result['comparison_horizon'] == {
        'through_level': 23, 'reference_points_used': 14,
        'reference_endpoint_level': 60, 'reference_endpoint_points': 51,
        'progression_source': 'offline_source_leveling_order',
    }


def test_listener_never_deltas_low_level_optimizer_against_final_reference_split():
    html = DECISIONS_HTML
    assert 'referencePrefixAtLevel' in html
    assert 'Final L${Number(selected.level||60)} split shown only' in html
    assert 'optimizer − L${compareLevel} reference prefix' in html
    assert 'TalentsForever leveling order' in html
