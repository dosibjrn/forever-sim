from __future__ import annotations

"""Representative *normal leveling gear* curves for Forever Paladin.

This is intentionally not a literal BIS/loot optimizer.  Audited Forever profession
families provide real per-slot samples.  v0.11.29 keeps the equipment state
discrete: a slot contains a named audited item or it is absent; real items are
carried forward until a later real sample replaces them.  Weapon/shield samples
use the same sample-and-hold rule instead of interpolated pseudo-items.

Reference sanity anchors used when choosing the level-20 neighborhood include
roughly 19.7 DPS for an attainable level-18 2H, 15.5-16.7 DPS for level-19/21
1H weapons, and ~500-600 shield armor around level 17-21.  These references are
not treated as canonical ruleset data and do not imply the character owns any
particular item.
"""

from dataclasses import asdict, dataclass, replace
from typing import Mapping

from src.rulesets.forever.items.gear_requirements import enrich_catalogue_metadata
from src.rulesets.forever.items.runtime_selection import (
    available_items as catalogue_available_items, effective_level as catalogue_effective_level,
    item_payload as catalogue_item_payload, item_vector as catalogue_item_vector,
    select_gear as catalogue_select_gear,
)
from src.rulesets.forever.shared.crafted_itemization import (
    CRAFTED_ITEMS, PALADIN_RET_SLOT_PROGRESSION, PALADIN_TANK_SLOT_PROGRESSION,
    aggregate_items, item as crafted_item, paladin_holy_items, paladin_ret_items,
    paladin_role_slot_candidates, paladin_tank_items,
)


@dataclass(frozen=True)
class GearSetup:
    name: str
    weapon_style: str
    weapon_speed: float
    weapon_dps: float
    item_armor: float
    shield_armor: float
    shield_block_value: float
    strength_bonus: float
    stamina_bonus: float
    intellect_bonus: float
    spirit_bonus: float
    mp5_bonus: float
    spell_damage_bonus: float
    healing_bonus: float
    defense_bonus: float = 0.0
    calibration: str = "legacy_smooth"
    crafted_items: tuple[str, ...] = ()
    weapon_anchor: str = ""
    modeled_level: int = 0
    selected_body_items: tuple[str, ...] = ()
    gear_selection_method: str = "baseline_family"
    selection_weight_snapshot: tuple[tuple[str, float], ...] = ()
    selected_catalogue_items: tuple[tuple[str, int], ...] = ()

    @property
    def has_shield(self) -> bool:
        return self.weapon_style == "1h_shield"

    def as_dict(self) -> dict:
        return asdict(self)

    def with_delta(self, stat: str, amount: float) -> "GearSetup":
        """Return a local stat-weight probe without mutating the gear curve."""
        aliases = {
            "strength": "strength_bonus",
            "stamina": "stamina_bonus",
            "intellect": "intellect_bonus",
            "spirit": "spirit_bonus",
            "mp5": "mp5_bonus",
            "spell_power": "spell_damage_bonus",
            "spell_damage": "spell_damage_bonus",
            "healing": "healing_bonus",
            "armor": "item_armor",
            "shield_armor": "shield_armor",
            "block_value": "shield_block_value",
            "weapon_dps": "weapon_dps",
            "defense": "defense_bonus",
        }
        field = aliases.get(stat, stat)
        if field not in self.__dataclass_fields__:
            raise KeyError(stat)
        return replace(self, **{field: float(getattr(self, field)) + float(amount)})



