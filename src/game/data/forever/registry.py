from __future__ import annotations

"""Registry of source-backed Forever Game IR providers.

The generic backend asks this registry for data; it does not dispatch gameplay
semantics on class names.  Adding a class is a data-provider registration until
a genuinely new reusable mechanic is required.
"""

from collections.abc import Callable
from dataclasses import replace
from importlib import import_module

from src.game.model.ir import GameIRSlice
from .source_db_scope import ability_source_scope


Provider = Callable[..., GameIRSlice | None]

def _lazy_class_provider(class_key: str) -> Provider:
    """Keep source-specific GameIR builders off metadata/selection import paths."""
    def build(level: int, *, ability_db_path=None):
        provider = import_module(f".{class_key}", package=__package__).build_source_slice
        if ability_db_path is not None:
            from inspect import signature
            if "ability_db_path" in signature(provider).parameters:
                return provider(int(level), ability_db_path=ability_db_path)
        return provider(int(level))
    return build


def _lazy_native_provider(class_key: str) -> Provider:
    """The transitional SQLite provider is needed only for a requested build."""
    def build(level: int):
        from .native_source_provider import build_source_slice
        return build_source_slice(class_key, int(level))
    return build


_PROVIDERS: dict[str, Provider] = {
    key: _lazy_class_provider(key)
    for key in ("druid", "warrior", "rogue", "priest", "shaman", "warlock", "mage")
}
_PROVIDERS.update({
    key: _lazy_native_provider(key) for key in ("hunter", "paladin")
})


def build_game_ir_slice(*, class_key: str, level: int, ability_db_path=None,
                        use_runes: bool = False) -> GameIRSlice | None:
    """Build one complete source IR from one selected ability SQLite.

    An explicit staged snapshot is scoped across legacy provider facts, talents,
    rank promotion, maintenance, and the generic action compiler. It does not
    make unverified data eligible for a checkpoint.
    """
    with ability_source_scope(ability_db_path):
        ir = _build_game_ir_slice_inner(
            class_key=class_key, level=level, ability_db_path=ability_db_path)
    if ir is None:
        return None
    # Keep the legacy source-index rune policy isolated from provider dispatch.
    disabled_ids = set()
    if not use_runes:
        from .source_rune_policy import filter_default_runes
        ir, disabled_ids = filter_default_runes(
            ir, class_key=class_key, level=level, ability_db_path=ability_db_path)
    return replace(ir,provenance={**ir.provenance,
        'rune_system_enabled':bool(use_runes),
        'rune_engraving_policy':'DEFAULT_DISABLED_REQUIRE_EXPLICIT_SOURCE_PROOF',
        'rune_disabled_action_ids':sorted(disabled_ids) if not use_runes else []})


def _build_game_ir_slice_inner(*, class_key: str, level: int, ability_db_path=None) -> GameIRSlice | None:
    """Build from source facts, optionally from an isolated ability-stage SQLite.

    The override is only for indexed ability compilation and its matching
    coverage ledger; unrelated game datasets retain their canonical sources.
    This is NOT proof that staged facts were independently verified.
    """
    provider = _PROVIDERS.get(str(class_key).strip().lower())
    if provider is None:
        return None
    if ability_db_path is not None:
        # Provider capability inspection keeps SQLite overrides generic; a
        # source adapter declaring this argument must read the SAME staged DB
        # as the shared compiler. Do not special-case class names here.
        from inspect import signature
        accepts_db = 'ability_db_path' in signature(provider).parameters
        ir = provider(int(level), ability_db_path=ability_db_path) if accepts_db else provider(int(level))
    else:
        ir = provider(int(level))
    if ir is None:
        return None
    # Source overlays belong to their legacy assembly boundary, not dispatch.
    from .source_ir_assembly import assemble_source_ir
    return assemble_source_ir(
        ir, class_key=class_key, level=level, ability_db_path=ability_db_path)

def registered_class_keys() -> tuple[str, ...]:
    return tuple(sorted(_PROVIDERS))


# G47b: provider-declared *source IR* bounds and independently verified
# planning corridors. These are NOT full playable-level or race support.
# A new provider without a declaration remains discoverable but unverified.
_PROVIDER_SUPPORT: dict[str, dict] = {
    "druid": {"source_levels": (1, 60), "planning_levels": (10, 11, 12, 13, 14)},
    "warrior": {"source_levels": (10, 30), "planning_levels": (10, 11, 12)},
    "rogue": {"source_levels": (10, 20), "planning_levels": (10, 11, 12, 13, 14)},
    "priest": {"source_levels": (10, 20), "planning_levels": ()},
    "shaman": {"source_levels": (10, 20), "planning_levels": ()},
    "warlock": {"source_levels": (10, 20), "planning_levels": ()},
    "mage": {"source_levels": (10, 30), "planning_levels": ()},
    "hunter": {"source_levels": (10, 20), "planning_levels": ()},
    "paladin": {"source_levels": (10, 30), "planning_levels": ()},
}


def generic_planning_levels(class_key: str) -> tuple[int, ...]:
    """Canonical executable route corridor; empty means no proven route."""
    return tuple(int(x) for x in _PROVIDER_SUPPORT.get(str(class_key).lower(), {}).get("planning_levels", ()))


