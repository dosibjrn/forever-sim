from __future__ import annotations

"""Forever-wide beta facts and data-provenance helpers.

Only ruleset-level facts belong here. Class-specific spell/talent snapshots keep
an explicit provenance object in their own ``profile.py`` so mixed-build data
cannot hide behind a single global constant.
"""

from dataclasses import dataclass

RULESET = "forever"
EXPERIMENTAL = True
VERIFIED_LEVEL_CAP = 30
DEFAULT_DATA_QUALITY = (
    "experimental beta snapshot; unknown values must be explicit "
    "fallbacks/approximations"
)


@dataclass(frozen=True)
class DataProvenance:
    """Auditable origin metadata for one experimental class data snapshot."""

    build: str
    attribution: str
    quality: object = DEFAULT_DATA_QUALITY
    verified_level_cap: int = VERIFIED_LEVEL_CAP
    mixed_build: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "build": self.build,
            "attribution": self.attribution,
            "quality": self.quality,
            "verified_level_cap": int(self.verified_level_cap),
            "mixed_build": bool(self.mixed_build),
        }
