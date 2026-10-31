from __future__ import annotations

"""Generic per-level search coordinator.

The kernel owns the repeated *shape* of class optimization: expand builds from
previous states, deduplicate opaque build objects, evaluate candidates, and add
the current-level objective cost.  ClassModel owns all game semantics.

This module deliberately does not know talent field names, spell names, specs,
rotations, pets, forms, seals, or Mage schools.  Those live behind ClassModel.
"""

from dataclasses import dataclass, field
from concurrent.futures import Executor, as_completed
import os
from typing import Any, Callable, Mapping, Sequence

from .class_model import CandidateResult, ClassModel, Evaluation, SearchContext, active_class_model


@dataclass(frozen=True)
class SearchParent:
    build: Any
    cumulative_s: float = 0.0
    payload: Any = None


@dataclass(frozen=True)
class SearchLevelCandidate:
    parent: SearchParent
    result: CandidateResult
    transition_label: str
    cumulative_s: float

    @property
    def build(self) -> Any:
        return self.result.build

    @property
    def evaluation(self) -> Evaluation:
        return self.result.evaluation


@dataclass(frozen=True)
class SearchLevelResult:
    level: int
    candidates: tuple[SearchLevelCandidate, ...]
    generated_count: int
    metadata: Mapping[str, Any] = field(default_factory=dict)


ProgressCallback = Callable[[int, int], None]


def _best_policy_evaluation(model: ClassModel, ctx: SearchContext) -> tuple[SearchContext, Evaluation]:
    rotations = tuple(model.get_rotation_candidates(ctx) or ())
    if not rotations:
        rotations = (ctx.policy,)

    best: tuple[float, SearchContext, Evaluation] | None = None
    for rotation in rotations:
        candidate_ctx = ctx.with_updates(policy=rotation)
        optimized_policy = model.optimize_policy(candidate_ctx)
        candidate_ctx = candidate_ctx.with_updates(policy=optimized_policy)
        evaluation = model.evaluate(candidate_ctx)
        row = (float(evaluation.score_s_per_100), candidate_ctx, evaluation)
        if best is None or row[0] < best[0]:
            best = row
    if best is None:
        raise RuntimeError(f"{model.name}: candidate produced no evaluation")
    return best[1], best[2]


def evaluate_candidate(
    model: ClassModel,
    ctx: SearchContext,
    *,
    derive_stat_weights: bool = False,
    fixed_point_max_iters: int = 4,
) -> CandidateResult:
    """Evaluate one opaque class candidate through the shared hook sequence.

    New plugins use the generic fixed point:

        policy/rotation -> evaluate -> stat weights -> gear -> repeat

    Legacy EngineClassModel adapters temporarily report that candidate
    optimization is bundled inside their evaluator, so they take the same outer
    path without double-running class-local fixed points.
    """
    loadout = ctx.loadout
    if loadout is None:
        initialized = model.initialize_item_options(ctx)
        if initialized is not None:
            loadout = initialized
    current = ctx.with_updates(loadout=loadout)

    if model.candidate_optimization_is_bundled():
        best_ctx, evaluation = _best_policy_evaluation(model, current)
        weights = dict(model.stat_weights(best_ctx, evaluation) or {}) if derive_stat_weights else {}
        return CandidateResult(
            level=int(best_ctx.level), build=best_ctx.build, loadout=best_ctx.loadout,
            policy=best_ctx.policy, evaluation=evaluation, stat_weights=weights,
            metadata={**dict(best_ctx.metadata), "fixed_point_owner": "class_compatibility_adapter"},
        )

    max_iters = max(1, int(fixed_point_max_iters))
    final_ctx = current
    final_eval: Evaluation | None = None
    final_weights: dict[str, float] = {}
    iterations = 0
    converged = False

    for iterations in range(1, max_iters + 1):
        best_ctx, evaluation = _best_policy_evaluation(model, current)
        weights = dict(model.stat_weights(best_ctx, evaluation) or {})
        next_loadout = model.optimize_gear(best_ctx, weights)
        final_ctx, final_eval, final_weights = best_ctx, evaluation, weights
        if model.loadout_key(next_loadout) == model.loadout_key(best_ctx.loadout):
            converged = True
            break
        current = best_ctx.with_updates(loadout=next_loadout)
    else:
        # The final gear proposal has not been scored yet.  Evaluate it once so
        # CandidateResult always describes the published loadout.
        final_ctx, final_eval = _best_policy_evaluation(model, current)
        final_weights = dict(model.stat_weights(final_ctx, final_eval) or {})

    if final_eval is None:
        raise RuntimeError(f"{model.name}: fixed point produced no evaluation")

    metadata = dict(final_ctx.metadata)
    metadata.update({
        "fixed_point_owner": "generic_search_kernel",
        "fixed_point_iterations": int(iterations),
        "fixed_point_converged": bool(converged),
    })
    return CandidateResult(
        level=int(final_ctx.level), build=final_ctx.build, loadout=final_ctx.loadout,
        policy=final_ctx.policy, evaluation=final_eval,
        stat_weights=(final_weights if derive_stat_weights else {}), metadata=metadata,
    )


