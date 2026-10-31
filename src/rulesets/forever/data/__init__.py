"""Pinned WoW Forever source data and source-identity helpers.

This package is deliberately runtime-offline.  Acquisition/refresh tools live
under ``tools/`` and ``data.importers``; simulation code loads pinned fixtures.
"""

from .catalogue import ForeverSourceCatalogue, default_catalogue
from .schema import EffectRecord, SourceRef, SpellRankRecord, TalentRecord, TalentRankRecord
from .rules import SourceRuleError, SourceRuleInterpreter, default_rules

__all__ = [
    "EffectRecord",
    "ForeverSourceCatalogue",
    "SourceRef",
    "SpellRankRecord",
    "TalentRankRecord",
    "TalentRecord",
    "default_catalogue",
    "SourceRuleError",
    "SourceRuleInterpreter",
    "default_rules",
]
