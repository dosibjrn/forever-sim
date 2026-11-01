from pathlib import Path
import re

from src.v2.icon_provenance import item_icon, talent_icon

ROOT = Path(__file__).resolve().parents[1]


def test_listener_uses_one_shared_hover_renderer_for_items_and_talents():
    html = (ROOT / 'src/listener.py').read_text(encoding='utf-8')
    assert 'function wowheadEntityReady(meta)' in html
    assert 'function wowheadLink(label,meta,extra=\'\',innerHtml=null)' in html
    assert "entityLabel(label,x.icon,'talent-icon')" in html
    assert "entityLabel(name,x.icon,'item-icon')" in html
    assert 'https://wow.zamimg.com/js/tooltips.js' in html
    assert 'refreshWowheadLinks()' in html
    # Entity-bearing icon labels must be anchors, not icon-only spans.
    body = re.search(r"function entityLabel\(label,meta,extra=''\)\{(.+?)\nlet wowheadRefreshTimer", html, re.S).group(1)
    assert 'wowheadEntityReady(meta)' in body
    assert 'wowheadLink(label,meta,extra,content)' in body


def test_exact_item_identity_is_hoverable_and_unverified_item_fails_closed():
    meta = item_icon('Wolfsbane', source_url='https://www.wowhead.com/forever/item=267369/wolfsbane')
    assert meta and meta['entity_verified'] is True and meta['entity_id'] == 267369
    assert item_icon('Definitely Not Wolfsbane', source_url='https://www.wowhead.com/forever/item=267369/wolfsbane') is None


def test_exact_talent_identity_is_hoverable_but_icon_only_talent_fails_closed():
    pala = talent_icon('paladin', 'benediction')
    assert pala and pala['entity_verified'] is True and pala['entity_id'] == 20101
    druid = talent_icon('druid', 'berserk')
    assert druid and druid.get('icon_verified') is True
    assert not druid.get('entity_id')


def test_druid_talent_entities_use_pinned_exact_wowhead_ids():
    from src.v2.icon_provenance import talent_icon

    wrath = talent_icon('druid', 'improved_wrath')
    assert wrath['entity_verified'] is True
    assert wrath['entity_id'] == 16814
    assert wrath['provenance_url'] == 'https://www.wowhead.com/forever/spell=16814/improved-wrath'

    genesis = talent_icon('druid', 'genesis')
    assert genesis['entity_verified'] is True
    assert genesis['entity_id'] == 1223081
    assert genesis['provenance_url'] == 'https://www.wowhead.com/forever/spell=1223081/genesis'
