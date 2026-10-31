from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


VALID_STATUS = {"unsupported", "override", "proxy", "partial", "not_probeable"}
VALID_SEVERITY = {"low", "medium", "high"}
VALID_IMPACT = {"data", "rotation", "throughput", "survival", "resource", "stat_weight"}
PRODUCTION_CLASSES = ("mage", "paladin", "druid")


@dataclass(frozen=True)
class FidelityIssue:
    issue_id: str
    class_key: str
    mechanic: str
    status: str
    severity: str
    impacts: tuple[str, ...]
    summary: str
    evidence: tuple[str, ...]
    resolution: str
    source_ids: tuple[int, ...] = ()
    required_capability: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# M46 contract: fidelity gaps are finite, named, and intentional.  This registry
# is deliberately about *modeled behavior*, not source-roster ID coverage.  A
# spell/talent can be source-resolved while its server semantics remain partial.
ISSUES: tuple[FidelityIssue, ...] = (
    FidelityIssue(
        "mage.blizzard_aoe_leveling", "mage", "Blizzard/AoE leveling capability", "partial", "medium",
        ("rotation", "throughput"),
        "Blizzard-centric AoE grinding is a server-dependent strategy lane. It is explicitly disabled for the current target-server profile, so its unimplemented AoE geometry/channel search is documented but is not an M46 blocker for that profile.",
        ("src/rulesets/forever/classes/mage/server_profile.py:CURRENT_TARGET_SERVER_PROFILE",),
        "Enable the server capability only when target-server evidence says the strategy is viable; enabled profiles must then provide AoE geometry/channel/policy support and independent validation.",
        (10,),
        "mage.blizzard_aoe_leveling",
    ),
    FidelityIssue(
        "mage.ice_lance_spell_power_coefficient", "mage", "Ice Lance Spell Power coefficient", "override", "low",
        ("throughput", "stat_weight"),
        "Forever public data does not expose Ice Lance's SP modifier. The current target-server profile therefore owns an explicit 1/7 TBC-like proxy with provenance instead of a universal hidden fallback; Frozen scaling is applied separately as a 3x multiplier.",
        ("src/rulesets/forever/classes/mage/server_profile.py:CURRENT_TARGET_SERVER_PROFILE", "src/rulesets/forever/classes/mage/engine.py:spell_power_direct_coeff"),
        "Replace the profile value when target-server combat-log/source evidence becomes available; keep unfrozen-vs-Frozen SP-delta regression to prevent coefficient/multiplier double counting.",
        (1312002,),
    ),
    FidelityIssue(
        "mage.fingers_of_frost_charge_count", "mage", "Fingers of Frost charge count", "override", "low",
        ("rotation", "throughput"),
        "Pinned Forever database records say the next 2 spells are treated as Frozen while a current guide says 1. The charge count is now target-server-profile scoped; the current profile defaults to the pinned database value 2 and preserves the conflict in provenance.",
        ("src/rulesets/forever/classes/mage/server_profile.py:CURRENT_TARGET_SERVER_PROFILE",),
        "Override the profile from an in-game target-server probe if the server consumes a different number of charges.",
        (400647, 400669),
    ),
    FidelityIssue(
        "mage.root_break_and_melee_leeway", "mage", "Root break / melee leeway", "partial", "low",
        ("survival", "throughput"),
        "Frostbite/Frost Nova root-break behavior and moving melee-contact leeway are explicit target-server-profile parameters. The current profile retains a Classic-like scaled root-break proxy and zero extra leeway until target-server evidence replaces them.",
        ("src/rulesets/forever/classes/mage/server_profile.py:CURRENT_TARGET_SERVER_PROFILE", "src/rulesets/forever/classes/mage/engine.py:SimConfig.__post_init__"),
        "Replace the profile values when target-server combat-log/server evidence establishes different root-break or contact behavior; keep mutation regressions proving runtime follows the profile.",
    ),
    FidelityIssue(
        "paladin.seal_of_fury_absorb_replacement", "paladin", "Seal of Fury absorb stacking/replacement", "not_probeable", "low",
        ("resource", "survival", "throughput"),
        "Public Forever data establishes a per-attack absorb equal to 50% of Seal damage, but does not expose whether repeated grants stack or replace. Fast and event replay now share one explicit replacement interpretation.",
        ("src/rulesets/forever/classes/paladin/survival.py replacing_absorb_dynamics", "Forever Seal of Fury tooltip / spell family source effect"),
        "Keep the replacement interpretation explicit until combat-log or server-script evidence establishes stacking behavior; no remaining Fast/event mismatch exists under that interpretation.",
    ),
    FidelityIssue(
        "druid.feral_weapon_component", "druid", "Feral fixed form-speed constants", "partial", "low",
        ("throughput", "stat_weight"),
        "Current Forever guides establish that equipped weapon DPS carries into both Cat and Bear and equipped weapon speed is irrelevant to form DPS. Runtime now consumes named weapon-DPS anchors directly. The remaining uncertainty is the target-server fixed Cat/Bear swing constants used to turn DPS into normal-weapon hits for percentage-weapon abilities.",
        ("src/rulesets/forever/classes/druid/weapon.py", "current Wowhead/Icy Veins Forever Feral guides"),
        "Probe target-server Cat/Bear swing timers; until then keep the explicit 1.0s/2.5s Classic-derived form-speed parameters visible.",
    ),
    FidelityIssue(
        "druid.incoming_damage_rage", "druid", "Bear rage from incoming damage", "partial", "low",
        ("resource", "rotation", "throughput"),
        "Blizzard states Forever keeps the original incoming-damage Rage formula but ignores real Armor and absorbs, evaluating the original formula as if Armor always reduced damage by 50%. The original conversion coefficients remain pinned to Classic RewardRage provenance.",
        ("Blizzard Forever Warrior Class Deep Dive https://worldofwarcraft.blizzard.com/en-us/news/24301514", "src/rulesets/forever/classes/druid/server_profile.py", "src/rulesets/forever/classes/druid/rage.py", "CMaNGOS Player::RewardRage @ 8ec338a1704e7dcb1c0213eb7ed58f9231ade40f"),
        "Keep the fixed-50%-Armor rule source-backed and separate from real Bear mitigation. Revisit only if Blizzard changes Forever Rage semantics or a newer build-specific source supersedes the class deep dive.",
    ),
    FidelityIssue(
        "druid.ooc_health_regen", "druid", "Out-of-combat health regeneration", "proxy", "low",
        ("survival", "throughput"),
        "Druid out-of-combat health regeneration uses an explicit Classic-like proxy.",
        ("src/rulesets/forever/classes/druid/mechanics.py OOC health regen proxy",),
        "Replace with Forever-specific recovery evidence when available.",
    ),
)


