"""Source-ID-only Wowhead links and optional live tooltip overlay.

Combat measurements stay in the verified native receipt. The official Wowhead
script enriches IDs in the user's browser when online; offline the saved HTML
still exposes the source item/spell name and a clickable reference URL.
"""
from __future__ import annotations

from html import escape


WOWHEAD_BOOTSTRAP = (
    '<script>const whTooltips={colorLinks:true,iconizeLinks:true,'
    'renameLinks:false};</script>'
    '<script async src="https://wow.zamimg.com/js/tooltips.js"></script>'
)


def _id(value: object) -> int | None:
    return value if type(value) is int and value > 0 else None


def wowhead_href(kind: str, identifier: object, *,
                 edition: str = "forever", enchant_id: object = None) -> str | None:
    """Only source-provided typed IDs; no name searches or Classic guesses."""
    ident = _id(identifier)
    if kind not in ("item", "spell") or edition not in ("forever", "classic") or ident is None:
        return None
    url = f"https://www.wowhead.com/{edition}/{kind}={ident}"
    enchant = _id(enchant_id)
    if kind == "item" and enchant is not None:
        url += f"?ench={enchant}"
    return url


def wowhead_anchor(kind: str, identifier: object, name: object, *,
                   edition: str = "forever", enchant_id: object = None) -> str:
    """Render ordinary HTML first, letting the optional Wowhead JS add overlays."""
    label = escape(str(name) if name is not None else "Unlabeled", quote=True)
    url = wowhead_href(kind, identifier, edition=edition, enchant_id=enchant_id)
    if url is None:
        return label
    attributes = ''
    ench = _id(enchant_id)
    if kind == "item" and ench is not None:
        attributes = f' data-wowhead="ench={ench}"'
    return ('<a class="wowhead-ref" href="' + escape(url, quote=True)
            + '" target="_blank" rel="noopener noreferrer"' + attributes
            + '>' + label + '</a>')
