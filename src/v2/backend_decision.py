from __future__ import annotations

"""Backend-neutral player decision contract.

This module is the stable publication boundary shared by the legacy and future
Generic WoW backends.  Backend-specific representations may be adapted into
``DecisionRecord`` but the API/listener contract above this layer must not grow
class-shaped top-level fields.

G01 deliberately keeps a nested compatibility row so the existing listener can
move onto the new authority without a big-bang UI rewrite.  Subsequent generic
backend increments replace that compatibility payload with first-class actor,
resource, action and policy records.
"""

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Mapping, Sequence

from src.class_registry import get_definition
from src.version import SOFTWARE_VERSION
from .class_model import Evaluation


DECISION_CONTRACT_VERSION = 1


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


@dataclass(frozen=True)
class DecisionRecord:
    """One backend-neutral decision at one level/state.

    The contract is intentionally about generic product concepts: identity,
    objective/timing, build inputs, actors/resources/actions/policy and
    capability/fidelity/provenance.  A backend may leave collections empty when
    it cannot yet express them canonically; that absence is explicit rather than
    being replaced by a class-specific top-level schema.
    """

    record_id: str
    backend: Mapping[str, Any]
    identity: Mapping[str, Any]
    objective: Mapping[str, Any]
    timing: Mapping[str, Any]
    gear: Mapping[str, Any] = field(default_factory=dict)
    stat_weights: Mapping[str, Any] = field(default_factory=dict)
    talents: Mapping[str, Any] = field(default_factory=dict)
    actors: tuple[Mapping[str, Any], ...] = ()
    resources: tuple[Mapping[str, Any], ...] = ()
    actions: tuple[Mapping[str, Any], ...] = ()
    policy: Mapping[str, Any] = field(default_factory=dict)
    modes: tuple[Mapping[str, Any], ...] = ()
    capability: Mapping[str, Any] = field(default_factory=dict)
    fidelity: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    unsupported_mechanics: tuple[str, ...] = ()
    compatibility: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = DECISION_CONTRACT_VERSION

    @classmethod
    def from_legacy_route_row(
        cls,
        *,
        class_name: str,
        target_level: int,
        route_name: str,
        row: Mapping[str, Any],
        ruleset: str = "forever",
    ) -> "DecisionRecord":
        """Adapt one current production route row into the common contract."""
        raw = dict(row)
        level = int(raw.get("level", 0) or 0)
        evaluation = Evaluation.from_published_row(raw)
        definition = get_definition(ruleset, class_name)
        record_id = str(raw.get("decision_row_id") or f"{ruleset}:{class_name}:{target_level}:{route_name}:{level}")

        fidelity_raw = raw.get("model_fidelity") or definition.fidelity() or {}
        fidelity = _dict(fidelity_raw)
        if not fidelity and fidelity_raw:
            fidelity = {"label": str(fidelity_raw)}

        policy_value = raw.get("policy") or raw.get("rotation")
        policy = {
            "label": policy_value,
            "steps": _list(raw.get("rotation_steps")),
        }

        talents = {
            "allocation": raw.get("allocation"),
            "family": raw.get("talent_family"),
            "ranks": _dict(raw.get("talent_ranks")),
            "trees": _dict(raw.get("talent_trees")),
            "tree_points": _dict(raw.get("tree_points")),
            "added": raw.get("talent_added"),
        }

        gear_stats = _dict(raw.get("gear_stats"))
        gear = {
            "label": raw.get("gear"),
            "snapshot": gear_stats,
        }

        timing = {
            "contract": evaluation.timing_contract,
            "seconds_per_mob": evaluation.seconds_per_mob if evaluation.score_s_per_100 > 0 else None,
            "kill_seconds_per_mob": (
                evaluation.kill_s_per_100 / 100.0 if evaluation.kill_s_per_100 is not None else None
            ),
            "recovery_seconds_per_mob": (
                evaluation.recovery_s_per_100 / 100.0 if evaluation.recovery_s_per_100 is not None else None
            ),
            "travel_seconds_per_mob": (
                evaluation.travel_s_per_100 / 100.0 if evaluation.travel_s_per_100 is not None else None
            ),
            "complete": evaluation.timing_complete,
            "consistent": evaluation.timing_consistent,
            "residual_seconds_per_mob": (
                evaluation.timing_residual_s_per_100 / 100.0
                if evaluation.timing_residual_s_per_100 is not None
                else None
            ),
        }
        objective = {
            "score_s_per_100": float(evaluation.score_s_per_100),
            "mobs_per_hour": (
                evaluation.mobs_per_hour
                if evaluation.mobs_per_hour is not None
                else (360000.0 / evaluation.score_s_per_100 if evaluation.score_s_per_100 > 0 else None)
            ),
        }
        identity = {
            "ruleset": str(ruleset),
            "class_name": str(class_name),
            "race": raw.get("race"),
            "level": level,
            "target_level": int(target_level),
            "route": str(route_name),
            "decision_mode": raw.get("decision_mode") or route_name,
            "profile": raw.get("combat_profile") or raw.get("profile"),
        }
        backend = {
            "id": "legacy",
            "version": SOFTWARE_VERSION,
            "implementation": "legacy_class_backend",
        }
        provenance = {
            "source": raw.get("source"),
            "data_sources": _list(raw.get("data_sources")),
            "legacy_row_id": raw.get("decision_row_id"),
        }
        unsupported = tuple(str(x) for x in _list(raw.get("unsupported_mechanics")) if x)
        # Legacy projection is an oracle adapter, not a dependency of native generic records.
        from .legacy_decision_projection import project_legacy_gameplay
        gameplay = project_legacy_gameplay(class_name=class_name, row=raw)

        return cls(
            record_id=record_id,
            backend=backend,
            identity=identity,
            objective=objective,
            timing=timing,
            gear=gear,
            stat_weights=_dict(raw.get("stat_weights")),
            talents=talents,
            actors=gameplay.actors,
            resources=gameplay.resources,
            actions=gameplay.actions,
            policy=dict(gameplay.policy or policy),
            modes=gameplay.modes,
            capability=definition.capabilities.as_dict(),
            fidelity=fidelity,
            provenance=provenance,
            unsupported_mechanics=unsupported,
            # Compatibility is deliberately nested and marked legacy.  The
            # backend-neutral top level remains stable while G02+ migrate rich
            # UI detail to actors/resources/actions/modes.
            compatibility={"legacy_route_row": raw},
        )

    def publication_availability(self) -> dict[str, str]:
        """G48: honest per-field availability, not inferred from schema presence.

        A source-only generic adapter can publish an empty record.  This
        manifest tells consumers which *decisions* were actually produced.
        Native route corridors are published separately from individual
        level records and must not be inferred from their identity labels.
        """
        generic = str(self.backend.get("kind", self.backend.get("name", ""))).lower().startswith("generic") or str(self.provenance.get("source", "")) == "generic_backend_native"
        if not generic:
            return {}
        cap = self.capability
        gear = self.gear
        weights = self.stat_weights
        talents = self.talents
        policy = self.policy
        return {
            "selected_build": "available" if bool(talents.get("search_performed")) else "not_computed",
            "gear": "available" if bool(cap.get("gear_optimization")) and gear.get("status") == "selected_named_catalogue_gear" else "not_computed",
            "stat_weights": "available" if bool(cap.get("stat_weight_evaluation")) and bool(weights) else "not_computed",
            "policy": "available" if bool(cap.get("policy_execution")) and bool(policy.get("priority") or policy.get("steps") or policy.get("rules")) else "not_computed",
            "timing": "available" if bool(cap.get("combat_evaluation")) and self.timing.get("seconds_per_mob") is not None else "not_computed",
            "route": "available" if self.identity.get("route_scored") is True else "not_in_level_record",
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "publication_availability": self.publication_availability(),
            "schema_version": int(self.schema_version),
            "record_id": self.record_id,
            "backend": dict(self.backend),
            "identity": dict(self.identity),
            "objective": dict(self.objective),
            "timing": dict(self.timing),
            "gear": dict(self.gear),
            "stat_weights": dict(self.stat_weights),
            "talents": dict(self.talents),
            "actors": [dict(x) for x in self.actors],
            "resources": [dict(x) for x in self.resources],
            "actions": [dict(x) for x in self.actions],
            "policy": dict(self.policy),
            "modes": [dict(x) for x in self.modes],
            "capability": dict(self.capability),
            "fidelity": dict(self.fidelity),
            "provenance": dict(self.provenance),
            "unsupported_mechanics": list(self.unsupported_mechanics),
            "compatibility": dict(self.compatibility),
        }

    def legacy_route_row(self) -> dict[str, Any]:
        """Compatibility view derived from this record for the current listener.

        This makes DecisionRecord part of the active publication authority now;
        the old listener shape is no longer produced without crossing the new
        backend-neutral boundary first.
        """
        row = dict(_dict(self.compatibility).get("legacy_route_row") or {})
        row["decision_contract"] = {
            "schema_version": int(self.schema_version),
            "record_id": self.record_id,
            "backend": dict(self.backend),
        }
        row["decision_content"] = {
            "actors": [dict(x) for x in self.actors],
            "resources": [dict(x) for x in self.resources],
            "actions": [dict(x) for x in self.actions],
            "policy": dict(self.policy),
            "modes": [dict(x) for x in self.modes],
        }
        # Canonical generic values win over any stale legacy duplicates.
        row.update({
            "score_s_per_100": self.objective.get("score_s_per_100"),
            "mobs_per_hour": self.objective.get("mobs_per_hour"),
            "seconds_per_mob": self.timing.get("seconds_per_mob"),
            "kill_seconds_per_mob": self.timing.get("kill_seconds_per_mob"),
            "recovery_seconds_per_mob": self.timing.get("recovery_seconds_per_mob"),
            "travel_seconds_per_mob": self.timing.get("travel_seconds_per_mob"),
            "timing_contract": self.timing.get("contract"),
            "timing_complete": self.timing.get("complete"),
            "timing_consistent": self.timing.get("consistent"),
            "timing_residual_seconds_per_mob": self.timing.get("residual_seconds_per_mob"),
        })
        return row


