from __future__ import annotations

"""Game-runtime adapters that produce the shared Evaluation contract."""

from typing import TYPE_CHECKING, Any, Mapping

from src.shared.evaluation import Evaluation

if TYPE_CHECKING:
    from src.game.runtime.simulator import CombatTimelineResult


def evaluation_from_combat_timeline(
    timeline: CombatTimelineResult,
    *,
    action_name_by_id: Mapping[str, str] | None = None,
    provenance: Mapping[str, Any] | None = None,
    fidelity: Mapping[str, Any] | None = None,
) -> Evaluation:
    """Build one canonical combat-only Evaluation directly from runtime events.

    The timeline must contain a target death.  The returned score is the combat
    kill-time bucket expressed per 100 targets; it is deliberately marked
    ``optimization_ready=False`` because recovery/travel and remaining combat
    fidelity are not part of G10.
    """
    if not timeline.target_defeated or timeline.target_death_s is None:
        raise ValueError("combat timeline did not defeat the target")
    names = dict(action_name_by_id or {})
    events = tuple(timeline.events)
    timestamps = [float(e.time_s) for e in events]
    monotonic = all(a <= b + 1e-12 for a, b in zip(timestamps, timestamps[1:]))
    death_events = [e for e in events if e.kind == "TargetDied"]
    damage_events = [
        e for e in events
        if e.kind == "Damage" and e.payload.get("applied") is not False
    ]
    ignored_damage_events = [
        e for e in events
        if e.kind == "Damage" and e.payload.get("applied") is False
    ]
    starts = [e for e in events if e.kind == "ActionStarted"]
    death_s = float(timeline.target_death_s)
    kill_s = death_s - float(timeline.start_time_s)
    final_damage_s = max((float(e.time_s) for e in damage_events), default=float(timeline.start_time_s))
    event_timing_consistent = bool(monotonic and len(death_events) == 1 and abs(final_damage_s - death_s) <= 1e-9)

    resources_before = {str(k): float(v) for k, v in timeline.resources_before.items()}
    resources_after = {str(k): float(v) for k, v in timeline.resources_after.items()}
    resource_delta = {
        key: float(resources_after.get(key, 0.0) - resources_before.get(key, 0.0))
        for key in sorted(set(resources_before) | set(resources_after))
    }
    resource_spent = {key: max(0.0, -delta) for key, delta in resource_delta.items()}

    by_school: dict[str, float] = {}
    by_action: dict[str, float] = {}
    direct = 0.0
    periodic = 0.0
    for event in damage_events:
        amount = float(event.payload.get("amount", 0.0))
        school = str(event.payload.get("school") or "unknown")
        action_id = str(event.action_id or "unknown")
        by_school[school] = by_school.get(school, 0.0) + amount
        by_action[action_id] = by_action.get(action_id, 0.0) + amount
        if bool(event.payload.get("periodic")):
            periodic += amount
        else:
            direct += amount

    action_trace = [
        {
            "time_s": float(event.time_s),
            "action_id": str(event.action_id or ""),
            "action_name": names.get(str(event.action_id or ""), str(event.action_id or "")),
            "resource_spend": [dict(x) for x in event.payload.get("resource_spend", [])],
            "gcd_ready_s": event.payload.get("gcd_ready_s"),
            "cooldown_ready_s": event.payload.get("cooldown_ready_s"),
        }
        for event in starts
    ]

    score = 100.0 * max(0.0, kill_s)
    return Evaluation(
        score_s_per_100=score,
        kill_s_per_100=score,
        recovery_s_per_100=None,
        travel_s_per_100=None,
        mobs_per_hour=None,
        resource_metrics={
            "before": resources_before,
            "after": resources_after,
            "delta": resource_delta,
            "spent": resource_spent,
            **({"mana_spent": resource_spent.get("mana", 0.0), "end_mana": resources_after.get("mana")} if "mana" in resources_before else {}),
        },
        diagnostics={
            "target_start_health": float(timeline.target_start_health),
            "target_end_health": float(timeline.target_end_health),
            "target_defeated": bool(timeline.target_defeated),
            "target_death_s": death_s,
            "action_count": len(starts),
            "action_trace": action_trace,
            "damage": {
                "total": float(sum(float(e.payload.get("amount", 0.0)) for e in damage_events)),
                "direct": float(direct),
                "periodic": float(periodic),
                "by_school": by_school,
                "by_action": by_action,
                "resolved_event_count": len(damage_events),
                "ignored_after_target_death_count": len(ignored_damage_events),
                "runtime_total_damage": float(timeline.total_damage),
                "accounting_delta_vs_runtime": float(sum(float(e.payload.get("amount", 0.0)) for e in damage_events)) - float(timeline.total_damage),
                "overkill": max(0.0, float(sum(float(e.payload.get("amount", 0.0)) for e in damage_events)) - float(timeline.target_start_health)),
            },
            "timing_consistency": {
                "event_times_monotonic": monotonic,
                "one_target_death_event": len(death_events) == 1,
                "final_damage_matches_death": abs(final_damage_s - death_s) <= 1e-9,
                "consistent": event_timing_consistent,
            },
        },
        evaluation_scope="combat_kill_only",
        optimization_ready=False,
        provenance=dict(provenance or {}),
        fidelity=dict(fidelity or {}),
    )


