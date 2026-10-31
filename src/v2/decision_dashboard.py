from __future__ import annotations

"""Read-only aggregation for the player-facing Decisions browser surface."""

from pathlib import Path
import importlib
import os

from src.class_registry import class_names, get_definition
from src.game.data.forever.registry import registered_class_keys, generic_class_metadata
from src.shared.leveling.timing import TIMING_CONTRACT_VERSION

from .decision_artifacts import DECISION_ROOT, ROOT, read_json
from src.service.publication import resolve_published_path, read_published_class_artifact
from .icon_provenance import decorate_gear_stats, decorate_rotation_steps, decorate_talent_trees
from .class_model import Evaluation
from .reference_builds import all_reference_build_snapshots
from .backend_decision import DECISION_CONTRACT_VERSION, DecisionRecord, records_from_route_rows, records_from_native_generic_route_rows
from .generic_publication_coverage import summarize_generic_sections
from .generic_backend import build_partial_generic_records, backend_metadata as generic_backend_metadata
from .generic_frontier import (
    ROUTE_AUTHORITY, GENERIC_DRUID_ROUTE_LEVELS,
    build_generic_level_frontiers, serialize_generic_frontiers, generic_druid_route_publication,
    publish_generic_druid_route_rows,
)
from .generic_melee_routes import generic_melee_route_publication, MELEE_CORRIDORS
from .backend_compare import build_backend_comparisons, backend_metadata as compare_backend_metadata
from .backend_selection import select_backend
from src.version import SOFTWARE_VERSION


CLASSES = class_names("forever", ui_visible=True)
GENERIC_CLASSES = registered_class_keys()


class LegacyDecisionsDisabled(RuntimeError):
    """Legacy decision publication is quarantined; generic remains independent."""


def legacy_decisions_disabled() -> bool:
    """Opt-in G50 isolation gate. Do not mutate backend selection/readiness."""
    return os.environ.get("WOW_DISABLE_LEGACY_DECISIONS", "").strip().lower() in {"1", "true", "yes", "on"}


def _backend_catalog() -> list[dict]:
    """Backends selectable through the common Decision API."""
    return [
        {
            "id": "legacy",
            "version": SOFTWARE_VERSION,
            "implementation": "legacy_class_backend",
            "status": "available",
            "independent": True,
        },
        generic_backend_metadata(),
        compare_backend_metadata(),
    ]


def _class_metadata() -> dict:
    return {
        cls: {
            "display_name": get_definition("forever", cls).display_name,
            "tree_names": list(get_definition("forever", cls).tree_names),
            "primary_profiles": list(get_definition("forever", cls).primary_profiles),
            "capabilities": get_definition("forever", cls).capabilities.as_dict(),
            "accent": get_definition("forever", cls).accent,
            "proof_only": bool(get_definition("forever", cls).proof_only),
            "declared_routes": list(get_definition("forever", cls).route_definitions.keys()),
            "route_labels": {name: str(defn.get("label") or name) for name, defn in get_definition("forever", cls).route_definitions.items()},
        }
        for cls in CLASSES
    }


def _generic_ui_metadata(selected_level: int | None = None) -> dict:
    """Prefer full legacy display metadata when present, generic registry otherwise."""
    legacy = _class_metadata()
    native = generic_class_metadata(selected_level=selected_level)
    from src.game.data.forever.queue_capabilities import native_generic_queue_levels
    return {key: {"queued_native_decision_levels": list(native_generic_queue_levels(key)),
                  **{k: v for k, v in legacy.get(key, {}).items()
                      if k in ('display_name', 'tree_names', 'accent', 'primary_profiles')},
                  **native[key]} for key in native}


