#!/usr/bin/env python3
"""Native Warlock two-target APL proposals, not a combat simulator.

All spell IDs come from Rust get_options. Rust prepare/sim is responsible for
casts, mana, pets, DoT snapshots/ticks and actual target HP. This builder
only submits an APL policy including a <50%-HP *target switch*; it cannot on
its own prove a 2D rolling-world pull or Fear/Funnel source support.
"""
from __future__ import annotations


def discover(spells: list[dict], name: str) -> int | None:
    rows = [row for row in spells if name in str(row.get("name", "")).casefold()]
    return int(rows[0]["spell_id"]) if rows else None


def health_below(threshold: int, unit: str) -> dict:
    if not 0 < threshold <= 100:
        raise ValueError("HP threshold out of range")
    return {"cmp": {
        "lhs": {"currentHealthPercent": (
            {"sourceUnit": {"type": unit}} if unit != "Player" else {})},
        "op": "OpLt",
        "rhs": {"const": {"val": f"{threshold}%"}},
    }}


def health_above(threshold: int, unit: str) -> dict:
    if not 0 <= threshold < 100:
        raise ValueError("HP threshold out of range")
    return {"cmp": {
        "lhs": {"currentHealthPercent": {"sourceUnit": {"type": unit}}},
        "op": "OpGt",
        "rhs": {"const": {"val": f"{threshold}%"}},
    }}


def cast(spell_id: int, condition: dict | None = None) -> dict:
    entry = {"action": {"castSpell": {"spellId": {"spellId": spell_id}}}}
    if condition is not None:
        entry["action"]["condition"] = condition
    return entry


def build_rolling_two_target_apl(spells: list[dict], *,
                                 pull_threshold: int = 50,
                                 drain_health_threshold: int = 30) -> tuple[list[dict], dict]:
    """Use native-current-target + next-target APL, not a stitched kill clock.

    The new target must still have >95% HP before the switch, so an already
    injured original target cannot be reselected in an infinite loop.
    This is a *two-target native combat smoke*, not the eventual replenishing
    live 100-mob world policy.
    """
    names = ("immolate", "bane of agony", "siphon life", "corruption",
             "drain life", "life tap")
    ids = {name: discover(spells, name) for name in names}
    missing = [name for name in names if ids[name] is None]
    if missing:
        raise ValueError("Rust get_options missing L30 Warlock spells: " + ", ".join(missing))
    if not 10 <= pull_threshold <= 90:
        raise ValueError("Need supported candidate pull threshold 10..90")
    switch = {"action": {
        "condition": {"and": {"vals": [
            health_below(pull_threshold, "CurrentTarget"),
            health_above(95, "NextTarget"),
        ]}},
        "changeTarget": {"newTarget": {"type": "NextTarget"}},
    }}
    drain = cast(ids["drain life"], health_below(drain_health_threshold, "Player"))
    dot_rows = [cast(ids[name], {"not": {"val": {
        "dotIsActive": {"spellId": {"spellId": ids[name]}}}}})
                for name in names[:4]]
    # Existing native APL condition has proven to accept these Health/Mana
    # expressions. Rust determines the actual paid Life Tap effect.
    tap = cast(ids["life tap"], {"and": {"vals": [
        {"cmp": {"lhs": {"currentManaPercent": {}}, "op": "OpLt",
                  "rhs": {"const": {"val": "45%"}}}},
        {"cmp": {"lhs": {"currentHealthPercent": {}}, "op": "OpGt",
                 "rhs": {"const": {"val": "35%"}}}},
    ]}})
    wand = discover(spells, "shoot")
    fallback_name = "shoot" if wand is not None else "drain life"
    filler = cast(wand if wand is not None else ids["drain life"])
    result = [drain, switch, *dot_rows, tap, filler]
    meta = {"native_spell_ids": ids, "native_wand_spell_id": wand,
            "filler": fallback_name, "pull_threshold_pct": pull_threshold,
            "drain_health_threshold_pct": drain_health_threshold,
            "source_supported_fear_id": discover(spells, "fear"),
            "source_supported_health_funnel_id": discover(spells, "health funnel"),
            "fear_and_pet_funnel_not_executed_in_this_smoke": True,
            "multi_target_world_ACK_verified": False}
    return result, meta


def build_stationary_native_multidot_smoke(spells: list[dict]) -> tuple[list[dict], dict]:
    """Native-only capability screen: can Rust really DoT two live targets?

    The selected Fight's stationary targets intentionally have no HP ledger.
    Therefore a 50%-of-current-mob condition would be ungrounded outside the
    2D ACK world. Use existing native multidot APL actions here only; this
    smoke never claims the requested threshold behavior was executed.
    """
    dot_names = ("immolate", "bane of agony", "siphon life", "corruption")
    dot_ids = {name: discover(spells, name) for name in dot_names}
    missing = [name for name, sid in dot_ids.items() if sid is None]
    if missing:
        raise ValueError("Native two-target DoT unsupported: "+", ".join(missing))
    actions = [
        {"action": {"multidot": {
            "spellId": {"spellId": dot_ids[name]}, "maxDots": 2,
        }}}
        for name in dot_names
    ]
    drain_id = discover(spells, "drain life")
    if drain_id is None:
        raise ValueError("Native Drain Life not discovered")
    actions.insert(0, cast(drain_id, health_below(30, "Player")))
    wand_id = discover(spells, "shoot")
    actions.append(cast(wand_id if wand_id is not None else drain_id))
    return actions, {
        "source_dot_spell_ids": dot_ids,
        "filler": "shoot" if wand_id is not None else "drain life",
        "native_two_target_dots_only": True,
        "pull_at_50_pct_executed": False,
        "world_2d_ack_executed": False,
    }
