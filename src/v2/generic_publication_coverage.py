from __future__ import annotations

"""G48a: backend-neutral product sections derived from native generic facts.

This is publication metadata, never a scorer. A route solved elsewhere does not
make the selected-level DecisionRecord a route-scored CandidateResult.
"""

from collections.abc import Mapping


SECTION_NAMES = (
    "selected_build", "gear", "stat_weights", "policy", "timing", "route", "fidelity_provenance"
)


def _section(status: str, reason: str) -> dict[str, str]:
    assert status in {"available", "partial", "unavailable", "out_of_scope"}
    return {"status": status, "reason": reason}


def summarize_generic_sections(
    record: Mapping, *, class_metadata: Mapping, route_publication: Mapping | None = None,
) -> dict:
    """Summarize a single generic record without inventing absent gear/weights/routes."""
    identity = record.get("identity") or {}
    level = int(identity.get("level") or 0)
    gear = record.get("gear") or {}
    weights = record.get("stat_weights") or {}
    talents = record.get("talents") or {}
    policy = record.get("policy") or {}
    timing = record.get("timing") or {}
    fidelity = record.get("fidelity") or {}
    provenance = record.get("provenance") or {}
    route = route_publication or {}
    levels = tuple(int(x) for x in class_metadata.get("planning_levels") or ())

    has_policy = bool(policy.get("rules"))
    talent_selected = bool(talents.get("status") == "joint_talent_policy_search"
                           and talents.get("search_performed"))
    has_gear = bool(gear.get("status") == "selected_named_catalogue_gear"
                    and gear.get("slots"))
    has_weights = bool(weights.get("ranked") or weights.get("stats"))
    seconds = timing.get("seconds_per_mob")

    if not has_policy:
        selected_build = _section("unavailable", "No selected executable policy/build for this level")
    elif talent_selected:
        selected_build = _section("partial", "Executable policy and bounded talent selection; full leveling build not verified")
    else:
        selected_build = _section("partial", "Executable policy only; no verified optimized talent build")

    if not levels:
        route_status = _section("unavailable", "No verified native route corridor for this class")
    elif level not in levels:
        route_status = _section("out_of_scope", f"Native route corridor L{min(levels)}–L{max(levels)}; selected L{level} is outside")
    elif not route.get("route_solving") or not route.get("normal_route_selectable"):
        route_status = _section("unavailable", "Declared corridor lacks a selectable native route publication")
    else:
        route_status = _section("partial", "Bounded native route available separately; this DecisionRecord is not route-scored")

    sections = {
        "selected_build": selected_build,
        "gear": (_section("available", "Named catalogue gear selected by native generic optimizer") if has_gear
                 else _section("unavailable", str(gear.get("reason") or "No selected named gear for this class/level"))),
        "stat_weights": (_section("available", "Native scorer sensitivity published") if has_weights
                         else _section("unavailable", "No source-backed native stat sensitivities for this class/level")),
        "policy": (_section("available", "Executable selected Policy IR") if has_policy
                   else _section("unavailable", "No executable selected Policy IR")),
        "timing": (_section("available", "Complete canonical timing contract") if timing.get("complete") is True
                   else _section("partial", "Combat/recovery timing only; full travel-inclusive timing unsupported") if seconds is not None
                   else _section("unavailable", "No evaluated seconds-per-mob timing")),
        "route": route_status,
        "fidelity_provenance": (_section("partial", "Source Game IR and native provenance; full leveling/cross-class fidelity not verified")
                                if provenance.get("legacy_fallback") is False and fidelity.get("rating")
                                and provenance.get("game_ir") is not None
                                else _section("unavailable", "Source-backed Game IR or native fidelity evidence missing")),
    }
    assert tuple(sections) == SECTION_NAMES
    return {"schema_version": 1, "sections": sections, "authority": "generic_record_and_native_route_publication"}
