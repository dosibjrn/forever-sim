from __future__ import annotations

"""Generic class-plugin contract for the leveling optimizer.

The optimizer owns orchestration.  A class model owns game semantics: candidate
representation, legality, scoring, gear/policy choices and stat perturbations.
The route solver consumes only generic nodes/transitions produced through this
contract and therefore does not need to know what a Mage, Hunter, Cat or Seal is.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.game.evaluation import Evaluation


@dataclass(frozen=True)
class SearchContext:
    level: int
    scenario: Any = None
    build: Any = None
    loadout: Any = None
    policy: Any = None
    previous: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_updates(self, **changes: Any) -> "SearchContext":
        values = {
            "level": self.level,
            "scenario": self.scenario,
            "build": self.build,
            "loadout": self.loadout,
            "policy": self.policy,
            "previous": self.previous,
            "metadata": self.metadata,
        }
        values.update(changes)
        return SearchContext(**values)


@dataclass(frozen=True)
class CandidateResult:
    level: int
    build: Any
    loadout: Any
    policy: Any
    evaluation: Evaluation
    stat_weights: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LevelFrontier:
    level: int
    candidates: tuple[CandidateResult, ...]


class ClassModel(ABC):
    """Thin plugin facade.  Generic optimization calls this interface only."""

    name: str

    def runner_strategy(self) -> str:
        """Select the shared Forever search orchestration strategy.

        This is deliberately a capability of the class plugin rather than a
        class-name branch in ``runner.py``.  New Forever class models should
        normally use ``continuity_beam``; the migrated mature Mage adapter keeps
        ``analytic_views`` until its historical continuity repair is retired.
        """
        return "continuity_beam"

    def apply_cli_config(self, cfg: Any, args: Any) -> Any:
        """Apply class-owned CLI/runtime configuration without generic class-name dispatch."""
        return cfg

    def rerank_repaired_pools(self, pools: Any, cfg: Any) -> Any:
        """Optional post-repair scoring adjudication owned by class semantics."""
        return pools

    def adjudicate_per_level_candidate(self, level: int, candidates: Sequence[Any], cfg: Any) -> tuple[Any, Mapping[str, Any]]:
        """Choose the independent per-level winner and optional publication overrides."""
        if not candidates:
            raise ValueError(f"{self.name}: no per-level candidates at L{level}")
        node = min(candidates, key=lambda n: (float(n.score_s_per_100), self.build_key(n.talents)))
        return node, {}

    def candidate_optimization_is_bundled(self) -> bool:
        """Compatibility escape hatch while legacy scorers are being unbundled.

        New class plugins should return False (the default) so the generic kernel
        owns policy/stat-weight/gear fixed-point orchestration.  The temporary
        EngineClassModel adapter returns True because current engine score calls
        still contain some of those operations internally.
        """
        return False

    # Search-space hooks.  Concrete classes may freely choose their internal
    # representation; the kernel treats the returned values as opaque objects.
    def initialize_item_options(self, ctx: SearchContext) -> Any:
        return None

    def get_talent_candidates(self, ctx: SearchContext) -> Sequence[Any]:
        return ()

    def get_rotation_candidates(self, ctx: SearchContext) -> Sequence[Any]:
        return ()

    def optimize_gear(self, ctx: SearchContext, stat_weights: Mapping[str, float]) -> Any:
        return ctx.loadout

    def loadout_key(self, loadout: Any) -> Any:
        try:
            hash(loadout)
            return loadout
        except TypeError:
            return repr(loadout)

    def optimize_policy(self, ctx: SearchContext) -> Any:
        return ctx.policy

    @abstractmethod
    def evaluate(self, ctx: SearchContext) -> Evaluation:
        raise NotImplementedError

    def stat_weights(self, ctx: SearchContext, evaluation: Evaluation) -> Mapping[str, float]:
        return {}

    # Route/DP hooks.  These are intentionally the only build semantics needed
    # by the generic shortest-path solver.
    @abstractmethod
    def build_key(self, build: Any) -> Any:
        raise NotImplementedError

    @abstractmethod
    def build_points(self, build: Any) -> int:
        raise NotImplementedError

    @abstractmethod
    def legal_one_point_transition(self, parent: Any, child: Any) -> str | None:
        """Return transition label/name iff child is parent plus one legal point."""
        raise NotImplementedError

    def build_preference_key(self, build: Any) -> Any:
        return self.build_key(build)

    def route_matches(self, build: Any, definition: Mapping[str, Any]) -> bool:
        """Return whether an opaque build satisfies one registry route definition.

        The solver owns route orchestration, while this hook keeps build semantics
        behind ClassModel.  Registry definitions deliberately use a tiny generic
        DSL (talent rank or tree-point threshold).
        """
        kind = str(definition.get("kind") or "")
        minimum = int(definition.get("minimum", 1) or 1)
        if kind == "talent":
            return int(getattr(build, str(definition.get("talent") or ""), 0) or 0) >= minimum
        return False

    def policy_description(self, policy: Any, level: int) -> str:
        return "" if policy is None else str(policy)


class EngineClassModel(ClassModel):
    """Compatibility adapter around the current engine-shaped class modules.

    This keeps existing combat/search code untouched while making route logic
    consume a stable class-plugin interface.  Individual classes can replace
    these methods incrementally without changing the optimizer kernel.
    """

    def __init__(self, engine: Any):
        self.engine = engine
        self.name = str(getattr(engine, "CLASS_NAME", "unknown"))

    def candidate_optimization_is_bundled(self) -> bool:
        return True

    def get_talent_candidates(self, ctx: SearchContext) -> Sequence[Any]:
        """Compatibility expansion for current engine-shaped talent modules."""
        parent = ctx.build
        if parent is None:
            return ()
        target = int(ctx.metadata.get("target_points", max(0, int(ctx.level) - 9)))
        out = []
        for name in getattr(self.engine, "TALENT_RULES", ()):  # opaque to the kernel
            if not self.engine.legal_add(parent, name):
                continue
            child = self.engine.add_point(parent, name)
            if self.build_points(child) != target:
                continue
            out.append(child)
        return tuple(out)

    def build_key(self, build: Any) -> Any:
        fields = getattr(build, "__dataclass_fields__", None)
        if fields:
            return tuple(int(getattr(build, n)) for n in fields)
        return repr(build)

    def build_points(self, build: Any) -> int:
        points = getattr(build, "points", None)
        if callable(points):
            return int(points())
        return sum(int(v) for v in self.build_key(build))

    def legal_one_point_transition(self, parent: Any, child: Any) -> str | None:
        if self.build_points(child) != self.build_points(parent) + 1:
            return None
        fields = getattr(parent, "__dataclass_fields__", None)
        if not fields:
            return None
        found = None
        for name in fields:
            a = int(getattr(parent, name)); b = int(getattr(child, name))
            if b == a:
                continue
            if b == a + 1 and found is None:
                found = name
            else:
                return None
        if found is None:
            return None
        try:
            return found if self.engine.add_point(parent, found) == child else None
        except Exception:
            return None

    def build_preference_key(self, build: Any) -> Any:
        fn = getattr(self.engine, "talent_preference_key", None)
        return fn(build) if callable(fn) else self.build_key(build)

    def route_matches(self, build: Any, definition: Mapping[str, Any]) -> bool:
        kind = str(definition.get("kind") or "")
        minimum = int(definition.get("minimum", 1) or 1)
        if kind == "tree_points":
            fn = getattr(self.engine, "tree_points", None)
            if not callable(fn):
                return False
            return int(fn(build, str(definition.get("tree") or ""))) >= minimum
        return super().route_matches(build, definition)

    def policy_description(self, policy: Any, level: int) -> str:
        fn = getattr(self.engine, "policy_desc", None)
        if callable(fn) and policy is not None:
            return str(fn(policy, level))
        return super().policy_description(policy, level)

    def evaluate(self, ctx: SearchContext) -> Evaluation:
        fn = getattr(self.engine, "experimental_level_score", None)
        if not callable(fn):
            raise NotImplementedError(
                f"{self.name} still uses a legacy/mature evaluator; wrap it in a class-specific ClassModel"
            )
        profile = str(ctx.metadata.get("profile", "all"))
        raw = dict(fn(int(ctx.level), ctx.build, profile))
        return Evaluation.from_raw(raw)


def active_class_model() -> ClassModel:
    from src.engine_registry import get_engine
    engine = get_engine()
    if getattr(engine, "RULESET", None) == "forever":
        from .forever_class_models import create_forever_class_model
        return create_forever_class_model(engine)
    return EngineClassModel(engine)