def _generic_decision_payload(selected_level: int | None) -> dict:
    """Build the independent generic product payload without reading legacy artifacts."""
    level = int(selected_level if selected_level is not None else 20)
    native_records = build_partial_generic_records(
        class_names=registered_class_keys(), selected_level=level, ruleset="forever"
    )
    records = [record.as_dict() for record in native_records]
    # G32 product closure: once canonical route navigation exists, the API no
    # longer rescans an arbitrary three-level preview window on every request.
    # Publish the selected-level frontier (reusing the already-built Druid
    # record) plus the real route corridor below.  The frontier builder itself
    # still supports bounded multi-level proof/runs.
    frontier_levels = (level,)
    druid_record = next((
        record for record in native_records
        if str(record.identity.get("class_name", "")).lower() == "druid"
    ), None)
    frontier_seed = ({level: druid_record} if druid_record is not None and level in frontier_levels else {})
    generic_frontiers = serialize_generic_frontiers(
        build_generic_level_frontiers(
            class_name="Druid", levels=frontier_levels, ruleset="forever", records_by_level=frontier_seed,
        ),
        class_name="Druid", ruleset="forever",
    )

    # G32: solve only the bounded corridor for which every earned talent point
    # is represented by executable Talent IR.  Do not invent dummy points for
    # L13+ / later trees merely to make the DP accept a longer path.
    route_report, regret_report, route_cache = generic_druid_route_publication(ruleset="forever")
    route_cache_public = {k: v for k, v in route_cache.items() if k != "selected_route_steps"}
    route_target = int(max(GENERIC_DRUID_ROUTE_LEVELS))
    route_target_row = dict((route_report.get("targets") or {}).get(str(route_target)) or {})
    regret_target_row = dict((regret_report.get("targets") or {}).get(str(route_target)) or {})
    unconstrained = dict((route_target_row.get("routes") or {}).get("unconstrained") or {})
    unconstrained_regret = dict((regret_target_row.get("routes") or {}).get("unconstrained") or {})
    generic_routes = {
        "schema_version": 1,
        "authority": ROUTE_AUTHORITY,
        "class_name": "Druid",
        "levels": list(GENERIC_DRUID_ROUTE_LEVELS),
        "target_level": route_target,
        "route_solving": True,
        "route_scope": "fully_executable_talent_budget_corridor",
        "path": dict(unconstrained.get("path") or {}),
        "transitions": list(unconstrained.get("transitions") or ()),
        "regret": unconstrained_regret,
        "named_routes": {
            name: {"status": row.get("status"), "reason": row.get("reason")}
            for name, row in dict(route_target_row.get("routes") or {}).items() if name != "unconstrained"
        },
        "route_blocker_above_level": route_target,
        "route_blocker": "later talent points are not yet fully represented by executable generic Talent IR; no dummy continuity is invented",
        "legacy_fallback": False,
        "publication_cache": dict(route_cache_public),
    }
    generic_endpoint_paths = {"druid": route_report}
    generic_spec_regret = {"druid": regret_report}
    # G33: the legacy route adapter cannot represent native generic exact-state
    # weights. Use the selected DP CandidateResults carried by the versioned
    # release snapshot; their score/identity is checked against route authority.
    native_route_rows = publish_generic_druid_route_rows(
        route_report, route_cache.get("selected_route_steps") or (),
    )
    generic_route_rows = {"druid": native_route_rows}
    # G39: the exact same native LevelFrontier -> solve_routes authority as
    # Druid, but with explicit *proxy* weapon/scoring limitations. Do not
    # relabel these as the mature Druid named-gear fixed-point corridor.
    melee_routes, melee_cache = generic_melee_route_publication()
    generic_class_routes = {"druid": dict(generic_routes)}
    for cls, result in melee_routes.items():
        generic_class_routes[cls] = {
            k: v for k, v in result.items()
            if k not in {"endpoint_report", "regret_report", "route_rows"}
        }
        generic_class_routes[cls]["publication_cache"] = dict(melee_cache)
        generic_endpoint_paths[cls] = dict(result["endpoint_report"])
        generic_spec_regret[cls] = dict(result["regret_report"])
        generic_route_rows[cls] = dict(result["route_rows"])
    selected_route = dict(dict(native_route_rows.get(str(route_target)) or {}).get("routes") or {}).get("unconstrained") or {}
    generic_routes["normal_route_selectable"] = selected_route.get("status") == "available"
    generic_routes["normal_route_step_count"] = len(selected_route.get("rows") or ())
    generic_routes["quality_warnings"] = sorted({
        w for row in selected_route.get("rows") or () for w in row.get("quality_warnings") or ()
    })
    generic_routes["classified_limitations"] = [
        "travel_time_not_modeled", "attack_table_expected_value_only",
        "candidate_specific_gear_fixed_point_not_supported", "upper_talent_tree_unrepresented",
    ]
    # G48a: class-route metadata must be a snapshot of the *final* route
    # authority. The earlier copy predated normal_route_selectable/warnings,
    # incorrectly showing Druid's actual selectable route as blocked in UI.
    generic_class_routes["druid"] = dict(generic_routes)

    for record in records:
        if str((record.get("identity") or {}).get("class_name", "")).lower() != "druid":
            continue
        provenance = dict(record.get("provenance") or {})
        provenance["generic_level_frontier"] = {
            "authority": generic_frontiers["authority"],
            "levels": list(generic_frontiers["levels"]),
            "frontier_count": int(generic_frontiers["frontier_count"]),
            "candidate_count": int(generic_frontiers["candidate_count"]),
            "route_solving": False,
            "legacy_fallback": False,
        }
        provenance["generic_route_solve"] = {
            "authority": ROUTE_AUTHORITY,
            "levels": list(GENERIC_DRUID_ROUTE_LEVELS),
            "target_level": route_target,
            "route_solving": True,
            "route_scope": "fully_executable_talent_budget_corridor",
            "endpoint_allocation": (generic_routes.get("path") or {}).get("allocation"),
            "regret_percent": generic_routes.get("regret", {}).get("regret_percent"),
            "publication_cache": dict(route_cache_public),
            "legacy_fallback": False,
        }
        record["provenance"] = provenance
        capability = dict(record.get("capability") or {})
        capability.update({
            "route_solving": True,
            "normal_route_selectable": bool(generic_routes["normal_route_selectable"]),
            "normal_route_scope": "druid_caster_L10_L14_only",
            "route_solving_scope": "bounded_fully_executable_talent_budget_corridor",
            "route_solving_levels": list(GENERIC_DRUID_ROUTE_LEVELS),
        })
        record["capability"] = capability
        record["unsupported_mechanics"] = [
            x for x in list(record.get("unsupported_mechanics") or ()) if str(x) != "route_solving"
        ]

    for record in records:
        cls = str((record.get("identity") or {}).get("class_name", "")).lower()
        if cls not in melee_routes:
            continue
        route = melee_routes[cls]
        record["capability"] = {
            **dict(record.get("capability") or {}),
            "route_solving": True,
            "normal_route_selectable": bool(route["normal_route_selectable"]),
            "route_solving_levels": list(route["levels"]),
            "route_solving_scope": "bounded_early_talent_proxy_scenario_not_final_leveling_score",
        }
        record["provenance"] = {
            **dict(record.get("provenance") or {}),
            "generic_route_solve": {
                "authority": ROUTE_AUTHORITY, "levels":list(route["levels"]),
                "target_level":route["target_level"],
                "endpoint_allocation":route["path"].get("allocation"),
                "normal_route_selectable": bool(route["normal_route_selectable"]),
                "publication_cache": dict(melee_cache),
                "selected_record_is_route_scored":False,
                "legacy_fallback":False,
            },
        }
        record["unsupported_mechanics"] = [
            x for x in record.get("unsupported_mechanics", ()) if str(x) != "route_solving"
        ]

    # G48c: route-scored decisions are a separate, explicitly native collection.
    # The selected-level source-only records above must remain unchanged.
    native_route_decisions = [record.as_dict() for record in
                              records_from_native_generic_route_rows(generic_route_rows)]

    # G48a: every class gets the same explicit product-section coverage,
    # including honest absence of gear/weights and out-of-scope routes.
    class_metadata = _generic_ui_metadata(selected_level=level)
    for record in records:
        cls = str((record.get("identity") or {}).get("class_name") or "").lower()
        capability = dict(record.get("capability") or {})
        capability["publication_sections"] = summarize_generic_sections(
            record, class_metadata=class_metadata.get(cls, {}),
            route_publication=generic_class_routes.get(cls),
        )
        record["capability"] = capability

    return {
        "schema_version": 1,
        "decision_contract_version": DECISION_CONTRACT_VERSION,
        "ruleset": "forever",
        "active_backend": "generic",
        "backends": _backend_catalog(),
        "decisions": records,
        "native_route_decisions": native_route_decisions,
        "product_surface": {
            "route_navigation": True,
            "frontier_navigation": True,
            "status": "generic_multi_class_bounded_routes" if all(x["normal_route_selectable"] for x in melee_routes.values()) and generic_routes["normal_route_selectable"] else "generic_route_partial",
            "note": "Druid L10–L14 native named-gear route and Warrior L10–L12 / Rogue L10–L14 native proxy-weapon routes are selectable. Their scoring is not cross-class comparable; no higher-level talent continuation, invented talent points or legacy scorer fallback.",
        },
        "selected_level": level,
        "levels": sorted(set([level, *GENERIC_DRUID_ROUTE_LEVELS])),
        "generic_frontiers": generic_frontiers,
        "generic_routes": generic_routes,
        "generic_class_routes": generic_class_routes,
        "cards": [],
        "curves": {},
        "class_metadata": class_metadata,
        "forever_builds": {},
        "endpoint_paths": generic_endpoint_paths,
        "spec_regret": generic_spec_regret,
        "dual_spec": {},
        "spec_matrix": {},
        "route_rows": generic_route_rows,
        "per_level_rows": {"druid": list(selected_route.get("rows") or ())},
        "reference_builds": {},
        "per_level_best": {"enabled": False, "reason": "unsupported_by_selected_backend"},
        "questions": {
            "endpoint_paths": True,
            "constrained_regret": True,
            "generic_route_target": route_target,
        },
        "coverage": {
            "druid": {
                "levels": list(GENERIC_DRUID_ROUTE_LEVELS),
                "endpoint_paths": True,
                "route_authority": ROUTE_AUTHORITY,
            },
            **{cls: {"levels":list(MELEE_CORRIDORS[cls]),"endpoint_paths":True,
                     "route_authority":ROUTE_AUTHORITY, "scenario_proxy":True}
               for cls in MELEE_CORRIDORS},
        },
        "timing_contract": TIMING_CONTRACT_VERSION,
        "cross_class_timing_comparable": False,
        "cross_class_comparable": False,
        "comparability_note": "Generic Druid route timing is native generic runtime timing over the bounded fully-executable talent corridor; later levels and cross-class comparison remain explicitly unsupported.",
        "authority_note": "Generic backend publication is independent and fail-closed: native CandidateResult/LevelFrontier rows feed the shared canonical route DP for the fully represented corridor; there is no generic→legacy scorer fallback.",
    }


