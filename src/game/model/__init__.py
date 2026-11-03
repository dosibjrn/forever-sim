"""Legacy GameIR compatibility exports, resolved only for actual model consumers.

Source-only overlays and native adapter imports must not eagerly load the
transitional Python GameIR schema. Named public exports retain their exact
class identities until each live consumer is migrated to MythicSim Rust.
"""

from importlib import import_module

__all__ = [
    "ActionDefinition",
    "ActorDefinition",
    "ActorLinkModifier",
    "ArmorMitigationDefinition",
    "AutoAttackDamageSource",
    "AutoAttackDefinition",
    "DamageEffect",
    "ControlEffect",
    "SpatialChargeEffect",
    "GameIRSlice",
    "HealEffect",
    "ActivePeriodicFullHealEffect",
    "IncomingAttackDefinition",
    "IncomingEventProjection",
    "ModeChangeEffect",
    "ModeDefinition",
    "ModeResourceRule",
    "ModeResourceCapacityModifier",
    "ModeStatModifier",
    "PeriodicEffect",
    "PeriodicHealEffect",
    "PeriodicResourceEffect",
    "PolicyCondition",
    "PolicyDefinition",
    "PolicyRuleDefinition",
    "ResourceChangeEffect",
    "ResourceCost",
    "ResourceDefinition",
    "ResourceEventGainRule",
    "ResourceScaledPeriodicEffect",
    "ResourceScaledDirectDamageEffect",
    "TimedSummonDefinition",
    "SummonEffect",
    "TalentDefinition",
    "TalentModifier",
    "TalentRankDefinition",
    "TriggerDefinition",
    "TargetStatDebuffEffect",
    "TargetSchoolPowerEffect",
    "StatusAuraEffect",
    "EventEmitEffect",
    "WeaponDamageEffect",
    "QueuedSwingEffect",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(".ir", package=__name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
