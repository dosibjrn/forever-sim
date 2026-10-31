from __future__ import annotations

"""Target-server Druid semantics not fully fixed by public Forever data.

These values are explicit configuration with provenance. They are not claims
that every Forever-compatible server shares the same hidden server formulas.
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class DruidServerProfile:
    key: str
    incoming_rage_level2_coeff: float
    incoming_rage_level_coeff: float
    incoming_rage_constant: float
    incoming_rage_damage_multiplier: float
    incoming_rage_income_rate: float
    incoming_rage_fixed_armor_damage_taken_fraction: float
    incoming_rage_provenance: str

    def with_overrides(self, **kwargs) -> "DruidServerProfile":
        return replace(self, **kwargs)


CURRENT_TARGET_SERVER_PROFILE = DruidServerProfile(
    key="forever_current_target_2026_09_27",
    incoming_rage_level2_coeff=0.0091107836,
    incoming_rage_level_coeff=3.225598133,
    incoming_rage_constant=4.2652911,
    incoming_rage_damage_multiplier=2.5,
    incoming_rage_income_rate=1.0,
    incoming_rage_fixed_armor_damage_taken_fraction=0.5,
    incoming_rage_provenance=(
        "forever_blizzard_class_deep_dive:original_damage_taken_rage_formula; "
        "armor_ignored_and_original_formula_evaluated_as_if_50pct_armor_reduction; "
        "absorb_ignored; conversion_coefficients_pinned_to_cmangos_classic_1_12_RewardRage@"
        "8ec338a1704e7dcb1c0213eb7ed58f9231ade40f"
    ),
)