def issues_for(class_key: str | None = None) -> tuple[FidelityIssue, ...]:
    if class_key is None:
        return ISSUES
    key = str(class_key).strip().lower()
    return tuple(row for row in ISSUES if row.class_key == key)


def validate_inventory(rows: Iterable[FidelityIssue] = ISSUES) -> list[str]:
    rows = tuple(rows)
    errors: list[str] = []
    ids: set[str] = set()
    covered: set[str] = set()
    for row in rows:
        if row.issue_id in ids:
            errors.append(f"duplicate issue_id: {row.issue_id}")
        ids.add(row.issue_id)
        if row.class_key not in PRODUCTION_CLASSES:
            errors.append(f"unknown production class: {row.issue_id}:{row.class_key}")
        covered.add(row.class_key)
        if row.status not in VALID_STATUS:
            errors.append(f"invalid status: {row.issue_id}:{row.status}")
        if row.severity not in VALID_SEVERITY:
            errors.append(f"invalid severity: {row.issue_id}:{row.severity}")
        if not row.impacts:
            errors.append(f"missing impact: {row.issue_id}")
        for impact in row.impacts:
            if impact not in VALID_IMPACT:
                errors.append(f"invalid impact: {row.issue_id}:{impact}")
        if not row.evidence:
            errors.append(f"missing evidence: {row.issue_id}")
        if not row.resolution.strip():
            errors.append(f"missing resolution: {row.issue_id}")
    for class_key in PRODUCTION_CLASSES:
        if class_key not in covered:
            errors.append(f"missing class inventory: {class_key}")
    return errors



def _target_capabilities() -> dict[str, bool]:
    from src.rulesets.forever.classes.mage.server_profile import CURRENT_TARGET_SERVER_PROFILE
    return CURRENT_TARGET_SERVER_PROFILE.capabilities()


def issue_active(row: FidelityIssue, capabilities: dict[str, bool] | None = None) -> bool:
    if not row.required_capability:
        return True
    caps = _target_capabilities() if capabilities is None else capabilities
    return bool(caps.get(row.required_capability, False))


def blocking_issues(capabilities: dict[str, bool] | None = None) -> tuple[FidelityIssue, ...]:
    return tuple(
        row for row in ISSUES
        if row.severity in {"high", "medium"} and issue_active(row, capabilities)
    )

def inventory_report() -> dict:
    errors = validate_inventory()
    by_class = {}
    for class_key in PRODUCTION_CLASSES:
        rows = issues_for(class_key)
        issue_rows = []
        for r in rows:
            item = r.to_dict()
            item["active_for_target_server"] = issue_active(r)
            item["blocks_m46_for_target_server"] = bool(r.severity in {"high", "medium"} and issue_active(r))
            issue_rows.append(item)
        by_class[class_key] = {
            "count": len(rows),
            "high": sum(r.severity == "high" for r in rows),
            "medium": sum(r.severity == "medium" for r in rows),
            "low": sum(r.severity == "low" for r in rows),
            "blocking_high_medium": sum(r.severity in {"high", "medium"} and issue_active(r) for r in rows),
            "issues": issue_rows,
        }
    return {
        "schema_version": 1,
        "scope": "Forever production-class modeled-behavior fidelity gaps; source identity coverage is audited separately",
        "classes": by_class,
        "ok": not errors,
        "errors": errors,
    }
