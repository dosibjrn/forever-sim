"""Backend-neutral source-name identity helpers.

Pure spelling normalization only. This is not a Warcraft legality, rank,
source-verification, or combat authority; those belong to MythicSim Rust.
"""

from __future__ import annotations

import re


def source_slug(value: str) -> str:
    """Preserve the original SQLite talent/source family-key normalization."""
    return re.sub(r'[^a-z0-9]+', '_', value.lower()).strip('_').replace("_s_", 's_')
