from __future__ import annotations

"""Canonical Generic-backend CandidateResult / LevelFrontier production.

G22 is deliberately a bridge into the existing route architecture, not a route
solver.  Every candidate in these frontiers comes from the native generic
gear/talent/policy/runtime scorer.  No legacy route row or legacy scorer is read.

The current caster slice retains every *valid executable Talent IR allocation*
scored at the selected fixed-point gear state.  Candidate-specific gear fixed
points and full-tree continuity remain future work; therefore route solving stays
explicitly disabled even though the canonical frontier objects now exist.
"""

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.game.evaluation import Evaluation
from src.game.data.forever.registry import generic_planning_levels
from src.version import SOFTWARE_VERSION
from .class_model import CandidateResult, ClassModel, LevelFrontier, SearchContext


FRONTIER_SCHEMA_VERSION = 1
FRONTIER_AUTHORITY = "generic_candidate_result_level_frontier"
ROUTE_AUTHORITY = "generic_canonical_level_frontier_dp"
GENERIC_DRUID_ROUTE_LEVELS = generic_planning_levels("druid")
ROUTE_PUBLICATION_CACHE_SCHEMA = 2
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTE_PUBLICATION_CACHE_PATH = PROJECT_ROOT / "data" / "forever" / "generic_druid_route_publication_v1.json"
CANONICAL_ITEM_DB_PATH = PROJECT_ROOT / "data" / "forever" / "catalogue" / "items_2026-09-29.sqlite"


@dataclass(frozen=True)
class GenericTalentBuild:
    """Opaque build identity retained by the generic route architecture.

    It intentionally does not pretend that unimplemented talent families have
    ranks.  ``spent_points`` can therefore be lower than the total level budget;
    solve_routes() remains gated until complete executable build continuity lands.
    """

    candidate_id: str
    ranks: tuple[tuple[str, int], ...]
    spent_points: int
    available_points: int
    executable_talent_ids: tuple[str, ...]
    tree_points: tuple[tuple[str, int], ...] = ()

    @classmethod
    def from_candidate(
        cls, row: Mapping[str, Any], *, available_points: int,
        executable_talent_ids: Iterable[str], talent_tree_by_id: Mapping[str, str] | None = None,
    ) -> "GenericTalentBuild":
        selection = dict(row.get("selection") or {})
        tree_map = {str(k): str(v) for k, v in dict(talent_tree_by_id or {}).items()}
        by_tree: dict[str, int] = {}
        for talent_id, rank0 in selection.items():
            rank = int(rank0)
            if rank <= 0:
                continue
            tree = tree_map.get(str(talent_id))
            if tree:
                by_tree[tree] = by_tree.get(tree, 0) + rank
        return cls(
            candidate_id=str(row.get("candidate_id") or "talents:none"),
            ranks=tuple(sorted((str(k), int(v)) for k, v in selection.items() if int(v) > 0)),
            spent_points=int(row.get("spent_points", sum(int(v) for v in selection.values())) or 0),
            available_points=int(available_points),
            executable_talent_ids=tuple(str(x) for x in executable_talent_ids),
            tree_points=tuple(sorted((str(k), int(v)) for k, v in by_tree.items())),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "ranks": {k: int(v) for k, v in self.ranks},
            "spent_points": int(self.spent_points),
            "available_points": int(self.available_points),
            "executable_talent_ids": list(self.executable_talent_ids),
            "tree_points": {k: int(v) for k, v in self.tree_points},
            "full_level_budget_represented": bool(self.spent_points == self.available_points),
        }