def evaluation_with_recovery(combat: Evaluation, recovery) -> Evaluation:
    """Extend a real combat Evaluation with post-combat ActorState recovery.

    Travel remains deliberately absent in G12, so the result is still not
    optimization-ready even though kill + recovery timing is now canonical.
    """
    if combat.kill_s_per_100 is None:
        raise ValueError("combat Evaluation has no kill timing")
    recovery_per100 = 100.0 * max(0.0, float(recovery.total_s))
    score = float(combat.kill_s_per_100) + recovery_per100
    diagnostics = dict(combat.diagnostics)
    diagnostics["recovery"] = recovery.as_dict()
    resource_metrics = dict(combat.resource_metrics)
    resource_metrics["post_recovery"] = {
        "before": dict(recovery.resources_before),
        "after": dict(recovery.resources_after),
        "health_missing_before": float(recovery.health_missing_before),
        "mana_missing_before": float(recovery.mana_missing_before),
    }
    provenance = dict(combat.provenance)
    provenance["recovery"] = dict(recovery.provenance)
    fidelity = dict(combat.fidelity)
    limitations = list(fidelity.get("limitations") or [])
    limitations = [x for x in limitations if "recovery and travel" not in str(x)]
    limitations.extend([
        "recovery uses the same post-combat ActorState and generic heal runtime",
        ("source-cadenced incoming attacks share the combat ActorState with recovery; timing/avoidance/base Armor still require source verification"
         if provenance.get("incoming_schedule_executed")
         else "ordinary incoming-player-damage events were not scheduled in this Evaluation; HP recovery can be understated"),
        "player Health capacity remains the explicit shared qualified proxy until canonical player base-health authority lands",
        "travel is not part of this Evaluation yet",
    ])
    fidelity.update({
        "limitations": limitations,
        "recovery_runtime": True,
        "same_actor_state_combat_to_recovery": True,
        "health_capacity_source_status": "qualified_classic_proxy",
    })
    return Evaluation(
        score_s_per_100=score,
        kill_s_per_100=float(combat.kill_s_per_100),
        recovery_s_per_100=recovery_per100,
        travel_s_per_100=None,
        mobs_per_hour=None,
        resource_metrics=resource_metrics,
        diagnostics=diagnostics,
        timing_contract=combat.timing_contract,
        evaluation_scope="combat_plus_recovery",
        optimization_ready=False,
        provenance=provenance,
        fidelity=fidelity,
    )