def _talent_rules(class_name: str) -> dict:
    """Return static Forever talent metadata through the class registry."""
    definition = get_definition("forever", class_name)
    module_name = definition.talent_module or definition.engine_module
    try:
        module = importlib.import_module(module_name)
        return dict(getattr(module, "TALENT_RULES", {}) or {})
    except Exception:
        return {}



def _talent_point_contract(class_name: str, row: dict) -> dict:
    """Generic Forever invariant: one talent point per level from L10 through L60."""
    level = int(row.get("level", 0) or 0)
    expected = max(0, min(51, level - 9))
    ranks = {str(k): int(v) for k, v in dict(row.get("talent_ranks") or {}).items() if int(v) > 0}
    rules = _talent_rules(class_name)
    recognized = sum(rank for name, rank in ranks.items() if name in rules)
    unknown = sorted(name for name in ranks if name not in rules)
    ok = bool(ranks or expected == 0) and recognized == expected and not unknown
    return {
        "ok": ok,
        "expected": expected,
        "recognized": recognized,
        "unknown": unknown,
    }

def _talent_trees(class_name: str, row: dict) -> dict:
    """Normalize machine-readable talent ranks into tree-grouped UI data."""
    ranks = {str(k): int(v) for k, v in dict(row.get("talent_ranks") or {}).items() if int(v) > 0}
    points = {str(k): int(v) for k, v in dict(row.get("tree_points") or {}).items()}
    rules = _talent_rules(class_name)
    names = list(points)
    for _talent, rule in rules.items():
        if rule and str(rule[0]) not in names:
            names.append(str(rule[0]))
    trees = {name: {"points": int(points.get(name, 0)), "talents": []} for name in names}
    unassigned = []
    for talent, rank in ranks.items():
        rule = rules.get(talent)
        if rule:
            tree = str(rule[0])
            trees.setdefault(tree, {"points": int(points.get(tree, 0)), "talents": []})["talents"].append({"name": talent, "rank": rank})
        else:
            unassigned.append({"name": talent, "rank": rank})
    for name, tree in trees.items():
        if name not in points:
            tree["points"] = sum(x["rank"] for x in tree["talents"])
    if unassigned:
        trees["unassigned"] = {"points": sum(x["rank"] for x in unassigned), "talents": unassigned}
    return trees