class GenericTalentRouteModel(ClassModel):
    """Route-only build semantics for executable generic Talent IR allocations.

    Combat scoring remains owned by the native generic backend/frontier.  This
    adapter only teaches the shared route DP how to compare opaque generic
    talent builds and how one legal represented point advances between levels.
    """

    name = "generic-talent-route"

    def evaluate(self, ctx: SearchContext):  # pragma: no cover - route DP never rescoring
        raise RuntimeError("GenericTalentRouteModel is route-only; scoring comes from CandidateResult")

    def build_key(self, build: Any) -> Any:
        if not isinstance(build, GenericTalentBuild):
            return repr(build)
        return tuple(build.ranks)

    def build_points(self, build: Any) -> int:
        if not isinstance(build, GenericTalentBuild):
            return -1
        return int(build.spent_points)

    def legal_one_point_transition(self, parent: Any, child: Any) -> str | None:
        if not isinstance(parent, GenericTalentBuild) or not isinstance(child, GenericTalentBuild):
            return None
        if int(child.spent_points) != int(parent.spent_points) + 1:
            return None
        a = dict(parent.ranks); b = dict(child.ranks)
        keys = sorted(set(a) | set(b))
        changed = []
        for key in keys:
            av = int(a.get(key, 0)); bv = int(b.get(key, 0))
            if av == bv:
                continue
            if bv == av + 1:
                changed.append(key)
            else:
                return None
        return changed[0] if len(changed) == 1 else None

    def route_matches(self, build: Any, definition: Mapping[str, Any]) -> bool:
        if not isinstance(build, GenericTalentBuild):
            return False
        kind = str(definition.get("kind") or "")
        minimum = int(definition.get("minimum", 1) or 1)
        if kind == "tree_points":
            return int(dict(build.tree_points).get(str(definition.get("tree") or ""), 0)) >= minimum
        if kind == "talent":
            return int(dict(build.ranks).get(str(definition.get("talent") or ""), 0)) >= minimum
        return False

    def policy_description(self, policy: Any, level: int) -> str:
        if isinstance(policy, Mapping):
            return str(policy.get("candidate_id") or policy.get("policy_id") or "")
        return super().policy_description(policy, level)


def bounded_frontier_levels(selected_level: int, *, width: int = 3) -> tuple[int, ...]:
    """Return a small contiguous real-level window including ``selected_level``."""
    level = max(10, min(60, int(selected_level)))
    count = max(1, min(5, int(width)))
    lo = level - count // 2
    hi = lo + count - 1
    if lo < 10:
        hi += 10 - lo
        lo = 10
    if hi > 60:
        lo -= hi - 60
        hi = 60
    lo = max(10, lo)
    return tuple(range(lo, hi + 1))


