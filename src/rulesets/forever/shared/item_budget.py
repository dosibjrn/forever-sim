from __future__ import annotations

"""Empirical equal-budget exchange scales from audited Forever peer items.

The current beta client/public item sources expose actual stat amounts but not a
single authoritative server-side formula that converts one abstract item-budget
point into flat Strength/Intellect/Spell Power/etc.  We can still estimate the
*local exchange scale* directly from designed peer items: same profession,
slot, item level and required level, but different role variants.

For a peer group, the range of each stat is the amount designers traded in/out
while keeping the same slot/item-level envelope.  Ranges are normalized by
(required_level + 5) so samples from different tiers can be combined, then a
proximity-weighted median is scaled back to the requested level.  The result is
not claimed to be Blizzard's hidden formula; it is an empirical equal-budget
projection calibrated from current Forever items.
"""

from collections import defaultdict
from typing import Iterable, Mapping, Any


_DEFAULT_STATS = (
    "strength", "agility", "stamina", "intellect", "spirit",
    "spell_power", "healing", "mp5", "defense",
)


def _stat_value(row: Any, stat: str) -> float:
    if stat == "spell_power":
        if hasattr(row, "damage_power"):
            return float(row.damage_power)
        if isinstance(row, Mapping):
            return float(row.get("damage_power", row.get("spell_power", row.get("spell_damage", 0.0))) or 0.0)
    if isinstance(row, Mapping):
        return float(row.get(stat, 0.0) or 0.0)
    return float(getattr(row, stat, 0.0) or 0.0)


def _field(row: Any, name: str, default=None):
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _weighted_median(samples: list[tuple[float, float]]) -> float | None:
    xs = sorted((float(v), max(0.0, float(w))) for v, w in samples if float(v) > 0 and float(w) > 0)
    if not xs:
        return None
    total = sum(w for _, w in xs)
    acc = 0.0
    for value, weight in xs:
        acc += weight
        if acc >= total * 0.5:
            return value
    return xs[-1][0]


def peer_exchange_budget_units(
    rows: Iterable[Any],
    level: int,
    *,
    stats: Iterable[str] = _DEFAULT_STATS,
    distance_scale: float = 15.0,
) -> dict:
    """Estimate units of each stat purchasable by one peer-item budget chunk.

    A peer group is keyed by profession + slot + item level + required level.
    Groups need at least two role variants.  Within a group, max-min for a stat
    is treated as the observed exchange chunk for that stat.  The chunk is
    normalized for level before pooling so the estimator remains useful between
    and beyond sparse sampled tiers.
    """
    level = max(1, int(level))
    wanted = tuple(dict.fromkeys(str(s) for s in stats))
    grouped: dict[tuple, list[Any]] = defaultdict(list)
    for row in rows:
        key = (
            _field(row, "profession", ""), _field(row, "slot", ""),
            int(_field(row, "item_level", 0) or 0), int(_field(row, "required_level", 0) or 0),
        )
        grouped[key].append(row)

    samples: dict[str, list[tuple[float, float]]] = defaultdict(list)
    sample_meta: dict[str, list[dict]] = defaultdict(list)
    scale = max(1.0, float(distance_scale))
    peer_group_count = 0
    for key, peers in grouped.items():
        if len(peers) < 2:
            continue
        peer_group_count += 1
        req = max(1, int(key[3]))
        distance = abs(float(req - level))
        # Smoothly prefer nearby tiers without throwing away older/future peer
        # information.  Three-way role families carry slightly more evidence.
        weight = (1.0 / (1.0 + (distance / scale) ** 2)) * (1.0 + 0.15 * max(0, len(peers) - 2))
        level_norm = float(req + 5)
        for stat in wanted:
            values = [_stat_value(x, stat) for x in peers]
            span = max(values) - min(values)
            if span <= 0.0:
                continue
            normalized_span = span / level_norm
            samples[stat].append((normalized_span, weight))
            sample_meta[stat].append({
                "required_level": req,
                "item_level": int(key[2]),
                "slot": str(key[1]),
                "profession": str(key[0]),
                "peer_count": len(peers),
                "observed_span": float(span),
                "weight": float(weight),
            })

    units: dict[str, float] = {}
    confidence: dict[str, dict] = {}
    for stat in wanted:
        med = _weighted_median(samples.get(stat, []))
        if med is None:
            continue
        units[stat] = float(med) * float(level + 5)
        rows_for_stat = sample_meta[stat]
        confidence[stat] = {
            "peer_samples": len(rows_for_stat),
            "nearest_sample_levels": sorted({int(x["required_level"]) for x in rows_for_stat}, key=lambda x: abs(x-level))[:6],
            "weighted_support": sum(float(x["weight"]) for x in rows_for_stat),
        }

    return {
        "method": "forever_peer_item_exchange_v1",
        "level": level,
        "unit": "empirical_stat_units_per_equal_peer_item_budget_chunk",
        "units_per_budget": units,
        "confidence": confidence,
        "peer_group_count": peer_group_count,
        "note": (
            "Approximate equal-budget exchange scale inferred from same-slot/same-ilvl designed role peers. "
            "It is a data-driven projection, not a claim about the hidden server item-budget formula."
        ),
    }