def _route_identity_contract(class_name: str, route_name: str, row: dict) -> dict:
    """Validate player-facing route identity against the class registry.

    Endpoint paths preserve talent continuity, but their gameplay profile can be
    the unconstrained scorer winner.  A named route such as Druid Feral · Cat
    must never inherit Bear timing/gear simply because the exact route-specific
    matrix is absent.  Registry ``publication_profile`` / ``score_profile`` is
    therefore a hard publication contract for routes that declare one.
    """
    definition = get_definition("forever", class_name)
    route_def = dict(definition.route_definitions.get(route_name) or {})
    expected = route_def.get("publication_profile") or route_def.get("score_profile")
    actual = row.get("combat_profile") or row.get("profile")
    ok = True
    reason = None
    if expected:
        expected = str(expected)
        actual = str(actual or "")
        # The Druid scorer calls Cat's fixed scoring profile ``feral`` but the
        # player-facing publication profile is ``cat``.  If publication_profile
        # is explicit it already contains the UI identity and wins.
        if route_def.get("publication_profile"):
            expected_publication = str(route_def["publication_profile"])
        else:
            expected_publication = expected
        ok = bool(actual) and actual == expected_publication
        if not ok:
            reason = f"route {route_name} requires combat_profile={expected_publication}, got {actual or 'missing'}"
    else:
        expected_publication = None
    return {
        "ok": bool(ok),
        "route": str(route_name),
        "expected_score_profile": (str(route_def.get("score_profile")) if route_def.get("score_profile") else None),
        "expected_publication_profile": expected_publication,
        "actual_combat_profile": (str(actual) if actual is not None else None),
        "reason": reason,
    }


def _derive_seconds_per_mob(row: dict) -> float | None:
    value = row.get("seconds_per_mob")
    if value is not None:
        return float(value)
    score = row.get("score_s_per_100")
    if score is not None and float(score) > 0:
        return float(score) / 100.0
    rate = row.get("mobs_per_hour")
    if rate is not None and float(rate) > 0:
        return 3600.0 / float(rate)
    return None