def _candidate_identity(*, level: int, fixed_point_identity: str | None, build: GenericTalentBuild, policy_candidate_id: str | None, seconds_per_mob: float) -> str:
    payload = {
        "level": int(level),
        "fixed_point_gear_state": fixed_point_identity,
        "talent_candidate_id": build.candidate_id,
        "policy_candidate_id": policy_candidate_id,
        "seconds_per_mob": float(seconds_per_mob),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _evaluation_for_candidate(record, row: Mapping[str, Any], *, selected: bool) -> Evaluation:
    seconds = float(row["seconds_per_mob"])
    if selected:
        return Evaluation(
            score_s_per_100=100.0 * seconds,
            kill_s_per_100=(None if record.timing.get("kill_seconds_per_mob") is None else 100.0 * float(record.timing["kill_seconds_per_mob"])),
            recovery_s_per_100=(None if record.timing.get("recovery_seconds_per_mob") is None else 100.0 * float(record.timing["recovery_seconds_per_mob"])),
            travel_s_per_100=(None if record.timing.get("travel_seconds_per_mob") is None else 100.0 * float(record.timing["travel_seconds_per_mob"])),
            mobs_per_hour=(3600.0 / seconds if seconds > 0 else None),
            evaluation_scope="generic_frontier_selected_fixed_point_state",
            optimization_ready=bool(record.objective.get("optimization_ready", False)),
            provenance={
                "producer": FRONTIER_AUTHORITY,
                "source_record_id": record.record_id,
                "selected_fixed_point_candidate": True,
            },
            fidelity={"source": "native_generic_runtime_evaluation"},
        )
    return Evaluation(
        score_s_per_100=100.0 * seconds,
        mobs_per_hour=(3600.0 / seconds if seconds > 0 else None),
        evaluation_scope="generic_frontier_candidate_total_only",
        optimization_ready=False,
        provenance={
            "producer": FRONTIER_AUTHORITY,
            "source_record_id": record.record_id,
            "selected_fixed_point_candidate": False,
        },
        fidelity={
            "source": "native_generic_joint_talent_policy_scorer",
            "limitation": "candidate total score retained; timing decomposition/stat sensitivities are authoritative only for selected fixed-point state",
        },
    )


def frontier_from_generic_record(record) -> LevelFrontier:
    """Create one canonical LevelFrontier from a native Generic DecisionRecord."""
    if str(record.backend.get("id")) != "generic":
        raise ValueError("generic frontier requires a native generic DecisionRecord")
    level = int(record.identity.get("level", 0) or 0)
    search = dict(record.provenance.get("talent_search") or record.talents.get("search") or {})
    candidates_raw = list(search.get("candidates") or ())
    if not candidates_raw:
        raise ValueError(f"generic L{level} has no retained talent/policy candidate scores")
    available_points = int(record.talents.get("available_points", max(0, level - 9)) or 0)
    executable_ids = tuple(str(x) for x in search.get("executable_talent_ids") or ())
    game_ir = dict(record.provenance.get("game_ir") or {})
    talent_tree_by_id = {
        str(t.get("id")): str(t.get("tree_key"))
        for t in list(game_ir.get("talents") or ()) if t.get("id") and t.get("tree_key")
    }
    selected_id = str(search.get("selected_candidate_id") or "")
    fixed_point = dict(record.gear.get("fixed_point") or {})
    fixed_point_identity = fixed_point.get("selected_state_identity") or fixed_point.get("scorer_state_identity")
    gear_loadout = {
        "selection_method": record.gear.get("selection_method"),
        "fixed_point_scorer_state_identity": fixed_point_identity,
        "slots": dict(record.gear.get("slots") or {}),
        "aggregate_stats": dict(record.gear.get("aggregate_stats") or {}),
    }
    rows: list[CandidateResult] = []
    for raw in candidates_raw:
        row = dict(raw or {})
        if not bool(row.get("valid")) or row.get("seconds_per_mob") is None:
            continue
        build = GenericTalentBuild.from_candidate(
            row, available_points=available_points, executable_talent_ids=executable_ids,
            talent_tree_by_id=talent_tree_by_id,
        )
        detail = dict(row.get("detail") or {})
        policy_candidate_id = detail.get("policy_candidate_id") or detail.get("policy_id")
        selected = build.candidate_id == selected_id
        seconds = float(row["seconds_per_mob"])
        identity = _candidate_identity(
            level=level,
            fixed_point_identity=(None if fixed_point_identity is None else str(fixed_point_identity)),
            build=build,
            policy_candidate_id=(None if policy_candidate_id is None else str(policy_candidate_id)),
            seconds_per_mob=seconds,
        )
        action_names = {str(a.get("id")): str(a.get("name") or a.get("id")) for a in record.actions}
        selected_action_ids = [str(r.get("action_id")) for r in record.policy.get("rules", ()) if r.get("action_id")]
        selected_action_labels = [action_names.get(a, a) for a in selected_action_ids] if selected else []
        rows.append(CandidateResult(
            level=level,
            build=build,
            loadout=gear_loadout,
            policy={
                "candidate_id": policy_candidate_id,
                "policy_id": detail.get("policy_id"),
                "seconds_per_mob": detail.get("policy_seconds_per_mob"),
            },
            evaluation=_evaluation_for_candidate(record, row, selected=selected),
            stat_weights=(
                {str(k): float(v) for k, v in dict(record.stat_weights.get("values") or {}).items()}
                if selected else {}
            ),
            metadata={
                "source": FRONTIER_AUTHORITY,
                "backend": "generic",
                "software_version": SOFTWARE_VERSION,
                "candidate_id": identity,
                "talent_candidate_id": build.candidate_id,
                "selected_fixed_point_candidate": selected,
                "fixed_point_scorer_state_identity": fixed_point_identity,
                "gear_state_authority": "selected_generic_fixed_point_gear_state",
                "candidate_specific_gear_fixed_point": False,
                "fixed_point_converged": bool(record.gear.get("fixed_point_complete")),
                "fixed_point_stop_reason": fixed_point.get("stop_reason"),
                "route_ready": bool(build.spent_points == build.available_points),
                "route_blocker": (None if build.spent_points == build.available_points else "full executable talent-tree point continuity is not represented for this candidate"),
                "publication_row": {
                    "level": int(level),
                    "allocation": build.candidate_id,
                    "talent_ranks": {k: int(v) for k, v in build.ranks},
                    "tree_points": {k: int(v) for k, v in build.tree_points},
                    "talent_family": (max(build.tree_points, key=lambda kv: kv[1])[0] if build.tree_points else None),
                    "score_s_per_100": 100.0 * seconds,
                    "seconds_per_mob": seconds,
                    "mobs_per_hour": (3600.0 / seconds if seconds > 0 else None),
                    "policy": policy_candidate_id,
                    "rotation": " → ".join(selected_action_labels) if selected_action_labels else None,
                    "rotation_steps": [{"label": label} for label in selected_action_labels],
                    "policy_ir": dict(record.policy) if selected else None,
                    "backend": "generic",
                },
                "legacy_fallback": False,
            },
        ))
    if not rows:
        raise ValueError(f"generic L{level} retained no valid scored candidates")
    rows.sort(key=lambda c: (float(c.evaluation.score_s_per_100), str(c.metadata.get("talent_candidate_id"))))
    return LevelFrontier(level=level, candidates=tuple(rows))


def build_generic_level_frontiers(
    *, class_name: str = "Druid", levels: Iterable[int], ruleset: str = "forever",
    records_by_level: Mapping[int, Any] | None = None,
) -> tuple[LevelFrontier, ...]:
    """Build native generic frontiers for a bounded contiguous level slice.

    ``records_by_level`` may provide already-built native generic DecisionRecords
    for levels the caller has just published.  Reusing those records keeps the
    product path from rescoring the exact same class/level twice; missing levels
    are still built through the normal native generic backend authority.
    """
    from .generic_backend import build_partial_generic_records

    ordered = tuple(sorted(set(int(x) for x in levels)))
    if not ordered:
        raise ValueError("at least one frontier level is required")
    if any(b != a + 1 for a, b in zip(ordered, ordered[1:])):
        raise ValueError("generic frontier levels must be contiguous")
    seeded = {int(k): v for k, v in dict(records_by_level or {}).items()}
    out = []
    for level in ordered:
        record = seeded.get(int(level))
        if record is None:
            records = build_partial_generic_records(
                class_names=(str(class_name),), selected_level=int(level), ruleset=str(ruleset),
            )
            if len(records) != 1:
                raise ValueError(f"expected one generic record for {class_name} L{level}, got {len(records)}")
            record = records[0]
        identity = getattr(record, "identity", {}) or {}
        if str(identity.get("class_name", "")).lower() != str(class_name).lower() or int(identity.get("level", -1)) != int(level):
            raise ValueError(f"seeded generic record does not match {class_name} L{level}")
        out.append(frontier_from_generic_record(record))
    return tuple(out)


def route_ready_frontiers(frontiers: Iterable[LevelFrontier]) -> tuple[LevelFrontier, ...]:
    """Keep only candidates whose complete level talent budget is executable.

    G32 intentionally fails closed instead of inventing opaque/dummy talent
    points.  With the current Druid Talent IR this yields a real L10-L14
    continuity corridor where Improved Wrath can represent every earned point
    exactly.
    """
    out: list[LevelFrontier] = []
    for frontier in sorted(frontiers, key=lambda f: int(f.level)):
        kept = []
        for candidate in frontier.candidates:
            build = candidate.build
            if not isinstance(build, GenericTalentBuild):
                continue
            if int(build.spent_points) != int(build.available_points):
                continue
            kept.append(replace(candidate, metadata={
                **dict(candidate.metadata),
                "route_ready": True,
                "route_authority": ROUTE_AUTHORITY,
                "route_blocker": None,
            }))
        if not kept:
            raise ValueError(f"generic L{frontier.level} has no fully represented route-ready candidate")
        out.append(LevelFrontier(level=int(frontier.level), candidates=tuple(kept)))
    return tuple(out)



_GENERIC_DRUID_ROUTE_FRONTIER_CACHE: dict[tuple[str, tuple[int, ...]], tuple[LevelFrontier, ...]] = {}


def clear_generic_druid_route_frontier_cache() -> None:
    _GENERIC_DRUID_ROUTE_FRONTIER_CACHE.clear()


def build_generic_druid_route_frontiers(
    *, levels: Iterable[int] = GENERIC_DRUID_ROUTE_LEVELS, ruleset: str = "forever",
) -> tuple[LevelFrontier, ...]:
    """Build/cache the fully represented frontiers consumed by G32 route DP.

    Route levels are immutable within one software process.  Reusing these
    expensive native frontiers avoids rescoring identical fixed-point states
    when the listener/API and regression/report paths ask the same route
    question repeatedly.
    """
    ordered_levels = tuple(sorted(set(int(x) for x in levels)))
    if not ordered_levels:
        raise ValueError("generic Druid route solve requires at least one level")
    key = (str(ruleset), ordered_levels)
    cached = _GENERIC_DRUID_ROUTE_FRONTIER_CACHE.get(key)
    if cached is not None:
        return cached
    frontiers = route_ready_frontiers(build_generic_level_frontiers(
        class_name="Druid", levels=ordered_levels, ruleset=ruleset,
    ))
    _GENERIC_DRUID_ROUTE_FRONTIER_CACHE[key] = frontiers
    return frontiers

def solve_generic_druid_routes(
    *, levels: Iterable[int] = GENERIC_DRUID_ROUTE_LEVELS, targets: Iterable[int] | None = None,
    ruleset: str = "forever",
):
    """Solve the honest fully-executable generic Druid continuity corridor."""
    from .decision_result import solve_routes

    ordered_levels = tuple(sorted(set(int(x) for x in levels)))
    if not ordered_levels:
        raise ValueError("generic Druid route solve requires at least one level")
    frontiers = build_generic_druid_route_frontiers(levels=ordered_levels, ruleset=ruleset)
    target_levels = tuple(sorted(set(int(x) for x in (targets or (ordered_levels[-1],)))))
    result = solve_routes(
        frontiers, model=GenericTalentRouteModel(), class_name="druid", targets=target_levels,
        unconstrained_max_respecs=0, constrained_max_respecs=0,
    )
    return replace(result, authority=ROUTE_AUTHORITY)



def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_generic_druid_route_publication(*, ruleset: str = "forever") -> dict[str, Any]:
    """Run the live canonical G32 route solve and return publication reports.

    This is intentionally the expensive authority path.  The product API may
    consume a release-generated snapshot of this exact output when its software
    version and canonical item-catalogue SHA still match.
    """
    from .decision_result import reports

    result = solve_generic_druid_routes(levels=GENERIC_DRUID_ROUTE_LEVELS, ruleset=ruleset)
    endpoint, regret = reports(result, verified_level_cap=max(GENERIC_DRUID_ROUTE_LEVELS))
    # G33: take *the selected path's actual CandidateResult states*, not a
    # second scorer, legacy adapter or unselected frontier preview. This is the
    # canonical route row material for normal listener use.
    target = max(GENERIC_DRUID_ROUTE_LEVELS)
    path = result.targets[target]["unconstrained"].path
    if path is None:
        raise ValueError("generic Druid route has no selected path")
    selected_steps = []
    for step in path.steps:
        candidate = dict(step.node.details).get("candidate_result")
        if not isinstance(candidate, CandidateResult):
            raise ValueError(f"generic L{step.node.level}: selected path lost canonical CandidateResult")
        if not candidate.stat_weights or not dict(candidate.loadout.get("slots") or {}):
            raise ValueError(f"generic L{step.node.level}: selected state has no exact weights or named gear")
        row = {
            **dict(candidate.metadata.get("publication_row") or {}),
            "candidate_id": str(candidate.metadata.get("candidate_id")),
            "talent_added": step.talent_added,
            "policy": candidate.metadata.get("publication_row", {}).get("policy"),
            "policy_candidate": dict(candidate.policy),
            "gear_stats": {
                "slots": dict(candidate.loadout.get("slots") or {}),
                "aggregate_stats": dict(candidate.loadout.get("aggregate_stats") or {}),
                "selection_method": candidate.loadout.get("selection_method"),
            },
            "stat_weights": {
                "method": "generic_exact_state_first_effect_forward_difference",
                "scorer_state_identity": candidate.metadata.get("fixed_point_scorer_state_identity"),
                "stats": {
                    name: {"seconds_saved_per_100_per_point": float(value)*100.0, "status": "measured"}
                    for name, value in dict(candidate.stat_weights).items()
                },
            },
            "timing": candidate.evaluation.published_fields(),
            "fixed_point_converged": candidate.metadata.get("fixed_point_converged"),
            "fixed_point_stop_reason": candidate.metadata.get("fixed_point_stop_reason"),
            "legacy_fallback": False,
        }
        selected_steps.append(row)
    return {
        "schema_version": ROUTE_PUBLICATION_CACHE_SCHEMA,
        "software_version": SOFTWARE_VERSION,
        "ruleset": str(ruleset),
        "route_authority": ROUTE_AUTHORITY,
        "levels": list(GENERIC_DRUID_ROUTE_LEVELS),
        "canonical_item_db_sha256": _file_sha256(CANONICAL_ITEM_DB_PATH),
        "endpoint_report": endpoint,
        "regret_report": regret,
        "selected_route_steps": selected_steps,
    }


def write_generic_druid_route_publication_cache(
    path: Path | str = ROUTE_PUBLICATION_CACHE_PATH, *, ruleset: str = "forever",
) -> Path:
    """Generate the validated release snapshot from the live G32 authority."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_generic_druid_route_publication(ruleset=ruleset)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def generic_druid_route_publication(
    *, ruleset: str = "forever", cache_path: Path | str = ROUTE_PUBLICATION_CACHE_PATH,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return endpoint/regret reports from a validated snapshot or live solve.

    Snapshot validity is fail-closed on software version, ruleset, route levels,
    route authority and canonical item-catalogue bytes.  A stale/missing cache
    never becomes authority; it only causes the live canonical solve to run.
    """
    path = Path(cache_path)
    current_db_sha = _file_sha256(CANONICAL_ITEM_DB_PATH)
    reason = "cache_missing"
    if path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            checks = {
                "schema_version": int(cached.get("schema_version", -1)) == ROUTE_PUBLICATION_CACHE_SCHEMA,
                "software_version": str(cached.get("software_version")) == SOFTWARE_VERSION,
                "ruleset": str(cached.get("ruleset")) == str(ruleset),
                "route_authority": str(cached.get("route_authority")) == ROUTE_AUTHORITY,
                "levels": tuple(int(x) for x in cached.get("levels", ())) == GENERIC_DRUID_ROUTE_LEVELS,
                "canonical_item_db_sha256": str(cached.get("canonical_item_db_sha256")) == current_db_sha,
            }
            if all(checks.values()):
                return (
                    dict(cached.get("endpoint_report") or {}),
                    dict(cached.get("regret_report") or {}),
                    {
                        "status": "validated_release_snapshot",
                        "path": str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path),
                        "software_version": SOFTWARE_VERSION,
                        "canonical_item_db_sha256": current_db_sha,
                        "selected_route_steps": list(cached.get("selected_route_steps") or ()),
                    },
                )
            reason = "cache_fingerprint_mismatch:" + ",".join(k for k, ok in checks.items() if not ok)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            reason = f"cache_invalid:{type(exc).__name__}"

    live = build_generic_druid_route_publication(ruleset=ruleset)
    return (
        dict(live["endpoint_report"]),
        dict(live["regret_report"]),
        {
            "status": "live_canonical_solve",
            "reason": reason,
            "software_version": SOFTWARE_VERSION,
            "canonical_item_db_sha256": current_db_sha,
            "selected_route_steps": list(live.get("selected_route_steps") or ()),
        },
    )

