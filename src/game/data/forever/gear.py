from __future__ import annotations

"""Forever source bridge from scorer weights to legal named catalogue gear."""

from dataclasses import dataclass
from typing import Any, Mapping

from src.rulesets.forever.items.runtime_selection import (
    effective_level,
    item_payload,
    item_vector,
    select_gear,
    _source_class_profile,
)


# Source selector roles describe equipment package legality, not prescribed
# builds. Discovery may compare all compatible packages without a class-specific
# optimizer strategy.
_ROLES_BY_CLASS = {
    "druid": ("druid_balance", "druid_feral", "druid_bear"),
    "mage": ("mage",),
    "hunter": ("hunter",),
    "paladin": ("paladin_ret", "paladin_tank"),
}


def available_gear_roles(class_key: str) -> tuple[str, ...]:
    """Source profiles extend the generic gear bridge without class branches."""
    key=str(class_key).lower()
    profile=_source_class_profile(key)
    if profile and profile.get('gear_selection_roles'):
        return tuple(profile['gear_selection_roles'])
    return _ROLES_BY_CLASS.get(key, ())


_ROLE_BY_CLASS = {
    "druid": "druid_balance",
    "mage": "mage",
    "hunter": "hunter",
    "paladin": "paladin_ret",
}


@dataclass(frozen=True)
class NamedGearSelection:
    class_key: str
    role: str
    level: int
    slots: Mapping[str, Mapping[str, Any]]
    aggregate_stats: Mapping[str, float]
    selection_weights: Mapping[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "class_key": self.class_key,
            "role": self.role,
            "level": int(self.level),
            "item_count": len(self.slots),
            "slots": {str(k): dict(v) for k, v in self.slots.items()},
            "aggregate_stats": {str(k): float(v) for k, v in self.aggregate_stats.items()},
            "selection_weights": {str(k): float(v) for k, v in self.selection_weights.items()},
            "source": "canonical_sqlite_forever_catalogue",
        }


def select_named_gear(
    *,
    class_key: str,
    level: int,
    stat_weights: Mapping[str, float],
    required_level_policy: str = "catalogue",
    role: str | None = None,
    exclude_unknown_item_effects: bool = False,
) -> NamedGearSelection:
    key = str(class_key).lower()
    if role is None:
        roles=available_gear_roles(key)
        role=(_ROLE_BY_CLASS.get(key) or
              next((x for x in roles if x.endswith('_unrestricted')), None))
    else:
        role=str(role)
    if role not in available_gear_roles(key):
        raise ValueError(f"no Forever generic gear role bridge for {class_key!r}")
    weights = {str(k): max(0.0, float(v or 0.0)) for k, v in dict(stat_weights).items()}
    selected = select_gear(key, int(level), role, weights=weights,
                           required_level_policy=required_level_policy,
                           exclude_unknown_item_effects=exclude_unknown_item_effects)
    slots = {
        str(slot): item_payload(item, display_slot=str(slot), effective_level=effective_level(item))
        for slot, item in selected.items()
    }
    aggregate: dict[str, float] = {}
    for item in selected.values():
        for stat, value in item_vector(item).items():
            aggregate[stat] = float(aggregate.get(stat, 0.0)) + float(value or 0.0)
    return NamedGearSelection(
        class_key=key,
        role=role,
        level=int(level),
        slots=slots,
        aggregate_stats=aggregate,
        selection_weights=weights,
    )
