from __future__ import annotations

"""G49a: explicit, capability-gated Decision API backend selection.

No class-name special cases, no scoring fallback. The default may become
"generic" only after a provider declares product-complete *exact levels*.
"""

from src.game.data.forever.registry import generic_default_ready_levels, registered_class_keys
from src.class_registry import class_names

BACKENDS = frozenset(("legacy", "generic", "compare"))


def select_backend(*, requested: str | None = None,
                   class_key: str | None = None,
                   level: int | None = None) -> dict:
    name = str(requested).strip().lower() if requested is not None else ""
    if name and name not in BACKENDS:
        raise ValueError("backend must be one of: legacy, generic, compare")
    cls = str(class_key or "").strip().lower()
    lvl = int(level) if level is not None else 20
    eligible = bool(cls and lvl in generic_default_ready_levels(cls))
    if name:
        backend, mode, reason = name, "explicit", "explicit_backend_selection"
    elif eligible:
        backend, mode, reason = "generic", "automatic", "declared_product_complete_at_level"
    else:
        backend, mode, reason = "legacy", "automatic", "no_verified_generic_product_complete_class_level"
    return {
        "backend": backend, "mode": mode, "reason": reason,
        "class_name": cls or None, "level": lvl,
        "generic_default_eligible": eligible,
        "selectable_classes": sorted(set(class_names("forever", ui_visible=True)) | set(registered_class_keys())),
        "legacy_fallback": False,  # an automatic selection is not a runtime fallback
    }