def generic_source_level_bounds(class_key: str) -> tuple[int, int] | None:
    """Bounds for constructing a source IR slice, NOT leveling fidelity."""
    bounds = _PROVIDER_SUPPORT.get(str(class_key).lower(), {}).get("source_levels")
    return (int(bounds[0]), int(bounds[1])) if bounds else None


# G49a: default-authority eligibility is an *explicit product declaration*.
# A source IR, a combat probe or even a short native route alone cannot opt a
# class into the default.  Future releases must prove each required dimension
# before declaring exact eligible levels in _PROVIDER_SUPPORT.
_DEFAULT_REQUIRED = (
    "leveling_continuity", "gear_optimization", "stat_weights",
    "policy_optimization", "timing", "route_planning", "race_selection",
)


def generic_default_ready_levels(class_key: str) -> tuple[int, ...]:
    """Verified product-complete levels, empty unless every gate is declared.

    This never probes or evaluates Game IR and is safe on the HTTP hot path.
    """
    key = str(class_key).strip().lower()
    if key not in _PROVIDERS:
        return ()
    support = _PROVIDER_SUPPORT.get(key, {})
    capabilities = support.get("product_capabilities") or {}
    if not all(capabilities.get(name) is True for name in _DEFAULT_REQUIRED):
        return ()
    bounds = generic_source_level_bounds(key)
    planned = set(generic_planning_levels(key))
    if bounds is None or not planned:
        return ()
    declared = support.get("default_ready_levels") or ()
    try:
        levels = tuple(sorted({int(n) for n in declared}))
    except (TypeError, ValueError):
        return ()
    if any(n < bounds[0] or n > bounds[1] or n not in planned for n in levels):
        # Reject the whole declaration rather than silently trimming its scope.
        return ()
    return levels


# G47: one publication catalog for native generic providers. Metadata is
# owned by the provider registry, not copied into the listener/dashboard.
_GENERIC_DISPLAY = {
    "druid": ("Druid", "#ff7d0a", ("balance", "feral", "restoration")),
    "warrior": ("Warrior", "#c79c6e", ("arms", "fury", "protection")),
    "rogue": ("Rogue", "#fff569", ("assassination", "combat", "subtlety")),
    "priest": ("Priest", "#ffffff", ("discipline", "holy", "shadow")),
    "shaman": ("Shaman", "#0070de", ("elemental", "enhancement", "restoration")),
    "warlock": ("Warlock", "#9482c9", ("affliction", "demonology", "destruction")),
    "mage": ("Mage", "#69ccf0", ("arcane", "fire", "frost")),
    "hunter": ("Hunter", "#abd473", ("beast_mastery", "marksmanship", "survival")),
    "paladin": ("Paladin", "#f58cba", ("holy", "protection", "retribution")),
}


def generic_class_metadata(*, selected_level: int | None = None) -> dict[str, dict]:
    """Source-provider capability and route planning, never inferred from legacy.

    The IR may carry a *representative scenario race*. That does not establish
    which races are playable or prove any other race has modeled starting stats.
    """
    result = {}
    for key in registered_class_keys():
        display, accent, trees = _GENERIC_DISPLAY.get(key, (key.replace('_', ' ').title(), '#cccccc', ()))
        bounds = generic_source_level_bounds(key)
        levels = generic_planning_levels(key)
        source_level_available = bool(bounds and selected_level is not None
                                      and bounds[0] <= int(selected_level) <= bounds[1])
        default_levels = generic_default_ready_levels(key)
        product_caps = dict(_PROVIDER_SUPPORT.get(key, {}).get("product_capabilities") or {})
        scenario_race = None
        if bounds is not None:
            # Probe one representative IR at the provider's declared minimum;
            # this is a cheap metadata read, not a route/combat evaluation.
            try:
                ir = build_game_ir_slice(class_key=key, level=bounds[0])
                if ir is not None:
                    scenario_race = ir.actor.metadata.get("race_key")
            except (ValueError, KeyError, TypeError):
                pass
        result[key] = {
            "display_name": display, "tree_names": list(trees),
            "primary_profiles": ["all"], "accent": accent,
            "proof_only": True, "declared_routes": [], "route_labels": {},
            "capabilities": {
                "state": bool(bounds),
                "source_ir": bool(bounds),
                "route_planning": bool(levels),
                "full_leveling": product_caps.get("leveling_continuity") is True,
                "race_selection": product_caps.get("race_selection") is True,
                "default_authority": bool(default_levels),
            },
            "source_registry": "forever_game_ir",
            "source_ir_level_bounds": (None if bounds is None else
                                       {"min": bounds[0], "max": bounds[1]}),
            "selected_level_source_ir_available": source_level_available,
            "planning_levels": list(levels),
            "default_ready_levels": list(default_levels),
            "product_capabilities": {name: product_caps.get(name) is True for name in _DEFAULT_REQUIRED},
            "default_ready_at_selected_level": (selected_level is not None
                                                and int(selected_level) in default_levels),
            "planning_level_cap": (max(levels) if levels else None),
            "planning_status": ("bounded_native_generic_route" if levels else "no_verified_route"),
            "race_availability": {
                "status": "not_verified_for_generic",
                "playable_races": [],
                "representative_scenario_race": scenario_race,
                "note": "Representative IR race is not a verified playable-race list.",
            },
        }
    return result