def _canonical_route_rows(class_name: str, endpoint_class: dict, matrix_class: dict) -> dict:
    """Merge endpoint path identity with scorer/spec-matrix detail once, server-side.

    Talent identity comes from the preserved endpoint path. Gameplay/timing/gear and
    stat weights come from the fixed-talent spec matrix when available. This is the
    single row contract consumed by both the focused view and route timeline.
    """
    out: dict[str, dict] = {}
    matrices = dict((matrix_class or {}).get("matrices") or {})
    for target, target_row in dict((endpoint_class or {}).get("targets") or {}).items():
        routes_out: dict[str, dict] = {}
        for route_name, route_row in dict((target_row or {}).get("routes") or {}).items():
            if (route_row or {}).get("status") != "available":
                routes_out[route_name] = {"status": (route_row or {}).get("status", "unavailable"), "rows": []}
                continue
            steps = list(((route_row or {}).get("path") or {}).get("steps") or ())
            matrix = matrices.get(f"{int(target)}:{route_name}") or {}
            mrows = list(matrix.get("rows") or ())
            by_level: dict[int, dict] = {}
            for step in steps:
                if step.get("level") is not None:
                    by_level[int(step["level"])] = dict(step)
            for mrow in mrows:
                if mrow.get("level") is None:
                    continue
                level = int(mrow["level"]); base = dict(by_level.get(level) or {})
                # Endpoint paths are talent-continuity authority only.  Their
                # gameplay profile may be the unconstrained scorer winner (e.g.
                # a Feral-talent path scored as Bear).  Once a route-specific
                # matrix row exists, do not inherit any endpoint timing/gear/
                # objective fields that the matrix did not publish.
                identity = {
                    k: base.get(k)
                    for k in (
                        "level", "talent_added", "allocation", "talent_ranks",
                        "tree_points", "talent_family", "model_fidelity",
                    )
                    if base.get(k) is not None
                }
                merged = {**dict(mrow), **identity}
                by_level[level] = merged
            rows = []
            for level, row0 in sorted(by_level.items()):
                row = dict(row0); row["level"] = level
                row["seconds_per_mob"] = _derive_seconds_per_mob(row)
                row["talent_trees"] = decorate_talent_trees(class_name, _talent_trees(class_name, row))
                row["rotation_steps"] = decorate_rotation_steps(
                    class_name, row.get("rotation") or row.get("policy"), level=level
                )
                if isinstance(row.get("gear_stats"), dict):
                    row["gear_stats"] = decorate_gear_stats(row.get("gear_stats"))
                # Hard route-identity contract comes before stat weights.  In
                # particular, never label an endpoint-only Bear scorer state as
                # ``Feral · Cat`` just because the talent family is Feral.
                identity_contract = _route_identity_contract(class_name, route_name, row)
                row["route_identity"] = identity_contract
                row["route_identity_contract_ok"] = bool(identity_contract["ok"])
                if identity_contract["ok"]:
                    # Hard product contract: a normal selectable route step always
                    # carries canonical stat weights for this exact route state.
                    from .decision_stat_weights import ensure_row_stat_weights
                    row = ensure_row_stat_weights(class_name, row, route_name=route_name, strict=False)
                else:
                    row.pop("stat_weights", None)
                    details = dict(row.get("details") or {})
                    details.pop("stat_weights", None)
                    row["details"] = details
                    row["stat_weights_contract_ok"] = False
                    row["stat_weights_error"] = identity_contract["reason"]
                point_contract = _talent_point_contract(class_name, row)
                row["talent_point_contract"] = point_contract
                row["talent_points_contract_ok"] = bool(point_contract["ok"])
                sources = []
                if any(int(s.get("level", -1)) == level for s in steps): sources.append("endpoint_path")
                if any(int(r.get("level", -1)) == level for r in mrows): sources.append("spec_matrix")
                row["data_sources"] = sources
                row["decision_mode"] = route_name
                row["decision_row_id"] = f"{class_name}:{target}:{route_name}:{level}:{row.get('allocation','')}"
                missing = {}
                if not row.get("talent_ranks"):
                    missing["talents"] = "machine-readable talent ranks unavailable for this route step"
                elif not row.get("talent_points_contract_ok"):
                    pc = row.get("talent_point_contract") or {}
                    missing["talent_points"] = f"current talent-point budget mismatch: {pc.get('recognized')} / {pc.get('expected')}"
                if not row.get("stat_weights"):
                    missing["stat_weights"] = row.get("stat_weights_error") or "canonical stat-weight contract unavailable"
                gear_stats = row.get("gear_stats") or {}
                if not (gear_stats.get("slots") if isinstance(gear_stats, dict) else None):
                    missing["gear"] = "named gear snapshot unavailable for this route step"
                if row.get("seconds_per_mob") is None:
                    missing["timing"] = "scorer timing unavailable for this route step"
                row["missing"] = missing
                # G01: every normal canonical route row crosses the backend-neutral
                # DecisionRecord boundary before reaching the listener/API.  The
                # current listener still receives a compatibility row, but that
                # row is now derived from the stable contract rather than being
                # the publication authority itself.
                record = DecisionRecord.from_legacy_route_row(
                    class_name=class_name, target_level=int(target),
                    route_name=str(route_name), row=row,
                )
                rows.append(record.legacy_route_row())
            identity_ok = bool(rows) and all(bool(r.get("route_identity_contract_ok")) for r in rows)
            weights_ok = bool(rows) and all(bool(r.get("stat_weights_contract_ok")) and bool(r.get("stat_weights")) for r in rows)
            points_ok = bool(rows) and all(bool(r.get("talent_points_contract_ok")) for r in rows)
            decision_ok = identity_ok and weights_ok and points_ok
            if not rows:
                status, reason = "route_steps_unavailable", "route steps unavailable"
            elif not identity_ok:
                status, reason = "route_identity_invalid", "one or more route steps violate the named route combat-profile contract"
            elif not points_ok:
                status, reason = "talent_points_invalid", "one or more route steps failed the current talent-point budget"
            elif not weights_ok:
                status, reason = "stat_weights_unavailable", "one or more route steps failed the canonical stat-weight contract"
            else:
                status, reason = "available", None
            routes_out[route_name] = {
                "status": status,
                "rows": rows,
                "matrix_status": matrix.get("status", "missing"),
                "route_identity_complete": identity_ok,
                "stat_weights_complete": weights_ok,
                "talent_points_complete": points_ok,
                "reason": reason,
            }
        out[str(target)] = {"routes": routes_out}
    return out