def serialize_generic_frontiers(frontiers: Iterable[LevelFrontier], *, class_name: str, ruleset: str = "forever") -> dict[str, Any]:
    ordered = tuple(sorted(frontiers, key=lambda f: int(f.level)))
    payload_rows = []
    total = 0
    for frontier in ordered:
        candidates = []
        for candidate in frontier.candidates:
            build = candidate.build
            build_payload = build.as_dict() if isinstance(build, GenericTalentBuild) else {"repr": repr(build)}
            row = {
                "candidate_id": candidate.metadata.get("candidate_id"),
                "talent_candidate_id": candidate.metadata.get("talent_candidate_id"),
                "selected_fixed_point_candidate": bool(candidate.metadata.get("selected_fixed_point_candidate")),
                "seconds_per_mob": candidate.evaluation.seconds_per_mob,
                "mobs_per_hour": candidate.evaluation.mobs_per_hour,
                "build": build_payload,
                "policy": dict(candidate.policy or {}),
                "gear_item_count": len(dict(candidate.loadout or {}).get("slots") or {}),
                "stat_weights": {str(k): float(v) for k, v in dict(candidate.stat_weights).items()},
                "source": candidate.metadata.get("source"),
                "legacy_fallback": bool(candidate.metadata.get("legacy_fallback", False)),
            }
            candidates.append(row)
        total += len(candidates)
        winner = candidates[0] if candidates else None
        payload_rows.append({
            "level": int(frontier.level),
            "candidate_count": len(candidates),
            "winner": winner,
            "candidates": candidates,
        })
    return {
        "schema_version": FRONTIER_SCHEMA_VERSION,
        "authority": FRONTIER_AUTHORITY,
        "ruleset": str(ruleset),
        "class_name": str(class_name),
        "levels": [int(f.level) for f in ordered],
        "frontier_count": len(ordered),
        "candidate_count": int(total),
        "route_solving": False,
        "route_blocker": "full executable talent-tree point continuity is not yet represented; G22 publishes canonical frontiers but does not solve routes",
        "legacy_fallback": False,
        "frontiers": payload_rows,
    }


