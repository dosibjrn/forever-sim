from __future__ import annotations

"""Conservative helpers for captured Wowhead Forever entities.

The web page is the evidence; these helpers intentionally do not pretend to
reverse-engineer every JavaScript listview payload.  They normalize explicit
captured facts and reject URL/ID disagreements.  Network acquisition belongs to
``tools/refresh_forever_wowhead_data.py``.
"""

from dataclasses import dataclass
import re
from typing import Any, Mapping

from ..provenance import stable_json_fingerprint, wowhead_id_from_url


@dataclass(frozen=True)
class CapturedWowheadEntity:
    entity_id: int
    entity_kind: str
    class_key: str
    name: str
    url: str
    captured: dict[str, Any]


def normalize_capture(raw: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(raw)
    url = str(data["url"])
    entity_id = int(data["entity_id"])
    parsed = wowhead_id_from_url(url)
    if parsed != entity_id:
        raise ValueError(f"Wowhead URL id {parsed!r} != captured id {entity_id}")
    name = str(data["name"]).strip()
    if not name:
        raise ValueError("Wowhead capture has blank entity name")
    captured = dict(data.get("captured") or {})
    return {
        "provider": "wowhead",
        "ruleset": "forever",
        "entity_kind": str(data.get("entity_kind") or "spell"),
        "entity_id": entity_id,
        "class_key": str(data["class_key"]).lower(),
        "name": name,
        "url": url,
        "captured": captured,
        "content_fingerprint": stable_json_fingerprint({"id": entity_id, "name": name, "url": url, "captured": captured}),
        "fingerprint_scope": "normalized_capture",
    }
