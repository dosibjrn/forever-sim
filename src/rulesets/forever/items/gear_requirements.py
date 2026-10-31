from __future__ import annotations

"""Shared gear-slot requirements and catalogue coverage classification.

Class plugins describe which display slots are meaningful and any class/setup
constraints. This module owns generic classification over the same legal
runtime catalogue rows consumed by gear selection. Listener/UI code must not
infer a catalogue gap merely from an empty selected slot.
"""

from dataclasses import dataclass
from typing import Mapping, Any

from .catalogue import ItemRecord
from .runtime_selection import BODY_SLOTS, available_items


COVERAGE_AVAILABLE = "available"
COVERAGE_NO_ITEM = "no_item"
COVERAGE_PROFICIENCY_BLOCKED = "proficiency_blocked"
COVERAGE_SETUP_BLOCKED = "setup_blocked"
COVERAGE_CATALOGUE_GAP = "catalogue_gap"
COVERAGE_QUERY_GAP = "query_gap"


@dataclass(frozen=True)
class SlotRequirement:
    display_slot: str
    source_slots: tuple[str, ...]
    weapon_types: frozenset[str] | None = None
    armor_types: frozenset[str] | None = None
    require_empty_weapon_type: bool = False
    blocked_reason: str | None = None
    blocked_status: str | None = None
    scorer_modeled: bool = True
    note: str | None = None


@dataclass(frozen=True)
class GearRequirements:
    class_key: str
    role: str
    slots: tuple[SlotRequirement, ...]


def _base_slots() -> list[SlotRequirement]:
    out = [SlotRequirement(slot, (slot,)) for slot in BODY_SLOTS]
    out += [
        SlotRequirement("ring1", ("finger",)),
        SlotRequirement("ring2", ("finger",)),
        SlotRequirement("trinket1", ("trinket",)),
        SlotRequirement("trinket2", ("trinket",)),
    ]
    return out


def _selected_field(selected: Mapping[str, Any], slot: str, field: str, default=None):
    item = (selected or {}).get(slot)
    if item is None:
        return default
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _selected_two_handed(selected: Mapping[str, Any] | None) -> bool:
    selected = selected or {}
    hands = int(_selected_field(selected, "weapon", "weapon_hands", 0) or 0)
    raw_slot = str(_selected_field(selected, "weapon", "slot", "") or "")
    catalogue_slot = str(_selected_field(selected, "weapon", "catalogue_slot", "") or "")
    return hands == 2 or raw_slot == "two_hand" or catalogue_slot == "two_hand"


def _nonshield_offhand(*, blocked_status: str | None = None, blocked_reason: str | None = None) -> SlotRequirement:
    return SlotRequirement(
        "offhand", ("off_hand",), armor_types=frozenset({"", "misc"}), require_empty_weapon_type=True,
        blocked_status=blocked_status, blocked_reason=blocked_reason,
    )


def druid_requirements(role: str, selected: Mapping[str, Any] | None = None) -> GearRequirements:
    role = str(role)
    selected = selected or {}
    slots = _base_slots()
    slots.append(SlotRequirement("weapon", ("one_hand", "main_hand", "two_hand")))
    if _selected_two_handed(selected):
        slots.append(_nonshield_offhand(
            blocked_status=COVERAGE_SETUP_BLOCKED,
            blocked_reason="selected two-handed weapon occupies both hands",
        ))
    else:
        slots.append(_nonshield_offhand())
    slots.append(SlotRequirement(
        "relic", ("relic",), scorer_modeled=False,
        note="canonical Druid relic candidates exist; relic special effects are not yet scorer-modeled",
    ))
    slots.append(SlotRequirement(
        "ranged", ("ranged",), blocked_status=COVERAGE_PROFICIENCY_BLOCKED,
        blocked_reason="Druid does not use a conventional ranged weapon slot",
    ))
    slots.append(SlotRequirement(
        "wand", ("ranged",), weapon_types=frozenset({"wand"}),
        blocked_status=COVERAGE_PROFICIENCY_BLOCKED, blocked_reason="Druid cannot equip wands",
    ))
    return GearRequirements(class_key="druid", role=role, slots=tuple(slots))


def mage_requirements(role: str, selected: Mapping[str, Any] | None = None) -> GearRequirements:
    selected = selected or {}
    slots = _base_slots()
    slots.append(SlotRequirement("weapon", ("one_hand", "main_hand", "two_hand")))
    if _selected_two_handed(selected):
        slots.append(_nonshield_offhand(
            blocked_status=COVERAGE_SETUP_BLOCKED,
            blocked_reason="selected two-handed weapon occupies both hands",
        ))
    else:
        slots.append(_nonshield_offhand())
    slots.append(SlotRequirement("wand", ("ranged",), weapon_types=frozenset({"wand"})))
    slots.append(SlotRequirement(
        "ranged", ("ranged",), blocked_status=COVERAGE_PROFICIENCY_BLOCKED,
        blocked_reason="Mage ranged slot is wand-only",
    ))
    slots.append(SlotRequirement(
        "relic", ("relic",), blocked_status=COVERAGE_PROFICIENCY_BLOCKED,
        blocked_reason="Mage cannot equip relics",
    ))
    return GearRequirements(class_key="mage", role=str(role), slots=tuple(slots))