def _evaluate_worker(args: tuple[int, Any, dict[str, Any], bool]):
    """Spawn-safe evaluator using the active class plugin selected by env."""
    level, build, metadata, derive_stat_weights = args
    os.environ["WOW_SIM_SUPPRESS_RUNTIME_PROGRESS"] = "1"
    model = active_class_model()
    ctx = SearchContext(level=int(level), build=build, metadata=dict(metadata))
    result = evaluate_candidate(model, ctx, derive_stat_weights=bool(derive_stat_weights))
    return model.build_key(build), result


def search_level(
    model: ClassModel,
    level: int,
    parents: Sequence[SearchParent],
    *,
    level_weight: float = 1.0,
    metadata: Mapping[str, Any] | None = None,
    executor: Executor | None = None,
    derive_stat_weights: bool = False,
    progress: ProgressCallback | None = None,
    candidate_builds: Sequence[Any] | None = None,
) -> SearchLevelResult:
    """Expand/evaluate one level with deterministic first-parent-wins semantics.

    This is intentionally a *per-level* search primitive.  It returns data for a
    frontier; it does not solve the cross-level optimum.  ``solve_routes`` / the
    generic DP consumes retained level frontiers afterwards.
    """
    level = int(level)
    meta = dict(metadata or {})
    meta.setdefault("target_points", max(0, level - 9))

    # Preserve insertion order and first-parent-wins behavior.  The build is
    # opaque: the kernel only asks ClassModel for keys and legal transitions.
    prepared: dict[Any, tuple[SearchParent, str, Any]] = {}
    if candidate_builds is not None:
        # Whole-level candidate mode is used by mature class plugins whose own
        # structural generator already produced a bounded legal build set.  The
        # generic kernel still owns deterministic dedup/evaluation/result shape.
        for child in candidate_builds:
            key = model.build_key(child)
            prepared.setdefault(key, (SearchParent(child, 0.0, None), "candidate", child))
    else:
        for parent in parents:
            parent_ctx = SearchContext(
                level=level,
                build=parent.build,
                previous=parent.payload,
                metadata=meta,
            )
            for child in model.get_talent_candidates(parent_ctx):
                label = model.legal_one_point_transition(parent.build, child)
                if label is None:
                    continue
                key = model.build_key(child)
                prepared.setdefault(key, (parent, str(label), child))

    total = len(prepared)
    if progress is not None:
        progress(0, total)

    evaluated: dict[Any, CandidateResult] = {}
    if executor is None or total <= 1:
        for current, (key, (_parent, _label, child)) in enumerate(prepared.items(), 1):
            ctx = SearchContext(level=level, build=child, metadata=meta)
            evaluated[key] = evaluate_candidate(model, ctx, derive_stat_weights=derive_stat_weights)
            if progress is not None:
                progress(current, total)
    else:
        future_to_key = {
            executor.submit(_evaluate_worker, (level, child, meta, bool(derive_stat_weights))): key
            for key, (_parent, _label, child) in prepared.items()
        }
        for current, future in enumerate(as_completed(future_to_key), 1):
            expected_key = future_to_key[future]
            returned_key, result = future.result()
            if returned_key != expected_key:
                raise RuntimeError(f"candidate worker key mismatch at level {level}")
            evaluated[expected_key] = result
            if progress is not None:
                progress(current, total)

    weight = max(0.0, float(level_weight))
    out: list[SearchLevelCandidate] = []
    # Completion order never changes deterministic result order.
    for key, (parent, label, _child) in prepared.items():
        result = evaluated[key]
        cumulative = float(parent.cumulative_s) + weight * float(result.evaluation.score_s_per_100)
        out.append(SearchLevelCandidate(parent, result, label, cumulative))

    return SearchLevelResult(
        level=level,
        candidates=tuple(out),
        generated_count=total,
        metadata=meta,
    )
