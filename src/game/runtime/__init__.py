"""Legacy runtime compatibility exports loaded on demand.

Importing lightweight events must not instantiate the transitional Python
CombatRuntime/GameIR stack. Existing public names resolve to their original
objects when a caller explicitly requests them, until native Rust migration
can retire the legacy implementation.
"""

from importlib import import_module

__all__ = [
    "ActionEligibility",
    "ActionExecutionResult",
    "ActionNotEligibleError",
    "ActionSequenceResult",
    "CombatRuntime",
    "CombatTimelineResult",
    "ActorState",
    "CombatEvent",
    "EventQueue",
    "TargetState",
    "action_eligibility",
    "execute_action",
    "execute_repeated_actions",
    "execute_action_timeline",
    "expected_auto_attack_swing",
    "expected_weapon_damage",
    "expected_direct_damage",
    "expected_incoming_attack",
    "expected_direct_heal",
    "expected_periodic_tick_damage",
    "expected_periodic_tick_heal",
]

_EVENT_EXPORTS = frozenset(("CombatEvent", "EventQueue"))
_STATE_EXPORTS = frozenset(("ActorState", "TargetState"))


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = (
        ".events" if name in _EVENT_EXPORTS else
        ".state" if name in _STATE_EXPORTS else
        ".simulator"
    )
    value = getattr(import_module(module, package=__name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