def hunter_requirements(role: str, selected: Mapping[str, Any] | None = None) -> GearRequirements:
    selected = selected or {}
    slots = _base_slots()
    slots.append(SlotRequirement("weapon", ("one_hand", "main_hand", "two_hand")))
    if _selected_two_handed(selected):
        slots.append(_nonshield_offhand(
            blocked_status=COVERAGE_SETUP_BLOCKED,
            blocked_reason="selected two-handed melee stat stick occupies both hands",
        ))
    else:
        slots.append(_nonshield_offhand())
    slots.append(SlotRequirement("ranged", ("ranged",), weapon_types=frozenset({"bow", "crossbow", "gun"})))
    slots.append(SlotRequirement(
        "wand", ("ranged",), weapon_types=frozenset({"wand"}),
        blocked_status=COVERAGE_PROFICIENCY_BLOCKED, blocked_reason="Hunter cannot equip wands",
    ))
    slots.append(SlotRequirement(
        "relic", ("relic",), blocked_status=COVERAGE_PROFICIENCY_BLOCKED,
        blocked_reason="Hunter does not use a relic slot",
    ))
    return GearRequirements(class_key="hunter", role=str(role), slots=tuple(slots))


def paladin_requirements(role: str, selected: Mapping[str, Any] | None = None) -> GearRequirements:
    role = str(role)
    slots = _base_slots()
    if role == "paladin_ret":
        slots.append(SlotRequirement("weapon", ("two_hand",)))
        slots.append(SlotRequirement(
            "offhand", ("off_hand",), blocked_status=COVERAGE_SETUP_BLOCKED,
            blocked_reason="Retribution 2H setup occupies both hands",
        ))
    elif role == "paladin_tank":
        slots.append(SlotRequirement("weapon", ("one_hand", "main_hand")))
        slots.append(SlotRequirement("offhand", ("off_hand",), armor_types=frozenset({"shield"})))
    else:
        slots.append(SlotRequirement("weapon", ("one_hand", "main_hand", "two_hand")))
        slots.append(SlotRequirement("offhand", ("off_hand",)))
    slots.append(SlotRequirement(
        "relic", ("relic",), scorer_modeled=False,
        note="canonical Paladin relic candidates are visible; relic special effects are not yet scorer-modeled",
    ))
    slots.append(SlotRequirement(
        "ranged", ("ranged",), blocked_status=COVERAGE_PROFICIENCY_BLOCKED,
        blocked_reason="Paladin does not use a conventional ranged weapon slot",
    ))
    slots.append(SlotRequirement(
        "wand", ("ranged",), weapon_types=frozenset({"wand"}),
        blocked_status=COVERAGE_PROFICIENCY_BLOCKED, blocked_reason="Paladin cannot equip wands",
    ))
    return GearRequirements(class_key="paladin", role=role, slots=tuple(slots))


def requirements_for(class_key: str, role: str, selected: Mapping[str, Any] | None = None) -> GearRequirements:
    class_key = str(class_key).lower()
    factories = {
        "druid": druid_requirements,
        "mage": mage_requirements,
        "hunter": hunter_requirements,
        "paladin": paladin_requirements,
    }
    try:
        return factories[class_key](role, selected)
    except KeyError:
        raise KeyError(f"shared gear requirements not migrated for class {class_key!r}") from None


def _matches(req: SlotRequirement, item: ItemRecord) -> bool:
    if str(item.slot) not in req.source_slots:
        return False
    if req.weapon_types is not None and str(item.weapon_type or "") not in req.weapon_types:
        return False
    if req.armor_types is not None and str(item.armor_type or "") not in req.armor_types:
        return False
    if req.require_empty_weapon_type and str(item.weapon_type or ""):
        return False
    return True


def catalogue_coverage(
    requirements: GearRequirements,
    *,
    level: int,
    selected: Mapping[str, Any] | None = None,
) -> dict[str, dict]:
    """Classify display slots against the production legal item pool."""
    selected = selected or {}
    rows = available_items(requirements.class_key, int(level))
    out: dict[str, dict] = {}
    for req in requirements.slots:
        candidates = tuple(x for x in rows if _matches(req, x))
        selected_item = selected.get(req.display_slot)
        if req.blocked_status:
            status = req.blocked_status
        elif selected_item is not None or candidates:
            status = COVERAGE_AVAILABLE
        else:
            status = COVERAGE_CATALOGUE_GAP
        out[req.display_slot] = {
            "status": status,
            "candidate_count": len(candidates),
            "selected": selected_item is not None,
            "scorer_modeled": bool(req.scorer_modeled),
            "source_slots": list(req.source_slots),
            "reason": req.blocked_reason,
            "note": req.note,
        }
    return out


def candidate_counts_from_coverage(coverage: Mapping[str, Mapping]) -> dict[str, int]:
    return {str(slot): int(meta.get("candidate_count", 0) or 0) for slot, meta in coverage.items()}


def enrich_catalogue_metadata(
    gear: dict,
    *,
    class_key: str,
    role: str,
    level: int,
    selected: Mapping[str, Any] | None = None,
) -> dict:
    """Attach one production catalogue-coverage contract to a gear snapshot."""
    selected = selected or {}
    coverage = catalogue_coverage(
        requirements_for(class_key, role, selected), level=int(level), selected=selected,
    )
    gear["catalogue_coverage"] = coverage
    gear["catalogue_candidate_counts"] = candidate_counts_from_coverage(coverage)
    gear["catalogue_coverage_authority"] = "shared_gear_requirements_v1"
    return gear
