from __future__ import annotations

"""Machine-readable legacy-vs-generic backend comparison.

Comparison is orchestration, never simulation authority: both backends are run
independently and their already-published DecisionRecords are classified here.
No value from legacy is fed back into generic execution.
"""

from typing import Any, Iterable, Mapping

from src.version import SOFTWARE_VERSION

COMPARE_BACKEND_ID = "compare"
COMPARE_IMPLEMENTATION = "backend_delta_classifier"
COMPARE_SCHEMA_VERSION = 1


def backend_metadata() -> dict[str, Any]:
    return {
        "id": COMPARE_BACKEND_ID,
        "version": SOFTWARE_VERSION,
        "implementation": COMPARE_IMPLEMENTATION,
        "status": "druid_caster_delta_decomposition",
        "independent": False,
        "orchestrates": ["legacy", "generic"],
        "simulation_authority": False,
    }


def _records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(x) for x in (payload.get("decisions") or []) if isinstance(x, Mapping)]


def _find_record(
    payload: Mapping[str, Any], *, class_name: str, level: int, route: str | None = None,
) -> dict[str, Any] | None:
    cls = str(class_name).lower()
    rows = [
        row for row in _records(payload)
        if str((row.get("identity") or {}).get("class_name") or "").lower() == cls
        and int((row.get("identity") or {}).get("level") or -1) == int(level)
    ]
    if route is not None:
        exact = [row for row in rows if str((row.get("identity") or {}).get("route") or "") == str(route)]
        if exact:
            return exact[0]
    return rows[0] if rows else None


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _delta(generic: Any, legacy: Any) -> float | None:
    g, l = _num(generic), _num(legacy)
    return None if g is None or l is None else g - l


def _actor_stat(record: Mapping[str, Any], key: str) -> float | None:
    actors = list(record.get("actors") or [])
    if not actors:
        return None
    return _num((actors[0].get("stats") or actors[0].get("base_stats") or {}).get(key))


def _resource(record: Mapping[str, Any], resource_id: str) -> Mapping[str, Any] | None:
    for resource in record.get("resources") or []:
        if str(resource.get("id") or "") == str(resource_id):
            return resource
    return None


def _action(record: Mapping[str, Any], family_key: str) -> Mapping[str, Any] | None:
    for action in record.get("actions") or []:
        family = str(action.get("family_key") or action.get("id") or "").lower()
        if family == str(family_key).lower() or family.startswith(str(family_key).lower() + ":"):
            return action
    return None


def _direct_damage_average(action: Mapping[str, Any] | None) -> float | None:
    if not action:
        return None
    for effect in action.get("effects") or []:
        if str(effect.get("effect_type") or "") == "damage":
            lo, hi = _num(effect.get("base_min")), _num(effect.get("base_max"))
            if lo is not None and hi is not None:
                return (lo + hi) / 2.0
    return None


def _legacy_ranks(record: Mapping[str, Any]) -> dict[str, int]:
    return {str(k): int(v) for k, v in dict((record.get("talents") or {}).get("ranks") or {}).items() if int(v) > 0}


def _generic_ranks(record: Mapping[str, Any]) -> dict[str, int]:
    talents = dict(record.get("talents") or {})
    provenance = dict(record.get("provenance") or {})
    talent_application = dict(provenance.get("talent_application") or {})
    for raw in (
        talents.get("selection"),
        talents.get("selected_ranks"),
        talent_application.get("selection"),
    ):
        selection = dict(raw or {})
        if selection:
            return {str(k): int(v) for k, v in selection.items() if int(v) > 0}
    return {}


def _generic_eval(record: Mapping[str, Any]) -> Mapping[str, Any]:
    return dict((record.get("provenance") or {}).get("evaluation") or {})


def _generic_timeline(record: Mapping[str, Any]) -> Mapping[str, Any]:
    return dict((record.get("provenance") or {}).get("evaluation_timeline") or {})