def _throughput(row: dict | None) -> float | None:
    row = row or {}
    value = row.get("mobs_per_hour")
    if value is not None:
        return float(value)
    score = row.get("score_s_per_100")
    if score is None or float(score) <= 0:
        return None
    return 360000.0 / float(score)


def _level_rows(class_name: str, viewer: dict) -> list[dict]:
    views = viewer.get("views") or {}
    definition = get_definition("forever", class_name)
    view = next((views.get(name) for name in definition.viewer_view_priority if views.get(name)), {})
    return list(view.get("level_summaries") or ())


def _matrix_has_stats_and_rotation(class_payload: dict | None) -> bool:
    matrices = dict((class_payload or {}).get("matrices") or {})
    for matrix in matrices.values():
        rows = list((matrix or {}).get("rows") or ())
        if rows and all((row.get("rotation") or row.get("policy")) and row.get("stat_weights") for row in rows):
            return True
    return False


def _decorate_decision_row(class_name: str, row0: dict, *, source: str, route_name: str | None = None) -> dict:
    row = dict(row0 or {})
    if not row:
        return row
    level = int(row.get("level", 0) or 0)
    row["level"] = level
    ev = Evaluation.from_published_row(row)
    row.update(ev.published_fields())
    row["talent_trees"] = decorate_talent_trees(class_name, _talent_trees(class_name, row))
    row["rotation_steps"] = decorate_rotation_steps(class_name, row.get("rotation") or row.get("policy"), level=level)
    if isinstance(row.get("gear_stats"), dict):
        row["gear_stats"] = decorate_gear_stats(row.get("gear_stats"))
    row.setdefault("data_sources", [])
    if source not in row["data_sources"]:
        row["data_sources"] = [*row["data_sources"], source]
    row["decision_row_id"] = f"{class_name}:{row.get('decision_mode','route')}:{level}:{row.get('allocation','')}"
    if not row.get("stat_weights") and (row.get("details") or {}).get("stat_weights"):
        row["stat_weights"] = row["details"]["stat_weights"]
    if not row.get("stat_weights_error") and (row.get("details") or {}).get("stat_weights_error"):
        row["stat_weights_error"] = row["details"]["stat_weights_error"]
    from .decision_stat_weights import ensure_row_stat_weights
    row = ensure_row_stat_weights(class_name, row, route_name=route_name, strict=False)
    point_contract = _talent_point_contract(class_name, row)
    row["talent_point_contract"] = point_contract
    row["talent_points_contract_ok"] = bool(point_contract["ok"])
    return row


def _card(class_name: str, summary: dict | None, viewer: dict) -> dict:
    best = dict((summary or {}).get("best") or {})
    event = dict((summary or {}).get("event_validated_best") or {})
    definition = get_definition("forever", class_name)
    fidelity = best.get("model_fidelity") or ((viewer.get("capabilities") or {}).get("model_fidelity")) or definition.fidelity()
    return {
        "class": class_name,
        "available": bool(best),
        "level": (summary or {}).get("level"),
        "fast_best": best,
        "event_validated_best": event or None,
        "decision_change_kind": (summary or {}).get("decision_change_kind", "none"),
        "fidelity": fidelity,
        "coverage": {
            "per_level_best": bool(best),
            "fidelity_known": bool(fidelity),
        },
    }