# Current Forever crafted/current-client weapon anchors.  Weapon DPS and speed
# are deliberately separated from armor/stat calibration because 1H+shield and
# slow 2H use the same body budget very differently in the combat model.
# Values are normal/craft reference points, not a claim of automatic ownership.
_WEAPON_ANCHORS: dict[str, dict[int, tuple[float, float, str]]] = {
    "2h_normal": {
        10: (7.20, 2.50, "Planting Shovel"),
        # Current Forever low-level weapon frontier.  L20 is the Paladin class
        # quest tier: Wolfsbane (Horde) and Verigan's Fist (Alliance) are both
        # ~25.6 DPS; the generic field uses the slower Horde sample because
        # weapon speed is mechanically relevant to seals.
        15: (20.50, 3.00, "Forsaken Greataxe"),
        # Horde/default representative for the class-quest tier.  Alliance has
        # Verigan's Fist as the corresponding real quest weapon; the generic
        # runtime must still equip one literal item rather than a composite name.
        20: (25.59, 3.40, "Wolfsbane"),
        29: (28.95, 3.80, "Corpsemaker"),
        38: ((91 + 137) / 2 / 3.50, 3.50, "Mithril Warhammer"),
        40: ((106 + 158) / 2 / 3.80, 3.80, "Mithril Claymore"),
        43: ((99 + 148) / 2 / 3.30, 3.30, "Charged Mithril Battleaxe"),
        50: ((137 + 205) / 2 / 3.60, 3.60, "Thorium Greatmace"),
        58: ((155 + 233) / 2 / 3.60, 3.60, "Stormcarver"),
        60: ((162 + 244) / 2 / 3.30, 3.30, "Forest Defender's Axe"),
    },
    "1h_shield_normal": {
        10: (5.50, 2.40, "Roofing Hammer"),
        17: (14.62, 2.60, "Scepter of the Abandoned"),
        19: (15.22, 2.30, "Pathfinder's Clearway"),
        33: ((36 + 67) / 2 / 2.50, 2.50, "Iron Morningstar"),
        60: ((80 + 148) / 2 / 2.40, 2.40, "Ironwood Blade"),
    },
}

# Exact source identity for listener/tooltips when the audited weapon sample is
# known.  Keep this separate from the numeric anchor tuple so combat data and
# provenance can evolve independently.
_WEAPON_SOURCE_URLS: dict[str, str] = {
    "Wolfsbane": "https://www.wowhead.com/forever/item=267369/wolfsbane",
}

# Evergreen Shield is an exact current crafted L60 endpoint.  Intermediate
# values are a calibration bridge from the existing L30 shield anchor; block
# value remains the old smooth proxy because the current sources do not expose
# a comparable block-value ladder.
# Stats on the weapon/shield samples are kept separate from DPS/speed.  For
# stats we use the latest actually-observed item at or below the level (no
# interpolation between different item stat profiles).
_WEAPON_STAT_FLOORS: dict[str, dict[int, dict[str, float]]] = {
    "2h_normal": {
        10: {"strength": 1.0},
        15: {"strength": 8.0, "stamina": 4.0},
        # Wolfsbane: +9 Sta/+10 Int.  Its on-hit proc is deliberately not valued
        # here because the public tooltip does not expose a reliable proc rate.
        20: {"stamina": 9.0, "intellect": 10.0},
        29: {"strength": 15.0, "stamina": 8.0},
        38: {"strength": 9.0},
        40: {"strength": 9.0, "stamina": 15.0},
        43: {"strength": 14.0, "spell_power": 15.0},
        50: {"strength": 21.0, "spell_power": 23.0},
        58: {"strength": 15.0, "stamina": 11.0, "spell_power": 32.0},
        60: {"strength": 18.0, "stamina": 27.0, "spell_power": 28.0},
    },
    "1h_shield_normal": {
        10: {"spirit": 1.0},
        17: {"strength": 5.0},
        19: {"stamina": 3.0, "intellect": 4.0},
        33: {"strength": 4.0, "spell_power": 5.0},
        60: {"strength": 8.0, "stamina": 12.0},
    },
}
_SHIELD_STAT_FLOORS: dict[int, dict[str, float]] = {
    11: {},
    19: {"spell_power": 4.0},  # Seedcloud Buckler, current Forever tooltip
    36: {"stamina": 13.0, "spirit": 7.0},  # The Green Tower
    39: {"strength": 7.0, "stamina": 8.0},  # Aegis of the Scarlet Commander
    60: {"stamina": 16.0, "spell_power": 7.0, "healing": 22.0},  # Evergreen Shield
}
_SHIELD_ARMOR_ANCHORS = {11: 311.0, 19: 547.0, 36: 1308.0, 39: 1548.0, 60: 2468.0}
_SHIELD_BLOCK_ANCHORS = {11: 5.0, 19: 11.0, 36: 25.0, 39: 23.0, 60: 44.0}
_SHIELD_NAMES = {
    11: "Salvaged Wooden Tower Shield",
    19: "Seedcloud Buckler",
    36: "The Green Tower",
    39: "Aegis of the Scarlet Commander",
    60: "Evergreen Shield",
}