def publish_generic_druid_route_rows(
    endpoint_report: Mapping[str, Any], selected_steps: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """G33 normal route rows from the same selected native DP candidates.

    A missing exact-state weight, named item or scorer/path match fails closed.
    No legacy route-row conversion or rehydration is permitted here.
    """
    from math import isfinite

    steps_by_level = {int(x["level"]): dict(x) for x in selected_steps}
    target = max(GENERIC_DRUID_ROUTE_LEVELS)
    target_report = dict(dict(endpoint_report.get("targets") or {}).get(str(target)) or {})
    result: dict[str, Any] = {}
    for route, report in dict(target_report.get("routes") or {}).items():
        if report.get("status") != "available":
            result[route] = {"status": report.get("status", "unavailable"), "reason": report.get("reason"), "rows": []}
            continue
        path = list(dict(report.get("path") or {}).get("steps") or ())
        rows = []
        problems = []
        for step in path:
            level = int(step["level"])
            source = steps_by_level.get(level)
            if source is None or source.get("allocation") != step.get("allocation"):
                problems.append(f"L{level}: selected CandidateResult identity missing/mismatched")
                continue
            expected = float(step["score_s_per_100"])
            score = float(source["score_s_per_100"])
            if not isfinite(score) or abs(score - expected) > 1e-7:
                problems.append(f"L{level}: route scoring and candidate scoring diverged")
                continue
            weights = dict(source.get("stat_weights") or {})
            stats = dict(weights.get("stats") or {})
            slots = dict(dict(source.get("gear_stats") or {}).get("slots") or {})
            if not stats or not slots or any(not isfinite(float(v["seconds_saved_per_100_per_point"])) for v in stats.values()):
                problems.append(f"L{level}: exact native stat weights or named gear unavailable")
                continue
            row = {
                **source,
                "level": level,
                "score_profile": "caster",
                "combat_profile": "caster",
                "talent_points_contract_ok": True,
                "stat_weights_contract_ok": True,
                "route_identity_contract_ok": True,
                "decision_contract": {"backend": {"id": "generic"}, "schema_version": 1},
                "decision_mode": "native_generic_route",
                "source": ROUTE_AUTHORITY,
                "model_fidelity": "bounded_generic_caster_expected_value",
                "missing": {
                    "travel": "travel time not modeled in generic scorer",
                    "attack_table": "hit/crit/resist resolution remains unsupported",
                },
                "quality_warnings": (["bounded_best_fixed_point_not_converged"] if source.get("fixed_point_converged") is False else []),
            }
            rows.append(row)
        result[route] = {
            "status": "available" if not problems and len(rows) == len(path) and rows else "unavailable",
            "reason": "; ".join(problems) if problems else None,
            "rows": rows if not problems and len(rows) == len(path) else [],
            "source": ROUTE_AUTHORITY,
            "legacy_fallback": False,
        }
    return {str(target): {"routes": result}}