def build_decision_payload(
    project_root: Path | str = ROOT,
    selected_level: int | None = None,
    backend_id: str | None = None,
    class_name: str | None = None,
) -> dict:
    selection = select_backend(requested=backend_id, class_key=class_name,
                               level=selected_level)
    backend_key = selection["backend"]
    # G50a: refuse legacy/compare before reading legacy artifacts or invoking
    # their scorers.  Do NOT silently promote an ineligible auto selection to
    # generic: capability readiness continues to be decided by the registry.
    if backend_key in {"legacy", "compare"} and legacy_decisions_disabled():
        raise LegacyDecisionsDisabled(
            f"{backend_key} decisions unavailable: WOW_DISABLE_LEGACY_DECISIONS is enabled"
        )
    if backend_key == "generic":
        payload = _generic_decision_payload(selected_level)
        payload["backend_selection"] = selection
        return payload
    if backend_key == "compare":
        level = int(selected_level if selected_level is not None else 20)
        # Comparison orchestrates two independently produced payloads. Legacy is
        # never used as an input to generic execution.
        legacy_payload = build_decision_payload(project_root=project_root, selected_level=level, backend_id="legacy")
        generic_payload = _generic_decision_payload(level)
        comparisons = build_backend_comparisons(
            legacy_payload=legacy_payload, generic_payload=generic_payload, selected_level=level,
        )
        druid_meta = {k: v for k, v in _class_metadata().items() if str(k).lower() == "druid"}
        return {
            "schema_version": 1,
            "decision_contract_version": DECISION_CONTRACT_VERSION,
            "ruleset": "forever",
            "active_backend": "compare",
            "backend_selection": selection,
            "backends": _backend_catalog(),
            "decisions": [],
            "comparisons": comparisons,
            "product_surface": {
                "route_navigation": False,
                "comparison": True,
                "status": "legacy_vs_generic_delta_decomposition",
                "note": "Legacy and generic are executed independently, then differences are classified machine-readably. Legacy values never feed generic execution.",
            },
            "selected_level": level,
            "levels": [level],
            "cards": [], "curves": {}, "class_metadata": druid_meta,
            "forever_builds": {}, "endpoint_paths": {}, "spec_regret": {}, "dual_spec": {},
            "spec_matrix": {}, "route_rows": {}, "per_level_rows": {}, "reference_builds": {},
            "per_level_best": {"enabled": False, "reason": "comparison_surface"},
            "questions": {}, "coverage": {},
            "timing_contract": TIMING_CONTRACT_VERSION,
            "cross_class_timing_comparable": False, "cross_class_comparable": False,
            "comparability_note": "Comparison decomposes known Druid caster deltas; it is not a throughput ranking.",
            "authority_note": "Compare backend is an oracle surface only: it classifies independent legacy and generic publications and is never simulation authority.",
        }

    root = Path(project_root)
    artifacts = {
        name: read_published_class_artifact(root, Path("decisions") / "forever" / f"{name}.json")
        for name in ("endpoint_paths", "spec_regret", "dual_spec", "spec_matrix")
    }
    viewers = {
        cls: read_json(resolve_published_path(root, Path("games") / f"forever-{cls}" / "v2" / "viewer.json"), {}) or {}
        for cls in CLASSES
    }
    level_maps = {cls: {int(r["level"]): r for r in _level_rows(cls, viewers[cls]) if r.get("level") is not None} for cls in CLASSES}
    route_rows = {
        cls: _canonical_route_rows(
            cls,
            (artifacts["endpoint_paths"].get("classes") or {}).get(cls, {}),
            (artifacts["spec_matrix"].get("classes") or {}).get(cls, {}),
        )
        for cls in CLASSES
    }
    # Route availability is a registry contract, not an accidental property of
    # whichever bounded frontier rows survived.  Materialize missing declared
    # routes as explicit unavailable entries so the browser can show them rather
    # than silently deleting Mage/Paladin specs from the selector.
    for cls in CLASSES:
        declared=list(get_definition("forever", cls).route_definitions.keys())
        endpoint_targets=set(str(k) for k in (((artifacts["endpoint_paths"].get("classes") or {}).get(cls, {}).get("targets") or {}).keys()))
        matrix_targets=set(str(int(m.get("target_level"))) for m in ((((artifacts["spec_matrix"].get("classes") or {}).get(cls, {}).get("matrices") or {}).values())) if m.get("target_level") is not None)
        for target in sorted(endpoint_targets | matrix_targets, key=lambda x:int(x)):
            target_routes=route_rows[cls].setdefault(target,{"routes":{}}).setdefault("routes",{})
            for route in declared:
                target_routes.setdefault(route,{"status":"unavailable","rows":[],"reason":"declared route not preserved in this publication"})
    per_level_rows = {}
    for cls in CLASSES:
        rows=[]
        # Mature Mage now publishes an explicit per-level-best path whose
        # structural unlocks may be event-reranked (e.g. Ice Lance). Prefer that
        # path over re-deriving the mode from analytic level-summary leaders.
        views=viewers[cls].get('views') or {}
        definition=get_definition('forever',cls)
        vv=next((views.get(name) for name in definition.viewer_view_priority if views.get(name)),{}) or {}
        explicit=list((((vv.get('paths') or {}).get('per_level_best') or {}).get('steps') or ()))
        summaries=list(_level_rows(cls, viewers[cls]))
        # Experimental classes publish the complete current winner in
        # level_summaries[].best.  Consume that object directly so the listener
        # cannot resurrect an older/minimal path row and lose the converged gear
        # snapshot.  Mage keeps its explicit per-level path because that path may
        # contain event-reranked structural unlocks (Ice Lance).
        if cls == 'mage' and explicit:
            for src in explicit:
                row=dict(src); row['level']=int(row.get('level',0)); row['decision_mode']='per_level_best'; rows.append(row)
        elif summaries:
            for summary in summaries:
                rich=dict(summary.get("best") or {})
                event=dict(summary.get("event_validated_best") or {})
                if not rich and not event:
                    continue
                # A modern experimental run enriches summary.best after event
                # reranking.  Only fall back to the raw event row for legacy
                # publications that do not have a rich best payload. Mage's
                # legacy level-summary fallback still overlays event timing.
                row=({**rich, **event} if cls == 'mage' else (rich or event))
                row["level"]=int(summary.get("level", row.get("level", 0)))
                row["decision_mode"]="per_level_best"
                row["respec_seconds"]=1.0
                rows.append(row)
        elif explicit:
            # Legacy experimental publication fallback.
            for src in explicit:
                row=dict(src); row['level']=int(row.get('level',0)); row['decision_mode']='per_level_best'; rows.append(row)
        decorated=[_decorate_decision_row(cls, row, source="level_summaries.best" if cls != "mage" else "explicit_per_level_path", route_name="per_level_best") for row in rows]
        # Anything exposed as a normal per-level selection must satisfy the same
        # hard weight contract. Failed legacy rows stay out of the selectable
        # surface instead of rendering a misleading "unavailable" placeholder.
        per_level_rows[cls]=[row for row in decorated if row.get("stat_weights_contract_ok") and row.get("stat_weights") and row.get("talent_points_contract_ok")]
    levels = sorted({level for rows in level_maps.values() for level in rows})
    if selected_level is None:
        selected_level = levels[-1] if levels else 20
    cards = [_card(cls, level_maps[cls].get(int(selected_level)), viewers[cls]) for cls in CLASSES]
    curves = {
        cls: [
            {
                "level": level,
                "mobs_per_hour": _throughput(row.get("event_validated_best") or row.get("best")),
                "fast_mobs_per_hour": _throughput(row.get("best")),
            }
            for level, row in sorted(level_maps[cls].items())
        ]
        for cls in CLASSES
    }
    forever_builds = {}
    for cls in CLASSES:
        ep = (artifacts["endpoint_paths"].get("classes") or {}).get(cls, {}) or {}
        viewer_build = (viewers.get(cls) or {}).get("forever_build") or {}
        build = ep.get("forever_build") or viewer_build
        if build:
            forever_builds[cls] = dict(build)
        elif ep or viewers.get(cls):
            forever_builds[cls] = {
                "schema_version": 1, "build_id": "forever-beta@2026-10-02",
                "as_of": "2026-10-02", "source": "legacy_compat_default",
            }

    decision_records = [record.as_dict() for record in records_from_route_rows(route_rows)]

    return {
        "schema_version": 1,
        "decision_contract_version": DECISION_CONTRACT_VERSION,
        "ruleset": "forever",
        "decisions": decision_records,
        "active_backend": "legacy",
        "backend_selection": selection,
        "backends": _backend_catalog(),
        "product_surface": {"route_navigation": True, "status": "available"},
        "forever_builds": forever_builds,
        "selected_level": int(selected_level),
        "levels": levels,
        "cards": cards,
        "curves": curves,
        "class_metadata": _class_metadata(),
        "endpoint_paths": artifacts["endpoint_paths"].get("classes", {}),
        "spec_regret": artifacts["spec_regret"].get("classes", {}),
        "dual_spec": artifacts["dual_spec"].get("classes", {}),
        "spec_matrix": artifacts["spec_matrix"].get("classes", {}),
        "route_rows": route_rows,
        "per_level_rows": per_level_rows,
        "reference_builds": all_reference_build_snapshots(CLASSES),
        "per_level_best": {"enabled": True, "respec_seconds": 1.0, "semantics": "independent best searched build at each level"},
        "questions": {
            # These are capability/data-coverage flags, not optimistic promises.
            # A result is marked true only when every requested Forever class has
            # a corresponding artifact/result at the selected level or target.
            "per_level_best": all(card["coverage"]["per_level_best"] for card in cards),
            "endpoint_paths": all(bool((artifacts["endpoint_paths"].get("classes") or {}).get(cls)) for cls in CLASSES),
            "dual_spec_pair": all((artifacts["dual_spec"].get("classes") or {}).get(cls, {}).get("status") == "available" for cls in CLASSES),
            "constrained_regret": all(bool((artifacts["endpoint_paths"].get("classes") or {}).get(cls)) and bool(level_maps[cls]) for cls in CLASSES),
            "route_stats_and_rotation": all(_matrix_has_stats_and_rotation((artifacts["spec_matrix"].get("classes") or {}).get(cls, {})) for cls in CLASSES),
        },
        "coverage": {
            cls: {
                "levels": sorted(level_maps[cls]),
                "endpoint_paths": bool((artifacts["endpoint_paths"].get("classes") or {}).get(cls)),
                "dual_spec": (artifacts["dual_spec"].get("classes") or {}).get(cls, {}).get("status", "missing"),
                "matrices": len(((artifacts["spec_matrix"].get("classes") or {}).get(cls, {}).get("matrices") or {})),
                "route_stats_and_rotation": _matrix_has_stats_and_rotation((artifacts["spec_matrix"].get("classes") or {}).get(cls, {})),
            }
            for cls in CLASSES
        },
        "timing_contract": TIMING_CONTRACT_VERSION,
        "cross_class_timing_comparable": all(
            all(bool(r.get("timing_consistent")) and r.get("timing_contract") == TIMING_CONTRACT_VERSION for r in rows)
            for rows in per_level_rows.values() if rows
        ),
        "cross_class_comparable": False,
        "comparability_note": (
            "Timing buckets now share one kill -> recovery -> between-pull travel contract, but raw mobs/hour is still diagnostic only and is NOT a class ranking. "
            + ", ".join(get_definition("forever", cls).display_name for cls in CLASSES)
            + " backends may declare different fidelity, pull, gear, and combat contracts; proof-only backends are explicitly marked. "
            "Compare specs within a class until the shared combat/gear/pull contract is complete."
        ),
        "authority_note": "Fast broad search, optional deterministic event-finalist validation, and explicit per-class fidelity; no HTTP-triggered optimization.",
    }