def weapon_peer_exchange_budget_units(
    rows: Iterable[Any],
    level: int,
    *,
    weapon_hands: int | None = None,
    stats: Iterable[str] = ("weapon_dps", "strength", "stamina", "intellect", "spirit", "spell_power", "healing", "mp5"),
    distance_scale: float = 12.0,
) -> dict:
    """Estimate a *weapon-slot* equal-budget exchange from real weapon peers.

    Weapon DPS must not borrow the body-slot exchange scale.  This estimator
    groups real canonical weapon rows by hand-count, item level and quality,
    then measures the stat/DPS spans designers traded inside that same weapon
    envelope.  The requested level only proximity-weights peer tiers; it does
    not change item stats or pretend to know Blizzard's hidden budget formula.

    ``weapon_hands`` lets Paladin Ret (2H) and Protection (1H+shield) use the
    correct weapon market instead of mixing fundamentally different slot
    envelopes.
    """
    level=max(1,int(level))
    wanted=tuple(dict.fromkeys(str(s) for s in stats))
    grouped: dict[tuple, list[Any]] = defaultdict(list)
    for row in rows:
        wdps=float(_field(row, "weapon_dps", 0.0) or 0.0)
        hands=int(_field(row, "weapon_hands", 0) or 0)
        ilvl=int(_field(row, "item_level", 0) or 0)
        quality=int(_field(row, "quality", 0) or 0)
        if wdps <= 0.0 or hands not in (1,2) or ilvl <= 0:
            continue
        if weapon_hands in (1,2) and hands != int(weapon_hands):
            continue
        grouped[(hands, ilvl, quality)].append(row)

    samples: dict[str, list[tuple[float,float]]] = defaultdict(list)
    sample_meta: dict[str, list[dict]] = defaultdict(list)
    scale=max(1.0,float(distance_scale))
    peer_group_count=0
    target_ilvl=float(level+5)
    for key, peers in grouped.items():
        if len(peers) < 2:
            continue
        peer_group_count += 1
        hands, ilvl, quality = key
        distance=abs(float(ilvl)-target_ilvl)
        weight=(1.0/(1.0+(distance/scale)**2))*(1.0+0.08*max(0,len(peers)-2))
        # Normalize by ilvl so low/high tiers can inform one local exchange scale.
        norm=max(1.0,float(ilvl))
        for stat in wanted:
            values=[_stat_value(x,stat) for x in peers]
            span=max(values)-min(values)
            if span <= 0.0:
                continue
            samples[stat].append((span/norm,weight))
            sample_meta[stat].append({
                "item_level":int(ilvl),
                "weapon_hands":int(hands),
                "quality":int(quality),
                "peer_count":len(peers),
                "observed_span":float(span),
                "weight":float(weight),
            })

    units: dict[str,float] = {}
    confidence: dict[str,dict] = {}
    for stat in wanted:
        med=_weighted_median(samples.get(stat,[]))
        if med is None:
            continue
        units[stat]=float(med)*target_ilvl
        metas=sample_meta[stat]
        confidence[stat]={
            "peer_samples":len(metas),
            "nearest_sample_item_levels":sorted({int(x["item_level"]) for x in metas}, key=lambda x:abs(float(x)-target_ilvl))[:6],
            "weighted_support":sum(float(x["weight"]) for x in metas),
        }

    return {
        "method":"forever_weapon_peer_item_exchange_v1",
        "level":level,
        "weapon_hands":int(weapon_hands) if weapon_hands in (1,2) else None,
        "unit":"empirical_weapon_slot_units_per_equal_peer_weapon_budget_chunk",
        "units_per_budget":units,
        "confidence":confidence,
        "peer_group_count":peer_group_count,
        "note":(
            "Weapon-slot equal-budget scale inferred only from same-hand-count/same-ilvl/same-quality real weapon peers. "
            "Weapon DPS is never projected with the body-slot budget model."
        ),
    }