# Continuous body field.  Unlike the old aggregate-remainder decomposition,
# each slot is derived only from real samples of that same slot.  We permit a
# short backwards projection (useful for e.g. a L20 head from a L25 head anchor)
# but refuse to synthesize a slot whose first real sample is far in the future.
# Slots with no audited same-slot samples remain explicitly missing.
_BODY_FIELD_STATS = (
    "strength", "stamina", "intellect", "spirit", "mp5",
    "spell_power", "healing", "defense",
)
_BODY_FIELD_GROWTH_EXPONENT = 1.0
_BODY_FIELD_MAX_BACKWARD_LEVELS = 10

_ROLE_PROGRESSIONS = {
    "2h_normal": PALADIN_RET_SLOT_PROGRESSION,
    "1h_shield_normal": PALADIN_TANK_SLOT_PROGRESSION,
}

# Full listener-facing body/accessory surface.  Some slots intentionally have no
# model yet; keeping them in the gap list makes sparse catalogue coverage
# explicit instead of letting absent gear disappear from audits.
_LISTENER_BODY_SLOTS = (
    "head", "neck", "shoulder", "back", "chest", "wrist", "hands",
    "waist", "legs", "feet", "ring1", "ring2", "trinket1", "trinket2",
)


def _role_slot_samples(style: str, slot: str):
    progression = _ROLE_PROGRESSIONS[style]
    names = set(progression.get(str(slot), ()))
    return tuple(x for x in CRAFTED_ITEMS if x.name in names and x.slot == str(slot))


def _body_field_rows(style: str, level: int) -> tuple[dict, ...]:
    """Latest literal role-family item per slot at this level.

    No interpolation, extrapolation or backwards projection is allowed here.
    Sparse catalogue coverage stays sparse and therefore visible.
    """
    rows = _default_body_rows(style, int(level))
    return tuple(_item_as_field_row(x, level=int(level), source_type="audited named item") for x in rows)


def _aggregate_dict_rows(rows) -> dict:
    totals = {stat: 0.0 for stat in _BODY_FIELD_STATS}
    totals["armor"] = 0.0
    for row in rows:
        for stat in _BODY_FIELD_STATS:
            totals[stat] += float(row.get(stat, 0.0) or 0.0)
        totals["armor"] += float(row.get("armor", 0.0) or 0.0)
    return totals


def _aggregate_body_field(style: str, level: int) -> dict:
    rows = _body_field_rows(style, int(level))
    totals = _aggregate_dict_rows(rows)
    totals["rows"] = rows
    return totals


def _latest_stat_floor(rows: Mapping[int, Mapping[str, float]], level: int) -> dict[str, float]:
    eligible=[l for l in rows if l <= int(level)]
    if not eligible:
        return {}
    return dict(rows[max(eligible)])


def _latest_scalar_sample(points: Mapping[int, float], level: int) -> float:
    """Return the latest real scalar sample available at ``level``."""
    eligible=[x for x in points if x <= int(level)]
    if not eligible:
        return 0.0
    return float(points[max(eligible)])


def _weapon_reference(style: str, level: int) -> tuple[float, float, str]:
    """Latest real named weapon sample at or below ``level``."""
    rows=_WEAPON_ANCHORS[style]
    eligible=[x for x in rows if x <= int(level)]
    if not eligible:
        return 0.0, 0.0, ""
    return rows[max(eligible)]


def _default_body_rows(style: str, level: int):
    """Latest literal role-family items available at this level (audit helper)."""
    return paladin_ret_items(level) if style == "2h_normal" else paladin_tank_items(level)


def _item_as_field_row(row, *, level: int | None = None, source_type: str = "audited named item") -> dict:
    modeled_level = int(level if level is not None else row.required_level)
    return {
        "slot": row.slot, "name": row.name,
        "source_type": source_type, "source": row.profession,
        "source_url": row.source_url,
        "effective_level": int(row.required_level), "modeled_level": modeled_level,
        "modeled": False, "model_kind": (
            "observed_anchor" if modeled_level == int(row.required_level) else "carried_forward_real_item"
        ),
        "armor": float(row.armor), "strength": float(row.strength),
        "stamina": float(row.stamina), "intellect": float(row.intellect),
        "spirit": float(row.spirit), "mp5": float(getattr(row, "mp5", 0.0)), "spell_power": float(row.damage_power),
        "healing": float(row.healing), "defense": float(row.defense),
        "anchor_low": row.name, "anchor_high": row.name,
        "anchor_low_level": int(row.required_level), "anchor_high_level": int(row.required_level),
    }


