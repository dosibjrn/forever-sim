from __future__ import annotations

"""Explicit simulator class/ruleset registry.

M45 centralizes the facts shared infrastructure needs to know about a class.
Class-specific mechanics stay in class modules; shared optimizer/listener code
asks this registry for engine location, capabilities, decision routes, viewer
shape and source identity rather than branching on class names.
"""

from dataclasses import dataclass, field
import importlib
from types import ModuleType
from typing import Any, Mapping


class ClassRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ClassCapabilities:
    """Declared cross-cutting hooks available for one class backend."""

    source_snapshot: bool = False
    state: bool = True
    action_score: bool = False
    policy: bool = False
    stat_weights: bool = False
    fidelity: bool = False
    replay: bool = False
    decision_artifacts: bool = False
    named_gear: bool = False

    def as_dict(self) -> dict[str, bool]:
        return {name: bool(getattr(self, name)) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class ClassDefinition:
    ruleset: str
    class_name: str
    engine_module: str
    display_name: str
    tree_names: tuple[str, ...]
    primary_profiles: tuple[str, ...]
    capabilities: ClassCapabilities
    viewer_view_priority: tuple[str, ...] = ("experimental", "smooth", "hard")
    route_definitions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    source_class_key: str | None = None
    talent_module: str | None = None
    ui_visible: bool = True
    comparison_default: bool = False
    accent: str = "#dddddd"
    proof_only: bool = False

    @property
    def key(self) -> str:
        return f"{self.ruleset}-{self.class_name}"

    def engine(self) -> ModuleType:
        return importlib.import_module(self.engine_module)

    def fidelity(self) -> dict[str, Any]:
        if not self.capabilities.fidelity:
            return {}
        out = dict(getattr(self.engine(), "MODEL_FIDELITY", {}) or {})
        # M46 makes modeled-behavior gaps first-class instead of leaving them
        # scattered through comments/approximation flags.  Keep the Warrior
        # onboarding proof out of the production inventory by design.
        if self.ruleset == "forever":
            try:
                from src.rulesets.forever.fidelity import PRODUCTION_CLASSES, issue_active, issues_for
                if self.class_name in PRODUCTION_CLASSES:
                    rows = issues_for(self.class_name)
                    issue_rows = []
                    for row in rows:
                        item = row.to_dict()
                        item["active_for_target_server"] = issue_active(row)
                        item["blocks_m46_for_target_server"] = bool(row.severity in {"high", "medium"} and issue_active(row))
                        issue_rows.append(item)
                    out["open_issues"] = issue_rows
                    out["open_issue_count"] = len(rows)
                    out["blocking_issue_count"] = sum(x["blocks_m46_for_target_server"] for x in issue_rows)
                    out["high_issue_count"] = sum(row.severity == "high" and issue_active(row) for row in rows)
            except ImportError:
                pass
        return out

    def source_catalogue_key(self) -> str:
        if not self.capabilities.source_snapshot:
            raise ClassRegistryError(f"{self.key} does not declare source_snapshot capability")
        return str(self.source_class_key or self.class_name)

    def validate(self) -> None:
        engine = self.engine()
        errors: list[str] = []
        # Modern class facades self-identify; the untouched legacy Classic Mage
        # module predates those constants, so absence means "registry-owned
        # metadata" while a conflicting declaration is still an error.
        for attr, expected in (("RULESET", self.ruleset), ("CLASS_NAME", self.class_name)):
            actual = getattr(engine, attr, None)
            if actual is not None and actual != expected:
                errors.append(f"{attr}={actual!r}, expected {expected!r}")
        engine_trees = tuple(getattr(engine, "TREE_NAMES", ()) or ())
        if self.tree_names and engine_trees and set(engine_trees) != set(self.tree_names):
            errors.append(f"TREE_NAMES={engine_trees!r}, registry={self.tree_names!r}")
        required = {
            "action_score": ("experimental_level_score",),
            "stat_weights": ("analytic_stat_gradient", "marginal_stat_weights"),
            "fidelity": ("MODEL_FIDELITY",),
            "replay": ("event_validate_candidates",),
            "decision_artifacts": ("Talents", "TALENT_RULES", "tree_points", "legal_add", "add_point", "final_allocation"),
        }
        for capability, hooks in required.items():
            if not bool(getattr(self.capabilities, capability)):
                continue
            if capability == "stat_weights":
                if not any(callable(getattr(engine, hook, None)) for hook in hooks):
                    errors.append("stat_weights requires analytic_stat_gradient or marginal_stat_weights")
                continue
            for hook in hooks:
                if not hasattr(engine, hook):
                    errors.append(f"{capability} requires engine hook {hook}")
        if self.capabilities.policy:
            if not (hasattr(engine, "policy_desc") or hasattr(engine, "experimental_level_score")):
                errors.append("policy requires policy_desc or score rows carrying rotation/policy")
        if errors:
            raise ClassRegistryError(f"invalid class definition {self.key}: " + "; ".join(errors))


_DEF: dict[tuple[str, str], ClassDefinition] = {}


def _tree_routes(*trees: str, minimum: int = 11) -> dict[str, dict[str, Any]]:
    return {
        tree: {"label": f"{tree.title()} endpoint", "kind": "tree_points", "tree": tree, "minimum": int(minimum)}
        for tree in trees
    }


def register(definition: ClassDefinition) -> ClassDefinition:
    key = (str(definition.ruleset).lower(), str(definition.class_name).lower())
    if key in _DEF:
        raise ClassRegistryError(f"duplicate class definition: {key[0]}/{key[1]}")
    _DEF[key] = definition
    return definition


# Legacy Classic Mage remains byte-canonical and registry-owned only by facade.
register(ClassDefinition(
    ruleset="classic", class_name="mage",
    engine_module="src.classic_mage_leveling_optimizer_v10",
    display_name="Mage", tree_names=("arcane", "fire", "frost"),
    primary_profiles=("all", "frost", "fire", "arcane"),
    capabilities=ClassCapabilities(state=True, policy=True, stat_weights=False, fidelity=False),
    viewer_view_priority=("smooth", "hard"), ui_visible=False,
    accent="#71b7ff",
))

register(ClassDefinition(
    ruleset="forever", class_name="mage",
    engine_module="src.rulesets.forever.classes.mage.engine",
    talent_module="src.rulesets.forever.classes.mage.engine",
    display_name="Mage", tree_names=("arcane", "fire", "frost"),
    primary_profiles=("all", "frost", "fire", "arcane"),
    capabilities=ClassCapabilities(
        source_snapshot=True, state=True, action_score=False, policy=True,
        stat_weights=True, fidelity=True, replay=False,
        decision_artifacts=True, named_gear=True,
    ),
    viewer_view_priority=("smooth", "hard"),
    route_definitions=_tree_routes("arcane", "fire", "frost"),
    source_class_key="mage", comparison_default=True, accent="#71b7ff",
))

register(ClassDefinition(
    ruleset="forever", class_name="paladin",
    engine_module="src.rulesets.forever.classes.paladin.engine",
    talent_module="src.rulesets.forever.classes.paladin.talents",
    display_name="Paladin", tree_names=("holy", "protection", "retribution"),
    primary_profiles=("all", "holy", "protection", "retribution"),
    capabilities=ClassCapabilities(
        source_snapshot=True, state=True, action_score=True, policy=True,
        stat_weights=True, fidelity=True, replay=True,
        decision_artifacts=True, named_gear=True,
    ),
    viewer_view_priority=("experimental",),
    route_definitions={
        "holy": {"label": "Holy endpoint", "kind": "tree_points", "tree": "holy", "minimum": 11},
        "protection": {"label": "Protection endpoint", "kind": "talent", "talent": "improved_seal_of_fury", "minimum": 1},
        "retribution": {"label": "Retribution endpoint", "kind": "talent", "talent": "seal_of_command", "minimum": 1},
    },
    source_class_key="paladin", comparison_default=True, accent="#f5c96b",
))

register(ClassDefinition(
    ruleset="forever", class_name="druid",
    engine_module="src.rulesets.forever.classes.druid.engine",
    talent_module="src.rulesets.forever.classes.druid.talents",
    display_name="Druid", tree_names=("balance", "feral", "restoration"),
    primary_profiles=("all", "balance", "feral", "bear", "restoration"),
    capabilities=ClassCapabilities(
        source_snapshot=True, state=True, action_score=True, policy=True,
        stat_weights=True, fidelity=True, replay=False,
        decision_artifacts=True, named_gear=False,
    ),
    viewer_view_priority=("experimental",),
    route_definitions={
        "balance": {"label": "Balance", "kind": "tree_points", "tree": "balance", "minimum": 11, "score_profile": "balance"},
        "feral_cat": {"label": "Feral · Cat", "kind": "tree_points", "tree": "feral", "minimum": 11, "score_profile": "feral", "publication_profile": "cat"},
        "feral_bear": {"label": "Feral · Bear", "kind": "tree_points", "tree": "feral", "minimum": 11, "score_profile": "bear", "publication_profile": "bear"},
        "restoration": {"label": "Restoration", "kind": "tree_points", "tree": "restoration", "minimum": 11},
    },
    source_class_key="druid", comparison_default=True, accent="#ff884d",
))

# Hunter uses the shared experimental optimizer contract. Its verified behavioral
# cap remains L20; fidelity metadata carries the unresolved mechanics explicitly.
register(ClassDefinition(
    ruleset="forever", class_name="hunter",
    engine_module="src.rulesets.forever.classes.hunter.engine",
    talent_module="src.rulesets.forever.classes.hunter.talents",
    display_name="Hunter", tree_names=("beast_mastery", "marksmanship", "survival"),
    primary_profiles=("all", "beast_mastery", "marksmanship", "survival"),
    capabilities=ClassCapabilities(
        source_snapshot=False, state=True, action_score=True, policy=True,
        stat_weights=True, fidelity=True, replay=False,
        decision_artifacts=True, named_gear=True,
    ),
    viewer_view_priority=("experimental",),
    route_definitions=_tree_routes("beast_mastery", "marksmanship", "survival"),
    comparison_default=False, accent="#aad372",
))

register(ClassDefinition(
    ruleset="forever", class_name="warrior",
    engine_module="src.rulesets.forever.classes.warrior.engine",
    talent_module="src.rulesets.forever.classes.warrior.talents",
    display_name="Warrior", tree_names=("arms", "fury", "protection"),
    primary_profiles=("all", "arms", "fury", "protection"),
    capabilities=ClassCapabilities(
        source_snapshot=True, state=True, action_score=True, policy=True,
        stat_weights=True, fidelity=True, replay=False,
        decision_artifacts=True, named_gear=False,
    ),
    viewer_view_priority=("experimental",),
    route_definitions=_tree_routes("arms", minimum=1),
    source_class_key="warrior", comparison_default=False, accent="#c79c6e",
    proof_only=True,
))


# G38: source-backed generic Rogue combat proof.  No legacy route/scorer is
# fabricated.  Generic product opts into this class separately, so the normal
# legacy route dashboard is unchanged until G39 route closure.
register(ClassDefinition(
    ruleset="forever", class_name="rogue",
    engine_module="src.game.data.forever.rogue",
    display_name="Rogue", tree_names=("assassination", "combat", "subtlety"),
    primary_profiles=("all",), capabilities=ClassCapabilities(state=True),
    route_definitions={
        "assassination": {"label":"Improved Eviscerate endpoint", "kind":"talent",
                          "talent":"improved_eviscerate", "minimum":3},
        "combat": {"label":"Improved Sinister Strike endpoint", "kind":"talent",
                   "talent":"improved_sinister_strike", "minimum":2},
    },
    ui_visible=False, comparison_default=False, accent="#fff569", proof_only=True,
))


# G40: source-backed generic Priest caster/wand proof, not legacy optimizer.
register(ClassDefinition(
    ruleset="forever", class_name="priest",
    engine_module="src.game.data.forever.priest",
    display_name="Priest", tree_names=("discipline", "holy", "shadow"),
    primary_profiles=("all",), capabilities=ClassCapabilities(state=True),
    route_definitions={}, ui_visible=False, comparison_default=False,
    accent="#ffffff", proof_only=True,
))


# G41: Shaman lives only in the generic source-backed runtime, not legacy.
register(ClassDefinition(
    ruleset="forever", class_name="shaman",
    engine_module="src.game.data.forever.shaman",
    display_name="Shaman", tree_names=("elemental", "enhancement", "restoration"),
    primary_profiles=("all",), capabilities=ClassCapabilities(state=True),
    route_definitions={}, ui_visible=False, comparison_default=False,
    accent="#0070de", proof_only=True,
))


def get_definition(ruleset: str, class_name: str) -> ClassDefinition:
    key = (str(ruleset).strip().lower(), str(class_name).strip().lower())
    try:
        return _DEF[key]
    except KeyError as exc:
        supported = ", ".join(f"{a}/{b}" for a, b in sorted(_DEF))
        raise ClassRegistryError(f"{key[0]}/{key[1]} is not registered; supported: {supported}") from exc


def registered_games() -> tuple[tuple[str, str], ...]:
    return tuple(sorted(_DEF))


def rulesets() -> tuple[str, ...]:
    return tuple(sorted({ruleset for ruleset, _ in _DEF}))


def class_names(ruleset: str | None = None, *, ui_visible: bool | None = None,
                comparison_default: bool | None = None) -> tuple[str, ...]:
    out: list[str] = []
    for (r, c), definition in sorted(_DEF.items()):
        if ruleset is not None and r != str(ruleset).lower():
            continue
        if ui_visible is not None and bool(definition.ui_visible) != bool(ui_visible):
            continue
        if comparison_default is not None and bool(definition.comparison_default) != bool(comparison_default):
            continue
        if c not in out:
            out.append(c)
    return tuple(out)


def definitions(ruleset: str | None = None) -> tuple[ClassDefinition, ...]:
    return tuple(_DEF[key] for key in sorted(_DEF) if ruleset is None or key[0] == str(ruleset).lower())


def validate_registry() -> None:
    for definition in definitions():
        definition.validate()


class ClassAdapter:
    """Uniform access to the cross-cutting hooks declared by ClassDefinition.

    This adapter is intentionally small: mechanics modules remain authoritative.
    Its job is to make capability checks/failures uniform so shared code does
    not grow another class-name branch whenever a backend is added.
    """

    def __init__(self, definition: ClassDefinition):
        self.definition = definition

    def _require(self, capability: str) -> None:
        if not bool(getattr(self.definition.capabilities, capability, False)):
            raise ClassRegistryError(f"{self.definition.key} lacks required capability: {capability}")

    def engine(self) -> ModuleType:
        return self.definition.engine()

    def state_root(self, project_root) -> Any:
        from pathlib import Path
        root = Path(project_root) / "state"
        if self.definition.ruleset == "classic" and self.definition.class_name == "mage":
            return root
        return root / "games" / self.definition.key

    def source_catalogue(self):
        self._require("source_snapshot")
        if self.definition.ruleset != "forever":
            raise ClassRegistryError(f"{self.definition.key} has no Forever source catalogue")
        from src.rulesets.forever.data.catalogue import default_catalogue
        return default_catalogue()

    def source_spell(self, family_key: str, *, level: int | None = None, spell_id: int | None = None):
        cat = self.source_catalogue()
        return cat.spell_rank(self.definition.source_catalogue_key(), family_key, level=level, spell_id=spell_id)

    def source_talent(self, local_key: str):
        cat = self.source_catalogue()
        return cat.talent(self.definition.source_catalogue_key(), local_key)

    def score(self, level: int, talents, *, profile: str = "all") -> dict:
        self._require("action_score")
        hook = getattr(self.engine(), "experimental_level_score", None)
        if not callable(hook):
            raise ClassRegistryError(f"{self.definition.key} declares action_score but has no experimental_level_score")
        return dict(hook(int(level), talents, profile) or {})

    def describe_policy(self, *, level: int, policy=None, score: Mapping[str, Any] | None = None) -> str | None:
        self._require("policy")
        engine = self.engine()
        hook = getattr(engine, "policy_desc", None)
        if callable(hook) and policy is not None:
            return str(hook(policy, int(level)))
        row = dict(score or {})
        value = row.get("policy") or row.get("rotation")
        return str(value) if value is not None else None

    def stat_weights(self, level: int, talents, *, baseline: dict, policy=None, cfg=None, profile: str = "all", options=None):
        self._require("stat_weights")
        from src.v2.stat_weight_model import compute_for_engine
        return compute_for_engine(
            self.engine(), int(level), talents, baseline=baseline, policy=policy,
            cfg=cfg, profile=profile, options=options,
        )

    def fidelity(self) -> dict[str, Any]:
        self._require("fidelity")
        return self.definition.fidelity()

    def replay(self, level: int, candidates):
        self._require("replay")
        hook = getattr(self.engine(), "event_validate_candidates", None)
        if not callable(hook):
            raise ClassRegistryError(f"{self.definition.key} declares replay but has no event_validate_candidates")
        return hook(int(level), candidates)

    def decision_metadata(self) -> dict[str, Any]:
        self._require("decision_artifacts")
        return {
            "ruleset": self.definition.ruleset,
            "class": self.definition.class_name,
            "display_name": self.definition.display_name,
            "tree_names": list(self.definition.tree_names),
            "primary_profiles": list(self.definition.primary_profiles),
            "capabilities": self.definition.capabilities.as_dict(),
            "model_fidelity": self.definition.fidelity() if self.definition.capabilities.fidelity else {},
            "proof_only": bool(self.definition.proof_only),
        }


def adapter(ruleset: str, class_name: str) -> ClassAdapter:
    return ClassAdapter(get_definition(ruleset, class_name))
