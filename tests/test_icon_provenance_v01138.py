import json

from src import listener
from src.v2.decision_dashboard import build_decision_payload
from src.v2.icon_provenance import item_icon, rotation_icon, talent_icon


def test_icon_cache_is_data_driven_and_exact_entities_are_optional_metadata():
    d = talent_icon('paladin', 'deflection')
    assert d['entity_id'] == 20064
    assert d['icon_provider'] == 'talentsforever_data'
    assert d['icon_key'] == 'ability_parry'
    assert d['icon_url'].endswith('/ability_parry.jpg')
    assert talent_icon('paladin', 'made_up_talent') is None

    assert item_icon("Crusader's Chain Belt")['entity_id'] == 250517
    assert item_icon("Crusader's Chain Shirt")['entity_id'] == 250492
    assert item_icon("Crusader's Gloves")['entity_id'] == 250512
    assert item_icon("Crusaders Chain Belt") is None  # exact-name only
    auto = item_icon('Any Exact Item', source_url='https://www.wowhead.com/forever/item=12345/example')
    assert auto is None  # URL syntax alone does not verify ID/name identity
    assert item_icon('Recipe-backed Item', source_url='https://www.wowhead.com/forever/spell=54321/example') is None

    holy = rotation_icon('paladin', 'Holy Strike on CD', level=20)
    assert holy['entity_id'] == 1866 and holy['icon_verified'] is True
    assert holy['icon_provider'] == 'talentsforever_data'
    # Icon identity is stable across ranks/levels; exact entity ID is merely optional link metadata.
    assert rotation_icon('paladin', 'Holy Strike on CD', level=21)['icon_key'] == 'classicon_paladin'


def test_dashboard_adds_icon_provenance_without_changing_route_identity(tmp_path):
    root = tmp_path / 'state/decisions/forever'; root.mkdir(parents=True)
    endpoint = {'classes': {'paladin': {'targets': {'20': {'routes': {'unconstrained': {
        'status': 'available', 'path': {'steps': [{
            'level': 20,
            'allocation': 'holy(0) / protection(0) / retribution(11)[deflection:5,benediction:1,conviction:4,seal_of_command:1]',
            'talent_ranks': {'deflection':5,'benediction':1,'conviction':4,'seal_of_command':1},
            'tree_points': {'holy':0,'protection':0,'retribution':11},
            'talent_family':'retribution',
        }]}
    }}}}}}}
    matrix = {'classes': {'paladin': {'matrices': {'20:unconstrained': {'status':'available','rows':[{
        'level':20,
        'rotation':'Seal of Command up; Judgement on CD; Holy Strike on CD; melee weave',
        'gear_stats':{'slots':{
            'chest':{'name':"Crusader's Chain Shirt"},
            'hands':{'name':"Crusader's Gloves"},
            'waist':{'name':"Crusader's Chain Belt"},
            'feet':{'name':"Crusader's Boots"},
            'legs':{'name':"Crusader's Chain Leggings"},
            'wrist':{'name':'Modeled Mail Bracers'},
        }},
    }]}}}}}
    for name, obj in {
        'endpoint_paths.json': endpoint, 'spec_matrix.json': matrix,
        'spec_regret.json': {'classes':{}}, 'dual_spec.json': {'classes':{}},
    }.items():
        (root / name).write_text(json.dumps(obj), encoding='utf-8')

    row = build_decision_payload(tmp_path, selected_level=20)['route_rows']['paladin']['20']['routes']['unconstrained']['rows'][0]
    talents = {x['name']: x for x in row['talent_trees']['retribution']['talents']}
    assert talents['deflection']['rank'] == 5
    assert talents['deflection']['icon']['icon_key'] == 'ability_parry'
    assert [x.get('icon', {}).get('icon_provider') for x in row['rotation_steps'][:3]] == ['talentsforever_data'] * 3
    assert row['gear_stats']['slots']['chest']['icon']['entity_id'] == 250492
    assert row['gear_stats']['slots']['hands']['icon']['entity_id'] == 250512
    assert 'icon' not in row['gear_stats']['slots']['wrist']


def test_listener_uses_generated_icon_urls_and_wowhead_item_tooltips_with_text_fallback():
    html = listener.DECISIONS_HTML
    assert 'https://wow.zamimg.com/js/tooltips.js' in html
    assert 'iconizeLinks:true' in html and 'renameLinks:false' in html
    assert 'window.$WowheadPower?.refreshLinks' in html
    assert 'data-wh-icon-size="small"' in html
    assert 'data-icon-provider' in html and 'data-icon-key' in html
    assert '<img class="entity-icon"' in html
    assert "onerror=\"this.style.display='none'\"" in html
    assert "entityLabel(label,x.icon,'talent-icon')" in html
    assert "entityLabel(x.label,x.icon,'rotation-icon')" in html
    assert "entityLabel(name,x.icon,'item-icon')" in html
