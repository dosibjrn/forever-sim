from __future__ import annotations

from src.rulesets.forever.items.wowhead_queries import all_canonical_bands
from tools.capture_wowhead import _detect_blocked


def test_capture_uses_exact_canonical_class_bands():
    bands = all_canonical_bands()
    assert len(bands) == 12
    assert {b.class_key for b in bands} == {"mage", "hunter", "druid", "paladin"}
    assert all("/forever/items/" in b.url for b in bands)
    assert all("?filter=161:195;1:1;0:0" in b.url for b in bands)


def test_capture_block_page_detection_rejects_common_challenges():
    assert _detect_blocked("<html><body>Access Denied</body></html>", "") == "access denied"
    assert _detect_blocked("<html><body>Just a moment...</body></html>", "") == "just a moment"
    assert _detect_blocked("<html><body>3,412 items found</body></html>", "Items - Wowhead") is None