def _body_rows_for_gear(gear: GearSetup, level: int) -> tuple[dict, ...]:
    """Exact body vectors used by combat, including named reroll overrides."""
    level = int(level)
    base = {str(x["slot"]): dict(x) for x in _body_field_rows(gear.name, level)}
    for name in gear.selected_body_items:
        row = crafted_item(str(name))
        base[row.slot] = _item_as_field_row(
            row, level=level, source_type="sampled per-level analytic choice"
        )
    # Selected audited accessories can occupy slots absent from the sparse
    # profession baseline, so render/sum the full listener surface rather than
    # only the role-family progression keys.
    order = list(_LISTENER_BODY_SLOTS)
    return tuple(base[s] for s in order if s in base)


def _row_stat(row, stat: str) -> float:
    if isinstance(row, Mapping):
        if stat in ("spell_power", "spell_damage"):
            return float(row.get("spell_power", row.get("spell_damage", 0.0)) or 0.0)
        return float(row.get(stat, 0.0) or 0.0)
    if stat in ("spell_power", "spell_damage"):
        return float(row.damage_power)
    return float(getattr(row, stat, 0.0) or 0.0)


def _item_utility(row, stat_values: Mapping[str, float]) -> float:
    aliases = {
        "strength": _row_stat(row, "strength"),
        "stamina": _row_stat(row, "stamina"),
        "intellect": _row_stat(row, "intellect"),
        "spirit": _row_stat(row, "spirit"),
        "mp5": _row_stat(row, "mp5"),
        "spell_power": _row_stat(row, "spell_power"),
        "spell_damage": _row_stat(row, "spell_power"),
        "healing": _row_stat(row, "healing"),
        "defense": _row_stat(row, "defense"),
        "armor": _row_stat(row, "armor"),
    }
    return sum(float(stat_values.get(stat, 0.0) or 0.0) * amount for stat, amount in aliases.items())


def _catalogue_selected_rows(gear: GearSetup) -> dict[str, object]:
    ids={slot:int(item_id) for slot,item_id in gear.selected_catalogue_items}
    if not ids:
        return {}
    rows={x.item_id:x for x in catalogue_available_items("paladin",int(gear.modeled_level or 1))}
    return {slot:rows[item_id] for slot,item_id in ids.items() if item_id in rows}


def _gear_from_catalogue_selection(
    style: str, level: int, selected: Mapping[str, object], *,
    selection_method: str="catalogue_role_baseline_v1",
    selection_weights: Mapping[str,float] | None=None,
) -> GearSetup:
    level=int(level)
    vals=dict(
        weapon_speed=0.0,weapon_dps=0.0,item_armor=0.0,shield_armor=0.0,shield_block_value=0.0,
        strength_bonus=0.0,stamina_bonus=0.0,intellect_bonus=0.0,spirit_bonus=0.0,
        mp5_bonus=0.0,spell_damage_bonus=0.0,healing_bonus=0.0,defense_bonus=0.0,
    )
    body_names=[]
    for slot,item in selected.items():
        v=catalogue_item_vector(item)
        vals["strength_bonus"]+=v["strength"]; vals["stamina_bonus"]+=v["stamina"]
        vals["intellect_bonus"]+=v["intellect"]; vals["spirit_bonus"]+=v["spirit"]
        vals["mp5_bonus"]+=v["mp5"]; vals["spell_damage_bonus"]+=v["spell_power"]
        vals["healing_bonus"]+=v["healing"]
        # defrtng/dodgertng are ratings in the catalogue, not Defense skill or
        # avoidance percentages. Keep them in listener rows until conversion is verified.
        if slot=="weapon":
            vals["weapon_dps"]=float(item.weapon_dps); vals["weapon_speed"]=float(item.weapon_speed)
        elif slot=="offhand" and item.armor_type=="shield":
            vals["shield_armor"]+=v["armor"]
        else:
            vals["item_armor"]+=v["armor"]
        if slot not in {"weapon","offhand"}: body_names.append(item.name)
    weapon=selected.get("weapon")
    return GearSetup(
        name=style,weapon_style=("2h" if style=="2h_normal" else "1h_shield"),
        calibration="canonical SQLite role selection; no curated item-stat fallback",
        crafted_items=tuple(body_names),weapon_anchor=(weapon.name if weapon is not None else ""),
        modeled_level=level,selected_body_items=tuple(body_names),
        gear_selection_method=str(selection_method),
        selection_weight_snapshot=tuple(sorted((str(k),float(v)) for k,v in (selection_weights or {}).items())),
        selected_catalogue_items=tuple((str(slot),int(item.item_id)) for slot,item in selected.items()),
        **vals,
    )


