#!/usr/bin/env python3
"""Fast *diagnostic* paired P1 effect experiment on real gsim GameIR/CombatRuntime.

The required gsim-2D <-> native MythicSim Rust spell-control session is not yet
implemented by the pinned Rust executable.  This runner NEVER claims P1 PASS,
and --backend hybrid-rust fails closed rather than substituting gsim results.

No mock spells, arbitrary PASS ledger, 100-mob run or historical evidence input.
The only deliberately artificial things are the toy enemy's health/hit cadence
and a zero-EFFECT copy of the actual sourced action (same costs/timing).
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
from src.game.model.ir import IncomingAttackDefinition, QueuedSwingEffect, ResourceChangeEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.runtime.simulator import action_eligibility
from tools.wf_gate_p1_live import (_highest_usable_ranks, _source_ids, _source_rows, _source_legality, _source_disabled_rune_ids, _load_p1_scenario_nonimpact, run_live)

TOY_MOB_HP = 20_000.
EXTRA_PLAYER_HP = 5_000.
MOB_HIT = 10.
SWING_SECONDS = 2.
# Never use status strings to manufacture full gate acceptance.
PROOF_KIND = "GSIM_ABLATION_DIAGNOSTIC_NOT_HYBRID_RUST_OR_P1_PASS"


def _starting_state(ir, action, mode):
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.metadata["level"] = 20
    if mode != actor.current_mode_id:
        actor.transition_mode(mode)
    # A safe oversized health pool, but 500 damage missing to let heals work.
    if "health" not in actor.resource_capacity:
        raise ValueError("SOURCE_ACTOR_HEALTH_MISSING")
    actor.resource_capacity["health"] += EXTRA_PLAYER_HP
    actor.resources["health"] = actor.resource_capacity["health"] - 500.
    for resource, capacity in actor.resource_capacity.items():
        if resource != "health" and resource in actor.resources and actor.resource_is_active(resource):
            actor.resources[resource] = float(capacity)
    # Realistic nonzero toy mitigation/debuff channels; these are fixture
    # numbers, NOT Forever source coefficients or class-specific game rules.
    target = TargetState.with_health("toy_mob", TOY_MOB_HP, armor=200.,
                                     attack_power=200., melee_attack_power=200.)
    if hasattr(target, "bind_resource_definitions"):
        target.bind_resource_definitions(ir.resources)
    for req in action.requirements:
        if not hasattr(req, "get"):
            raise ValueError("UNUSABLE_SOURCE_REQUIREMENT")
        if req.get("kind") == "relative_position_is":
            target.metadata["attacker_relative_position"] = str(req["value"])
        if req.get("kind") == "resource_min":
            rid = str(req.get("resource_id") or "")
            amount = float(req.get("value") or 0.)
            if rid in getattr(target, "resources", {}):
                cap = getattr(target, "resource_capacity", {}).get(rid)
                if cap is None or amount <= cap:
                    target.resources[rid] = max(float(target.resources[rid]), amount)
        if req.get("kind") == "resource_below_capacity":
            rid = str(req.get("resource_id") or "")
            if rid in actor.resource_capacity and rid in actor.resources:
                actor.resources[rid] = max(0., float(actor.resource_capacity[rid]) - 1.)
    # Generic resource-generating actions require room to show an effect.
    for effect in action.effects:
        if (isinstance(effect, ResourceChangeEffect)
                and effect.target in ("actor", "self")
                and effect.operation == "add"):
            rid = str(effect.resource_id)
            if rid in actor.resources and rid in actor.resource_capacity:
                actor.resources[rid] = min(float(actor.resources[rid]),
                                           float(actor.resource_capacity[rid]) * 0.25)
    return actor, target


def _numeric(value):
    v = float(value)
    if not math.isfinite(v):
        raise ValueError("NONFINITE_RUNTIME_OBSERVATION")
    return round(v, 6)


def observable_state(rt):
    """Real runtime end state and accumulated effects, not cast bookkeeping."""
    actor, target = rt.actor, rt.target
    # An active aura is an observable state; inactive/bogus auras are NOT
    # automatically accepted as a meaningful gameplay effect by the P1 gate.
    kinds = {}
    total_heal = total_overheal = total_taken = 0.
    for event in rt.trace:
        kinds[event.kind] = kinds.get(event.kind, 0) + 1
        if event.kind == "Heal":
            total_heal += float(event.payload.get("amount", 0.))
            total_overheal += float(event.payload.get("overheal", 0.))
        elif event.kind == "IncomingAttackResolved":
            total_taken += float(event.payload.get("post_mitigation_damage", 0.))
    return {
        "mob_hp": _numeric(target.health),
        "mob_stat_modifiers": {
            str(k): [str(v[0]), _numeric(v[1]), int(v[2])]
            for k, v in sorted(target.active_stat_modifiers.items())
        },
        "mob_school_power_modifiers": {
            str(k): [str(v[0]), _numeric(v[1]), int(v[2])]
            for k, v in sorted(target.active_school_power.items())
        },
        "player_hp": _numeric(actor.resources.get("health", 0.)),
        "player_resources": {k: _numeric(v) for k, v in sorted(actor.resources.items())},
        "player_stats": {k: _numeric(v) for k, v in sorted(actor.stats.items())},
        "player_mode": actor.current_mode_id,
        "player_auras": sorted(map(str, actor.active_auras)),
        "mob_controls": {k: _numeric(v) for k, v in sorted(target.active_controls.items())},
        "mob_auras": sorted(map(str, getattr(target, "active_auras", {}))),
        "damage_dealt": _numeric(rt.result().total_damage),
        "healing": _numeric(total_heal),
        "overhealing": _numeric(total_overheal),
        "damage_taken": _numeric(total_taken),
        # Accumulated behavioral observations handle effects which expire
        # before the end state (DoTs/CC/aura lifetimes).
        "damage_event_count": kinds.get("Damage", 0),
        "heal_event_count": kinds.get("Heal", 0),
        "control_event_count": kinds.get("ControlApplied", 0),
        "debuff_event_count": kinds.get("TargetStatDebuffApplied", 0),
    }


def _run_one(ir, action, mode, *, muted: bool):
    actor, target = _starting_state(ir, action, mode)
    incoming = IncomingAttackDefinition(
        id="toy_hit", name="toy mob 10-damage swing",
        source_actor_id=target.id, target_actor_id=actor.id,
        school="physical", raw_damage=MOB_HIT, hit_chance=1.,
        health_resource_id="health",
        metadata={"representative_swing_s": SWING_SECONDS},
        provenance=({"source": "user_defined_P1_toy_mob_fixture", "damage": MOB_HIT},),
    )
    # A queued-swing spell (Maul) only deals damage on the real next white
    # swing. Use the exact sourced autoattack definition, not a fake proc.
    queued = [e for e in action.effects if isinstance(e, QueuedSwingEffect)]
    attacks = tuple(a for a in ir.auto_attacks
                    if a.id in {e.auto_attack_id for e in queued})
    if len(attacks) != len(queued):
        raise ValueError("SOURCE_QUEUED_SWING_AUTOATTACK_MISSING")
    rt = CombatRuntime(actor=actor, target=target, auto_attacks=attacks,
                       incoming_attacks=(incoming,))
    real_or_muted = replace(action, effects=()) if muted else action
    eligibility = action_eligibility(action=real_or_muted, actor=actor, target=target)
    if not eligibility.eligible:
        raise ValueError("ACTION_NOT_ELIGIBLE:" + str(eligibility.reason))
    rt.schedule_action(real_or_muted)
    # Short, bounded clock advance. Periodic ticks and incoming hits are
    # actually executed on the same production event queue.
    durations = [float(e.duration_s) for e in action.effects
                 if hasattr(e, "duration_s") and getattr(e, "duration_s", None) is not None]
    window = min(40., max(12., *(durations or [0.])))
    rt.advance_to(max(actor.current_time_s, 0.) + window)
    return observable_state(rt)


def compare_action(ir, action):
    """Paired action vs effect-free identical timing/cost on actual gsim."""
    modes = [m.id for m in ir.modes
             if m.enabled_action_ids is None or action.id in m.enabled_action_ids]
    if not ir.modes:
        modes = [None]
    if not modes:
        return {"status": "NO_SOURCE_LEGAL_MODE", "difference": {}}
    errors = []
    for mode in modes:
        try:
            real = _run_one(ir, action, mode, muted=False)
            inert = _run_one(ir, action, mode, muted=True)
            difference = {k: {"real": real[k], "without_effect": inert[k]}
                          for k in real if real[k] != inert[k]}
            # Costs, cast time, GCD and cooldown are the SAME both times.
            # No-effect outcomes are NOT credited as working spells.
            return {"status": "EFFECT_OBSERVED" if difference else "NO_OBSERVABLE_EFFECT",
                    "mode": mode, "difference": difference}
        except (ValueError, KeyError, TypeError, RuntimeError, AssertionError) as exc:
            errors.append(f"{mode}: {type(exc).__name__}: {exc}")
    return {"status": "UNEXECUTABLE_SETUP", "errors": errors[:4], "difference": {}}


def _source_actions(root: Path):
    source = DEFAULT_DB
    if not source.is_file() or source.stat().st_size < 1024:
        raise ValueError("HYDRATED_SOURCE_SQLITE_REQUIRED")
    ir = build_game_ir_slice(class_key="druid", level=20, ability_db_path=source)
    if ir is None:
        raise ValueError("PRODUCTION_L20_DRUID_IR_UNAVAILABLE")
    # Execute the live P1 auditor to retain its gate verdict, but derive the
    # broader spell denominator directly from source legality and GameIR.
    # In particular, Feral Cat can ALSO cast druid heals and caster spells.
    p1 = run_live(root, "druid", 20, spec="feral-cat")
    legality, _meta = _source_legality(root, ir, "druid", 20, source)
    inactive = _source_disabled_rune_ids(source, "druid", 20)
    excluded_in_scenario = _load_p1_scenario_nonimpact(
        root, "druid", 20, "current_solo_leveling_100mob_v1")
    rows = [row for row in _source_rows(source, "druid", 20)
            if legality.get(int(row["spell_id"]), ("UNRESOLVED",))[0] in ("LEGAL", "CONDITIONAL")
            and int(row["spell_id"]) not in inactive]
    highest = _highest_usable_ranks(rows)
    selected = {int(row["spell_id"]): row for row in highest
                if int(row["spell_id"]) not in excluded_in_scenario}
    matched = {}
    for action in ir.actions:
        if action.owner_actor_id != ir.actor.id:
            continue
        for sid in _source_ids(action, _source_spell_ids):
            if sid in selected:
                if sid in matched:
                    raise ValueError("DUPLICATE_P1_ACTION_ID:" + str(sid))
                matched[sid] = action
    if not selected:
        raise ValueError("EMPTY_L20_SOURCE_LEGAL_ABILITY_UNIVERSE")
    return ir, selected, matched, p1


def run_gsim(root=ROOT, *, ability_id=None):
    ir, inventory, mapped, source_p1 = _source_actions(root)
    results = []
    for sid, row in sorted(inventory.items()):
        if ability_id is not None and sid != ability_id:
            continue
        action = mapped.get(sid)
        outcome = (compare_action(ir, action) if action is not None else
                   {"status": "MISSING_GAME_IR_ACTION", "difference": {}})
        results.append({"spell_id": sid, "name": row["name"],
                        "rank": row.get("rank_hint"),
                        "action_id": action.id if action is not None else None,
                        **outcome})
    if ability_id is not None and not results:
        raise ValueError("ABILITY_NOT_IN_L20_P1_UNIVERSE:" + str(ability_id))
    return {"class": "druid", "level": 20, "spec": "feral-cat",
            "proof_kind": PROOF_KIND,
            "p1_certified": False, "hybrid_rust_executed": False,
            "live_p1_current_status": source_p1["status"],
            "checked": len(results),
            "note": "full source-legal druid spellbook, including caster/healing, not just Cat Form",
            "observed": sum(x["status"] == "EFFECT_OBSERVED" for x in results),
            "results": results}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", choices=("hybrid-rust", "gsim-diagnostic"),
                    default="hybrid-rust")
    ap.add_argument("--rust-binary", type=Path)
    ap.add_argument("--ability-id", type=int)
    args = ap.parse_args(argv)
    if args.backend == "hybrid-rust":
        # The existing transport has no source-action injection/ablation API.
        # Opening it is NOT equivalent to executing source-native spells.
        if args.rust_binary:
            from src.game.runtime.native_step_protocol import RustStepSession
            try:
                with RustStepSession(args.rust_binary) as _session:
                    raise RuntimeError("RUST_SOURCE_ACTION_ABLATION_API_NOT_IMPLEMENTED")
            except Exception as exc:
                print(f"BLOCKED: real Rust source-action session: {exc}", file=sys.stderr)
                return 2
        print("BLOCKED: genuine gsim-2D <-> Rust source-action ablation is not yet "
              "implemented; supply a real native session and action-control API. "
              "gsim-diagnostic is not P1 PASS.", file=sys.stderr)
        return 2
    try:
        report = run_gsim(ability_id=args.ability_id)
    except Exception as exc:
        print("FAIL: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    # Diagnostics never claim that the required hybrid-rust gate passed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
