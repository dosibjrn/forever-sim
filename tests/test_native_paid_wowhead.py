"""Live Wowhead overlays only use verified source-native identifiers."""
from tools.wf_native_paid_wowhead import (
    WOWHEAD_BOOTSTRAP, wowhead_anchor, wowhead_href,
)
from tools.wf_native_paid_reference_layout import gear_table, talent_section, apl_section


def test_wowhead_url_uses_source_id_and_enchant():
    assert wowhead_href("item", 11832, enchant_id=2504) == (
        "https://www.wowhead.com/forever/item=11832?ench=2504")
    assert wowhead_href("spell", 11711) == (
        "https://www.wowhead.com/forever/spell=11711")
    assert wowhead_href("item", 11832, edition="classic") == (
        "https://www.wowhead.com/classic/item=11832")
    for identifier in (None, False, True, "11832", 0, -1, 4.5):
        assert wowhead_href("item", identifier) is None
    assert wowhead_href("item", 11832, edition="retail") is None
    assert wowhead_href("talent", 11711) is None


def test_tooltip_anchor_safe_and_offline_content_remains():
    html = wowhead_anchor("item", 11832, '<img src=x onerror=alert(1)>', enchant_id=2504)
    assert '<img src=x' not in html
    assert '&lt;img src=x onerror=alert(1)&gt;' in html
    assert 'data-wowhead="ench=2504"' in html
    assert 'href="https://www.wowhead.com/forever/item=11832?ench=2504"' in html
    assert wowhead_anchor("spell", "11711", "Unverified") == "Unverified"
    assert 'wow.zamimg.com/js/tooltips.js' in WOWHEAD_BOOTSTRAP
    assert 'renameLinks:false' in WOWHEAD_BOOTSTRAP


def test_all_three_build_sections_have_actual_id_hover_links():
    row = {"talents": "210-0-0", "receipt": {"native_named_build": {
        "equipped_item_names_ids": [
            {"position": 0, "native_slot": "head", "item_id": 11832,
             "name": "Source Hat", "enchant_id": 2504}],
        "talent_names": [
            {"tree": "Affliction", "name": "Improved Corruption",
             "rank": 2, "max_rank": 5, "spell_id": 17810}],
        "ordered_apl_spells": [
            {"priority": 1, "name": "Bane of Agony",
             "spell_id": 11711, "condition": {"if": "target"}}],
    }}}
    assert "forever/item=11832?ench=2504" in gear_table(row)
    assert "forever/spell=17810" in talent_section(row)
    assert "forever/spell=11711" in apl_section(row)
    assert 'source="Not' not in gear_table(row)


def test_missing_talent_id_is_plain_text_not_guess():
    row = {"talents": "210-0-0", "receipt": {"native_named_build": {
        "talent_names": [
            {"tree": "Affliction", "name": "Improved Corruption",
             "rank": 2, "max_rank": 5}],
    }}}
    html = talent_section(row)
    assert "Improved Corruption" in html
    assert "wowhead.com" not in html