def apply_body_item_names(
    gear: GearSetup, level: int, names, *,
    selection_method: str="per_level_analytic_sqlite_slot_reroll_v2",
    selection_weights: Mapping[str,float] | None=None,
) -> GearSetup:
    """Replay/overlay published body item names using canonical SQLite rows."""
    level=int(level)
    selected=dict(_catalogue_selected_rows(gear))
    rows=catalogue_available_items("paladin",level)
    by_name={x.name:x for x in rows}
    for name in names:
        item=by_name.get(str(name))
        if item is None:
            raise KeyError(f"published Paladin item not present in canonical catalogue: {name}")
        slot=item.slot
        if slot=="finger":
            # Preserve a deterministic two-ring surface when replaying names.
            used={v.item_id for k,v in selected.items() if k in {"ring1","ring2"}}
            target="ring1" if "ring1" not in selected or selected.get("ring1").item_id in used and selected.get("ring1").name==name else "ring2"
            if selected.get("ring1") and selected["ring1"].name==name: target="ring1"
            elif selected.get("ring2") and selected["ring2"].name==name: target="ring2"
            elif "ring1" in selected and "ring2" not in selected: target="ring2"
            selected[target]=item
        elif slot=="trinket":
            if selected.get("trinket1") and selected["trinket1"].name==name: target="trinket1"
            elif selected.get("trinket2") and selected["trinket2"].name==name: target="trinket2"
            elif "trinket1" not in selected: target="trinket1"
            else: target="trinket2"
            selected[target]=item
        elif slot in {"one_hand","main_hand","two_hand"}:
            selected["weapon"]=item
        elif slot=="off_hand": selected["offhand"]=item
        else: selected[slot]=item
    return _gear_from_catalogue_selection(gear.name,level,selected,selection_method=selection_method,selection_weights=selection_weights)


def reroll_body_items(gear: GearSetup, level: int, stat_values: Mapping[str, float]) -> GearSetup:
    """Re-evaluate every body/accessory slot from the full SQL candidate pool."""
    level=int(level)
    role="paladin_ret" if gear.name=="2h_normal" else "paladin_tank"
    dynamic=catalogue_select_gear("paladin",level,role,weights=stat_values)
    selected=dict(_catalogue_selected_rows(gear))
    for slot,item in dynamic.items():
        if slot not in {"weapon","offhand"}: selected[slot]=item
    return _gear_from_catalogue_selection(
        gear.name,level,selected,selection_method="per_level_analytic_sqlite_slot_reroll_v2",selection_weights=stat_values
    )


def _interp(style: str, level: int) -> GearSetup:
    if style not in {"2h_normal","1h_shield_normal"}: raise KeyError(style)
    level=int(level)
    role="paladin_ret" if style=="2h_normal" else "paladin_tank"
    selected=catalogue_select_gear("paladin",level,role)
    if "weapon" not in selected:
        raise RuntimeError(f"canonical catalogue has no legal Paladin weapon for {style} at level {level}")
    if style=="1h_shield_normal" and "offhand" not in selected:
        raise RuntimeError(f"canonical catalogue has no legal Paladin shield at level {level}")
    return _gear_from_catalogue_selection(style,level,selected)


def archetypes(level: int) -> tuple[GearSetup, ...]:
    """Exactly one normal-quality curve per equipment style."""
    return (_interp("2h_normal", level), _interp("1h_shield_normal", level))