def records_from_route_rows(route_rows: Mapping[str, Any]) -> list[DecisionRecord]:
    """Flatten canonical route rows into backend-neutral decision records."""
    out: list[DecisionRecord] = []
    for class_name, targets in dict(route_rows or {}).items():
        for target, target_payload in dict(targets or {}).items():
            for route_name, route_payload in dict((target_payload or {}).get("routes") or {}).items():
                if (route_payload or {}).get("status") != "available":
                    continue
                for row in list((route_payload or {}).get("rows") or ()):
                    out.append(DecisionRecord.from_legacy_route_row(
                        class_name=str(class_name),
                        target_level=int(target),
                        route_name=str(route_name),
                        row=row,
                    ))
    return out


def records_from_native_generic_route_rows(route_rows: Mapping[str, Any]) -> list[DecisionRecord]:
    """G48c: first-class, *route-scored* per-level decisions from native rows.

    These records are separate from selected-level source IR DecisionRecords.
    Only validated native route rows enter this adapter. No legacy conversion,
    cross-class score claim, gear invention or missing timing decomposition.
    """
    result: list[DecisionRecord] = []
    seen: set[str] = set()
    for cls, targets in dict(route_rows or {}).items():
        for target_key, target_data in dict(targets or {}).items():
            target = int(target_key)
            for route, publication in dict((target_data or {}).get("routes") or {}).items():
                if publication.get("status") != "available":
                    continue
                if publication.get("legacy_fallback") is not False:
                    raise ValueError(f"{cls} {route}: native route has unverified legacy fallback")
                for source in publication.get("rows") or ():
                    row = dict(source)
                    level = int(row["level"])
                    score = float(row["score_s_per_100"])
                    speed = float(row["mobs_per_hour"])
                    seconds = float(row["seconds_per_mob"])
                    if not (0 < score and isfinite(score) and isfinite(speed) and
                            isfinite(seconds) and abs(seconds - score / 100) < 1e-6 and
                            abs(speed - 360000 / score) < 1e-5):
                        raise ValueError(f"{cls} {route} L{level}: inconsistent native route score")
                    if row.get("legacy_fallback") is not False or not row.get("talent_points_contract_ok"):
                        raise ValueError(f"{cls} {route} L{level}: missing native authority or talent proof")
                    weights = _dict(row.get("stat_weights"))
                    if not _dict(weights.get("stats")) or not row.get("stat_weights_contract_ok"):
                        raise ValueError(f"{cls} {route} L{level}: no validated native weights")
                    gear_stats = _dict(row.get("gear_stats"))
                    method = str(gear_stats.get("selection_method") or "")
                    named = method == "explicit_bounded_optimizer_fixed_point"
                    proxy = method == "explicit_scenario_proxy_not_named_gear"
                    if not (named or proxy) or (named and not _dict(gear_stats.get("slots"))) or (proxy and gear_stats.get("slots")):
                        raise ValueError(f"{cls} {route} L{level}: ambiguous named/proxy gear provenance")
                    record_id = f"forever:{cls}:native-route:{target}:{route}:{level}"
                    if record_id in seen:
                        raise ValueError(f"duplicate native route decision: {record_id}")
                    seen.add(record_id)
                    source_timing = _dict(row.get("timing"))
                    timing = {
                        "contract": source_timing.get("timing_contract"),
                        "seconds_per_mob": seconds,
                        "kill_seconds_per_mob": source_timing.get("kill_seconds_per_mob"),
                        "recovery_seconds_per_mob": source_timing.get("recovery_seconds_per_mob"),
                        "travel_seconds_per_mob": source_timing.get("travel_seconds_per_mob"),
                        "complete": bool(source_timing.get("timing_complete", False)),
                        "consistent": source_timing.get("timing_consistent"),
                        "evaluation_scope": source_timing.get("evaluation_scope") or "native_route_scenario_score",
                    }
                    policy_ir = _dict(row.get("policy_ir"))
                    warnings = tuple(str(x) for x in row.get("quality_warnings") or ())
                    record = DecisionRecord(
                        record_id=record_id,
                        backend={"id": "generic", "kind": "generic", "version": SOFTWARE_VERSION,
                                 "implementation": "native_level_frontier_route_dp"},
                        identity={"ruleset": "forever", "class_name": cls, "level": level,
                                  "target_level": target, "route": route,
                                  "decision_mode": "native_route_scored",
                                  "profile": row.get("combat_profile"), "route_scored": True},
                        objective={"score_s_per_100": score, "mobs_per_hour": speed,
                                   "status": "native_route_scored", "cross_class_comparable": False},
                        timing=timing,
                        gear={"status": "selected_named_catalogue_gear" if named else "scenario_proxy_no_named_items",
                              "label": "named catalogue items" if named else "proxy weapon/base stats; no named items",
                              "snapshot": gear_stats, "selection_method": method,
                              "slots": _dict(gear_stats.get("slots"))},
                        stat_weights={**weights, "scope": "native_named_gear_state" if named else "proxy_scenario_only"},
                        talents={"allocation": row.get("allocation"), "family": row.get("talent_family"),
                                 "ranks": _dict(row.get("talent_ranks")),
                                 "tree_points": _dict(row.get("tree_points")),
                                 "added": row.get("talent_added"), "search_performed": True},
                        policy={**policy_ir, "label": policy_ir.get("label") or row.get("policy") or row.get("rotation"),
                                "steps": _list(row.get("rotation_steps"))},
                        capability={"route_scoring": True, "gear_optimization": named,
                                    "stat_weight_evaluation": True, "policy_execution": bool(policy_ir.get("rules")),
                                    "combat_evaluation": True, "full_leveling": False,
                                    "cross_class_comparable": False, "named_gear": named,
                                    "scenario_proxy": proxy},
                        fidelity={"rating": "bounded_native_route", "scope": "bounded_native_generic_route",
                                  "model": row.get("model_fidelity") or ("native_melee_proxy" if proxy else "native_caster_named_gear"),
                                  "quality_warnings": list(warnings), "cross_class_comparable": False,
                                  "full_leveling": False},
                        provenance={"source": "generic_backend_native", "route_authority": row.get("source"),
                                    "native_route_row": True, "gear_selection_method": method,
                                    "legacy_fallback": False, "selected_level_source_record": False},
                        unsupported_mechanics=warnings,
                    )
                    result.append(record)
    return result