def classify_druid_caster_delta(
    *, legacy_payload: Mapping[str, Any], generic_payload: Mapping[str, Any], level: int,
) -> dict[str, Any]:
    """Classify the first migrated Druid caster slice without hiding unknowns."""
    legacy = _find_record(legacy_payload, class_name="druid", level=level, route="balance")
    generic = _find_record(generic_payload, class_name="druid", level=level)
    if legacy is None or generic is None:
        return {
            "schema_version": COMPARE_SCHEMA_VERSION,
            "id": f"druid-caster:L{int(level)}",
            "class_name": "druid",
            "level": int(level),
            "status": "unavailable",
            "reason": "required legacy balance or generic Druid record missing",
            "categories": {},
        }

    lt, gt = dict(legacy.get("timing") or {}), dict(generic.get("timing") or {})
    legacy_ranks, generic_ranks = _legacy_ranks(legacy), _generic_ranks(generic)
    shared_ranks = {k: generic_ranks[k] for k in generic_ranks if legacy_ranks.get(k) == generic_ranks[k]}
    legacy_only = {k: v for k, v in legacy_ranks.items() if generic_ranks.get(k) != v}
    generic_only = {k: v for k, v in generic_ranks.items() if legacy_ranks.get(k) != v}

    wrath = _action(generic, "wrath")
    moonfire = _action(generic, "moonfire")
    mana = _resource(generic, "mana") or {}
    gev = _generic_eval(generic)
    gdiag = dict(gev.get("diagnostics") or {})
    gdamage = dict(gdiag.get("damage") or {})
    gtimeline = _generic_timeline(generic)
    gear = dict((legacy.get("gear") or {}).get("snapshot") or {})
    native_gear = dict(generic.get("gear") or {})
    native_gear_applied = native_gear.get("status") == "selected_named_catalogue_gear"
    legacy_policy = str((legacy.get("policy") or {}).get("label") or "")
    generic_policy = dict(generic.get("policy") or {})
    generic_policy_actions = [str(x.get("action_id") or "") for x in generic_policy.get("rules") or []]
    unsupported = list(generic.get("unsupported_mechanics") or [])

    runtime_damage = _num(gtimeline.get("total_damage"))
    evaluation_damage = _num(gdamage.get("total"))
    damage_accounting_delta = _delta(evaluation_damage, runtime_damage)
    damage_accounting_ok = damage_accounting_delta is not None and abs(damage_accounting_delta) <= 1e-9

    categories = {
        "action_damage": {
            "status": "partial_gap",
            "legacy": {
                "kill_seconds_per_mob": _num(lt.get("kill_seconds_per_mob")),
                "spell_power": _actor_stat(legacy, "spell_power"),
                "gear_spell_power": _num(gear.get("spell_power")),
            },
            "generic": {
                "kill_seconds_per_mob": _num(gt.get("kill_seconds_per_mob")),
                "wrath_tuned_base_average": _direct_damage_average(wrath),
                "moonfire_direct_base_average": _direct_damage_average(moonfire),
                "spell_power": _actor_stat(generic, "spell_power") or 0.0,
                "named_gear_applied": native_gear_applied,
                "gear_stats": dict(native_gear.get("aggregate_stats") or {}),
                "runtime_applied_damage": runtime_damage,
                "evaluation_accounted_damage": evaluation_damage,
                "damage_accounting_delta": damage_accounting_delta,
                "ignored_after_target_death_count": int(gdamage.get("ignored_after_target_death_count") or 0),
            },
            "delta": {"kill_seconds_per_mob": _delta(gt.get("kill_seconds_per_mob"), lt.get("kill_seconds_per_mob"))},
            "classification": [
                ("generic has independently selected named catalogue gear; loadouts need not match legacy" if native_gear_applied else "generic actor lacks native selected gear; legacy has its own gear"),
                "generic attack-table/crit resolution is still unsupported",
                "generic runtime/evaluation damage accounting is internally consistent" if damage_accounting_ok else "generic runtime/evaluation damage accounting mismatch",
            ],
        },
        "action_timing": {
            "status": "partial_gap",
            "legacy": {"kill_seconds_per_mob": _num(lt.get("kill_seconds_per_mob")), "improved_wrath_rank": legacy_ranks.get("improved_wrath")},
            "generic": {"kill_seconds_per_mob": _num(gt.get("kill_seconds_per_mob")), "wrath_cast_time_s": _num((wrath or {}).get("cast_time_s")), "improved_wrath_rank": generic_ranks.get("improved_wrath")},
            "delta": {"kill_seconds_per_mob": _delta(gt.get("kill_seconds_per_mob"), lt.get("kill_seconds_per_mob"))},
            "classification": ["Improved Wrath rank is shared", "legacy publication does not expose per-action cast timing; total kill-time gap remains downstream of damage/talent/policy fidelity"],
        },
        "resource": {
            "status": "partial_gap",
            "legacy": {"mana_value_status": "not_published_by_legacy_row", "gear_intellect": _num(gear.get("intellect")), "gear_mp5": _num(gear.get("mp5"))},
            "generic": {
                "mana_initial": _num(mana.get("initial_amount")), "mana_capacity": _num(mana.get("capacity")),
                "mana_spent_per_mob": _num((gev.get("resource_metrics") or {}).get("mana_spent")),
            },
            "classification": ["generic starting mana is source-backed", ("generic named gear is applied, but legacy route does not publish comparable starting Mana" if native_gear_applied else "generic gear application unavailable")],
        },
        "recovery": {
            "status": "partial_gap",
            "legacy": {"seconds_per_mob": _num(lt.get("recovery_seconds_per_mob"))},
            "generic": {"seconds_per_mob": _num(gt.get("recovery_seconds_per_mob")), "details": dict(gdiag.get("recovery") or {})},
            "delta": {"seconds_per_mob": _delta(gt.get("recovery_seconds_per_mob"), lt.get("recovery_seconds_per_mob"))},
            "classification": ["same shared food/water recovery authority", ("generic named gear includes executable intellect/spirit/mp5 effects" if native_gear_applied else "generic gear effects not available"), "incoming-player-damage/attack-table semantics and policy differences remain separate", "no quantified total residual attribution is claimed"],
        },
        "talent": {
            "status": "explained_gap" if legacy_only or generic_only else "parity",
            "legacy": {"ranks": legacy_ranks},
            "generic": {"ranks": generic_ranks, "search_performed": bool((generic.get("capability") or {}).get("talent_search"))},
            "shared_ranks": shared_ranks,
            "legacy_only_or_different": legacy_only,
            "generic_only_or_different": generic_only,
            "classification": ["native generic executable-talent scope differs from legacy full talent tree" if bool((generic.get("capability") or {}).get("talent_search")) else "generic talent selection remains an explicit seed"] if legacy_only or generic_only else ["selected ranks match"],
        },
        "policy": {
            "status": "partial_gap",
            "legacy": {"label": legacy_policy},
            "generic": {"label": generic_policy.get("label"), "action_ids": generic_policy_actions, "search_performed": bool((generic.get("capability") or {}).get("policy_search"))},
            "classification": [
                ("generic policy is bounded searched over action inclusion/exclusion and priority order" if bool((generic.get("capability") or {}).get("policy_search")) else "generic policy is supplied seed, not searched"),
                "legacy advertises Clearcasting reaction; generic Clearcasting proc semantics are not executable yet",
                ("generic bounded search currently excludes Moonfire at this level and scorer state" if bool((generic.get("capability") or {}).get("policy_search")) and not any(x.startswith("moonfire:") for x in generic_policy_actions) else "generic policy retains Moonfire in the selected priority"),
            ],
        },
        "unsupported_mechanic": {
            "status": "explicit",
            "generic": unsupported,
            "classification": ["unsupported mechanics remain visible and are never filled from legacy"],
        },
    }

    unexplained = [
        name for name, row in categories.items()
        if row.get("status") in {"unexplained", "mismatch"}
    ]
    return {
        "schema_version": COMPARE_SCHEMA_VERSION,
        "id": f"druid-caster:L{int(level)}",
        "class_name": "druid",
        "level": int(level),
        "status": "classified" if not unexplained else "unexplained_gaps",
        "legacy_record_id": legacy.get("record_id"),
        "generic_record_id": generic.get("record_id"),
        "summary": {
            "legacy_seconds_per_mob": _num(lt.get("seconds_per_mob")),
            "generic_seconds_per_mob": _num(gt.get("seconds_per_mob")),
            "seconds_per_mob_delta": _delta(gt.get("seconds_per_mob"), lt.get("seconds_per_mob")),
            "legacy_kill_seconds_per_mob": _num(lt.get("kill_seconds_per_mob")),
            "generic_kill_seconds_per_mob": _num(gt.get("kill_seconds_per_mob")),
            "legacy_recovery_seconds_per_mob": _num(lt.get("recovery_seconds_per_mob")),
            "generic_recovery_seconds_per_mob": _num(gt.get("recovery_seconds_per_mob")),
            "legacy_travel_seconds_per_mob": _num(lt.get("travel_seconds_per_mob")),
            "generic_travel_seconds_per_mob": _num(gt.get("travel_seconds_per_mob")),
        },
        "categories": categories,
        "unexplained_categories": unexplained,
        "numeric_scope_audit": {
            "classification": ("incomplete_timing_scope" if gt.get("travel_seconds_per_mob") is None or lt.get("travel_seconds_per_mob") is None else "component_timing_comparable"),
            "known_kill_delta_s_per_mob": _delta(gt.get("kill_seconds_per_mob"), lt.get("kill_seconds_per_mob")),
            "known_recovery_delta_s_per_mob": _delta(gt.get("recovery_seconds_per_mob"), lt.get("recovery_seconds_per_mob")),
            "travel_delta_s_per_mob": _delta(gt.get("travel_seconds_per_mob"), lt.get("travel_seconds_per_mob")),
            "unexplained_total_delta_bounded": False,
            "reason": "generic travel is not yet scored; no numeric residual can be attributed or bounded until both backends have the same timing scope" if gt.get("travel_seconds_per_mob") is None else "inspect remaining independent scorer differences",
        },
        "resolved_generic_mismatches": ([{
            "id": "post_death_damage_event_accounting",
            "category": "action_damage",
            "status": "resolved",
            "evidence": {
                "runtime_applied_damage": runtime_damage,
                "evaluation_accounted_damage": evaluation_damage,
                "delta": damage_accounting_delta,
                "ignored_after_target_death_count": int(gdamage.get("ignored_after_target_death_count") or 0),
            },
        }] if damage_accounting_ok and int(gdamage.get("ignored_after_target_death_count") or 0) > 0 else []),
        "authority": {
            "legacy": "independent legacy DecisionRecord",
            "generic": "independent generic DecisionRecord",
            "comparison": COMPARE_IMPLEMENTATION,
            "legacy_values_feed_generic_execution": False,
        },
    }


def build_backend_comparisons(
    *, legacy_payload: Mapping[str, Any], generic_payload: Mapping[str, Any], selected_level: int,
) -> list[dict[str, Any]]:
    return [classify_druid_caster_delta(
        legacy_payload=legacy_payload, generic_payload=generic_payload, level=int(selected_level)
    )]