def _listener_stat_summary(row: Mapping[str, object]) -> str:
    """Compact, explicit stat vector for listener/audit surfaces."""
    fields = (
        ("strength", "Str"), ("stamina", "Sta"), ("intellect", "Int"),
        ("spirit", "Spi"), ("spell_power", "SP"), ("healing", "Heal"),
        ("defense", "Def"), ("armor", "armor"), ("block_value", "block"),
        ("mp5", "mp5"), ("spell_hit", "hit%"), ("spell_crit", "crit%"),
        ("wand_dps", "wand dps"), ("weapon_dps", "weapon dps"),
        ("weapon_speed", "speed"),
    )
    parts=[]
    for key,label in fields:
        try:
            value=float(row.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if abs(value) > 1e-12:
            parts.append(f"{label} {value:.2f}".rstrip("0").rstrip("."))
    return " · ".join(parts) or "no numeric contribution"


def gear_snapshot(gear: GearSetup) -> dict:
    """Stable JSON-friendly decomposition of discrete named Paladin gear.

    Every displayed row is a literal audited named item. Sparse slots remain
    missing and an existing real item is carried forward until a real sampled
    replacement becomes available. The displayed slot vectors are the same
    vectors summed into combat.
    """
    out = gear.as_dict()
    level = max(1, int(getattr(gear, "modeled_level", 0) or 0))
    if gear.selected_catalogue_items:
        selected=_catalogue_selected_rows(gear)
        slots={}; items=[]
        for slot,item in selected.items():
            row=catalogue_item_payload(item,display_slot=slot,effective_level=catalogue_effective_level(item))
            if slot=="offhand" and item.armor_type=="shield":
                row["block_value"]=0.0
                row["block_value_status"]="not present in current listview catalogue; no synthetic fallback"
            row["stat_summary"]=_listener_stat_summary(row)
            slots[slot]=row; items.append(row)
        blocked=["offhand"] if gear.weapon_style=="2h" else []
        body_slots=set(_LISTENER_BODY_SLOTS)
        missing=[x for x in _LISTENER_BODY_SLOTS if x not in slots]
        slot_totals={
            "strength":sum(float(x.get("strength",0) or 0) for x in items),
            "stamina":sum(float(x.get("stamina",0) or 0) for x in items),
            "intellect":sum(float(x.get("intellect",0) or 0) for x in items),
            "spirit":sum(float(x.get("spirit",0) or 0) for x in items),
            "mp5":sum(float(x.get("mp5",0) or 0) for x in items),
            "spell_power":sum(float(x.get("spell_power",0) or 0) for x in items),
            "healing":sum(float(x.get("healing",0) or 0) for x in items),
            "defense":0.0,
            "body_armor":sum(float(x.get("armor",0) or 0) for x in items if x.get("slot") not in {"weapon","offhand"}),
            "shield_armor":float((slots.get("offhand") or {}).get("armor",0) or 0) if gear.weapon_style!="2h" else 0.0,
            "block_value":0.0,
            "weapon_dps":float((slots.get("weapon") or {}).get("weapon_dps",0) or 0),
            "weapon_speed":float((slots.get("weapon") or {}).get("weapon_speed",0) or 0),
        }
        combat_totals={
            "strength":float(gear.strength_bonus),"stamina":float(gear.stamina_bonus),"intellect":float(gear.intellect_bonus),
            "spirit":float(gear.spirit_bonus),"mp5":float(gear.mp5_bonus),"spell_power":float(gear.spell_damage_bonus),
            "healing":float(gear.healing_bonus),"defense":float(gear.defense_bonus),"body_armor":float(gear.item_armor),
            "shield_armor":float(gear.shield_armor),"block_value":float(gear.shield_block_value),
            "weapon_dps":float(gear.weapon_dps),"weapon_speed":float(gear.weapon_speed),
        }
        delta={k:slot_totals[k]-combat_totals[k] for k in combat_totals}
        out.update({
            "slots":slots,"items":items,"blocked_slots":blocked,"hand_setup":("2H" if gear.weapon_style=="2h" else "1H + shield"),
            "availability_rule":"canonical SQLite class eligibility + observed reqlevel + robust ilvl lower-bound floor",
            "item_field_scope":"canonical SQLite items only; no curated/hardcoded item-stat fallback",
            "gear_selection_method":gear.gear_selection_method,"selected_body_items":list(gear.selected_body_items),
            "selection_weight_snapshot":dict(gear.selection_weight_snapshot),"inventory_continuity":False,
            "body_field_method":"canonical_sqlite_runtime_selection_v1","body_field_sample_count":len([s for s in slots if s in body_slots]),
            "body_field_modeled_slots":[],"body_field_missing_slots":missing,
            "slot_totals":slot_totals,"combat_totals":combat_totals,"reconciliation_delta":delta,
            "reconciliation_ok":max((abs(v) for v in delta.values()),default=0.0)<=1e-8,
            "reconciliation_max_abs_delta":max((abs(v) for v in delta.values()),default=0.0),
            "catalogue_mode":"sqlite_runtime_authority",
            "rating_conversion_status":"raw ratings shown per item but not converted to combat skill/percent",
            "shield_block_value_status":"current listview capture lacks block value; combat uses 0 rather than a synthetic item stat",
        })
        role = "paladin_ret" if gear.weapon_style == "2h" else "paladin_tank"
        enrich_catalogue_metadata(out, class_key="paladin", role=role, level=level, selected=selected)
        return out
    body_rows = _body_rows_for_gear(gear, level)
    slots: dict[str, dict] = {}
    items: list[dict] = []
    represented = {
        "strength": 0.0, "stamina": 0.0, "intellect": 0.0, "spirit": 0.0, "mp5": 0.0,
        "spell_power": 0.0, "healing": 0.0, "defense": 0.0, "armor": 0.0,
    }

    def add(row: dict) -> None:
        row = dict(row)
        row["stat_summary"] = _listener_stat_summary(row)
        slots[str(row["slot"])] = row
        items.append(row)
        for stat in represented:
            represented[stat] += float(row.get(stat, 0.0) or 0.0)

    # Body rows are the exact named-item vectors consumed by combat.
    for row in body_rows:
        add(row)

    # Discrete weapon sample-and-hold.  The item name and stats are always from
    # one actual sampled weapon; no in-between pseudo-weapon is materialized.
    eligible_weapon_levels = [x for x in _WEAPON_ANCHORS[gear.name] if x <= level]
    weapon_sample_level = max(eligible_weapon_levels) if eligible_weapon_levels else None
    if weapon_sample_level is not None:
        weapon_name = _WEAPON_ANCHORS[gear.name][weapon_sample_level][2]
        wstats = _latest_stat_floor(_WEAPON_STAT_FLOORS[gear.name], level)
        weapon = {
            "slot": "weapon", "name": weapon_name,
            "source_type": "audited named weapon sample", "source": weapon_name,
            "source_url": _WEAPON_SOURCE_URLS.get(weapon_name),
            "effective_level": weapon_sample_level, "modeled_level": level, "modeled": False,
            "weapon_dps": float(gear.weapon_dps), "weapon_speed": float(gear.weapon_speed),
            "strength": float(wstats.get("strength", 0.0)), "stamina": float(wstats.get("stamina", 0.0)),
            "intellect": float(wstats.get("intellect", 0.0)), "spirit": float(wstats.get("spirit", 0.0)),
            "mp5": float(wstats.get("mp5", 0.0)), "spell_power": float(wstats.get("spell_power", 0.0)),
            "healing": float(wstats.get("healing", 0.0)), "defense": float(wstats.get("defense", 0.0)),
            "anchor_low": weapon_name, "anchor_high": weapon_name,
            "anchor_low_level": weapon_sample_level, "anchor_high_level": weapon_sample_level,
            "model_kind": ("observed_anchor" if level == weapon_sample_level else "carried_forward_real_item"),
        }
        add(weapon)

    blocked = []
    if gear.weapon_style == "2h":
        if weapon_sample_level is None:
            raise RuntimeError(f"missing named 2H weapon sample at level {level}")
        blocked.append("offhand")
        hand_setup = "2H"
    else:
        eligible_shield_levels = [x for x in _SHIELD_NAMES if x <= level]
        shield_sample_level = max(eligible_shield_levels) if eligible_shield_levels else None
        if shield_sample_level is not None:
            sstats = _latest_stat_floor(_SHIELD_STAT_FLOORS, level)
            shield_name = _SHIELD_NAMES[shield_sample_level]
            shield = {
                "slot": "offhand", "name": shield_name,
                "source_type": "audited named shield sample", "source": shield_name,
                "effective_level": shield_sample_level, "modeled_level": level, "modeled": False,
                "armor": float(gear.shield_armor), "block_value": float(gear.shield_block_value),
                "strength": float(sstats.get("strength", 0.0)), "stamina": float(sstats.get("stamina", 0.0)),
                "intellect": float(sstats.get("intellect", 0.0)), "spirit": float(sstats.get("spirit", 0.0)),
                "mp5": float(sstats.get("mp5", 0.0)), "spell_power": float(sstats.get("spell_power", 0.0)), "healing": float(sstats.get("healing", 0.0)),
                "defense": float(sstats.get("defense", 0.0)),
                "model_kind": ("observed_anchor" if level == shield_sample_level else "carried_forward_real_item"),
                "anchor_low": shield_name, "anchor_high": shield_name,
                "anchor_low_level": shield_sample_level, "anchor_high_level": shield_sample_level,
            }
            shield["stat_summary"] = _listener_stat_summary(shield)
            slots["offhand"] = shield
            items.append(shield)
            for stat in ("strength", "stamina", "intellect", "spirit", "mp5", "spell_power", "healing", "defense"):
                represented[stat] += float(shield.get(stat, 0.0) or 0.0)
        if weapon_sample_level is None:
            raise RuntimeError(f"missing named 1H weapon sample at level {level}")
        hand_setup = "1H + shield" if shield_sample_level is not None else "1H (no named shield yet)"

    # Listener/debug reconciliation: displayed slot vectors must reproduce the
    # exact aggregate GearSetup consumed by combat.
    slot_totals = {
        stat: sum(float(x.get(stat, 0.0) or 0.0) for x in items)
        for stat in ("strength", "stamina", "intellect", "spirit", "mp5", "spell_power", "healing", "defense")
    }
    slot_totals.update({
        "body_armor": sum(float(x.get("armor", 0.0) or 0.0) for x in items if x.get("slot") != "offhand"),
        "shield_armor": float((slots.get("offhand") or {}).get("armor", 0.0) or 0.0),
        "block_value": float((slots.get("offhand") or {}).get("block_value", 0.0) or 0.0),
        "weapon_dps": float((slots.get("weapon") or {}).get("weapon_dps", 0.0) or 0.0),
        "weapon_speed": float((slots.get("weapon") or {}).get("weapon_speed", 0.0) or 0.0),
    })
    combat_totals = {
        "strength": float(gear.strength_bonus), "stamina": float(gear.stamina_bonus),
        "intellect": float(gear.intellect_bonus), "spirit": float(gear.spirit_bonus),
        "mp5": float(gear.mp5_bonus), "spell_power": float(gear.spell_damage_bonus), "healing": float(gear.healing_bonus),
        "defense": float(gear.defense_bonus), "body_armor": float(gear.item_armor),
        "shield_armor": float(gear.shield_armor), "block_value": float(gear.shield_block_value),
        "weapon_dps": float(gear.weapon_dps), "weapon_speed": float(gear.weapon_speed),
    }
    reconciliation_delta = {k: slot_totals[k] - combat_totals[k] for k in combat_totals}
    max_abs_delta = max((abs(v) for v in reconciliation_delta.values()), default=0.0)
    modeled_body_rows = [x for x in body_rows if x.get("modeled")]
    missing_body_slots = [s for s in _LISTENER_BODY_SLOTS if s not in slots]

    out.update({
        "slots": slots, "items": items, "blocked_slots": blocked, "hand_setup": hand_setup,
        "availability_rule": (
            "discrete named items only: latest audited real item per role slot/weapon/shield is carried forward "
            "until another real sampled item replaces it; missing catalogue coverage remains missing"
        ),
        "item_field_scope": "named audited items only; no interpolated/extrapolated pseudo-items",
        "gear_selection_method": gear.gear_selection_method,
        "selected_body_items": list(gear.selected_body_items),
        "selection_weight_snapshot": dict(gear.selection_weight_snapshot),
        "inventory_continuity": False,
        "represented_totals": represented,
        "body_field_method": "discrete_named_sample_and_hold_v1",
        "body_field_sample_count": len(body_rows),
        "body_field_modeled_slots": [str(x.get("slot")) for x in modeled_body_rows],
        "body_field_missing_slots": missing_body_slots,
        "slot_totals": slot_totals,
        "combat_totals": combat_totals,
        "reconciliation_delta": reconciliation_delta,
        "reconciliation_ok": max_abs_delta <= 1e-8,
        "reconciliation_max_abs_delta": max_abs_delta,
    })
    role = "paladin_ret" if gear.weapon_style == "2h" else "paladin_tank"
    enrich_catalogue_metadata(out, class_key="paladin", role=role, level=level, selected=slots)
    return out


def gear_curve_status(level: int) -> str:
    """Human-readable provenance for the discrete named gear state."""
    return "discrete_named_sample_and_hold"
