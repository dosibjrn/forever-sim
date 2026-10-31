from __future__ import annotations

"""Target-server Mage semantics that public Forever source data does not fully fix.

The default profile is intentionally explicit.  Values here are *configuration
with provenance*, not claims that every Forever-compatible server behaves the
same way.
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class MageServerProfile:
    key: str
    blizzard_aoe_leveling_enabled: bool
    ice_lance_sp_coefficient: float
    ice_lance_sp_coefficient_provenance: str
    ice_lance_frozen_damage_multiplier: float
    ice_lance_frozen_multiplier_provenance: str
    fingers_of_frost_charges: int
    fingers_of_frost_charges_provenance: str
    root_break_mode: str
    root_break_base: float
    root_break_damage_scale: float
    root_break_fire_bonus: float
    root_break_provenance: str
    moving_melee_leeway: float
    moving_melee_leeway_provenance: str
    evocation_enabled: bool
    evocation_channel_s: float
    evocation_restore_fraction: float
    evocation_cooldown_s: float
    evocation_provenance: str
    mana_gem_enabled: bool
    mana_gem_cooldown_s: float
    mana_gem_restock_s: float

    def with_overrides(self, **kwargs) -> "MageServerProfile":
        return replace(self, **kwargs)

    def capabilities(self) -> dict[str, bool]:
        return {
            "mage.blizzard_aoe_leveling": bool(self.blizzard_aoe_leveling_enabled),
        }

    def with_blizzard_aoe_leveling(self, enabled: bool) -> "MageServerProfile":
        """Return an explicit per-run server capability override.

        This only declares that the target server supports the strategy lane; it
        does not silently substitute the single-target scorer for an AoE model.
        The Mage ClassModel owns the fail-closed guard until the AoE scorer is
        implemented.
        """
        enabled = bool(enabled)
        suffix = "aoe_on" if enabled else "aoe_off"
        return replace(
            self,
            key=f"{self.key}:{suffix}",
            blizzard_aoe_leveling_enabled=enabled,
        )


CURRENT_TARGET_SERVER_PROFILE = MageServerProfile(
    key="forever_current_target_2026_09_26",
    # Direct target-server observation/user evidence: the classic Blizzard AoE
    # grind lane is not a generally viable strategy here.  Keep it out of search
    # and, crucially, out of M46 blocker accounting while disabled.
    blizzard_aoe_leveling_enabled=False,
    # Forever public data does not expose an SP modifier for Ice Lance.  The
    # reviewer research found TBC Classic's direct modifier ~= 0.143.  Use the
    # exact 1/7 proxy only as an explicit server-profile value until a target-
    # server combat-log/source probe supersedes it.
    ice_lance_sp_coefficient=1.0 / 7.0,
    ice_lance_sp_coefficient_provenance=(
        "parameterized_proxy:tbc_classic_sp_mod_0.143; forever_public_row_has_no_sp_modifier"
    ),
    # Reviewer research interprets the published Frozen behavior as 300% total
    # damage, i.e. a 3x multiplier.  Keeping the multiplier separate from the SP
    # coefficient prevents coefficient/multiplier double counting.
    ice_lance_frozen_damage_multiplier=3.0,
    ice_lance_frozen_multiplier_provenance="forever_public_frozen_damage_300_percent_total",
    # Pinned Forever database records say next 2 spells; a current guide says 1.
    # Default to the database record, preserve the conflict in provenance, and
    # make the value profile-scoped so an in-game probe can override it cleanly.
    fingers_of_frost_charges=2,
    fingers_of_frost_charges_provenance=(
        "pinned_forever_db:400647/400669=2; current_guide_conflict=1; target_server_probe_pending"
    ),
    # Root-break behavior and the extra moving melee-contact leeway are not
    # established by current public Forever data. Keep the former Classic-like
    # search proxy and zero extra leeway, but make both target-server profile
    # values so they cannot masquerade as universal engine constants.
    root_break_mode="scaled",
    root_break_base=0.18,
    root_break_damage_scale=2.6,
    root_break_fire_bonus=0.10,
    root_break_provenance=(
        "parameterized_proxy:classic_like_damage_scaled_root_break; target_server_probe_pending"
    ),
    moving_melee_leeway=0.0,
    moving_melee_leeway_provenance=(
        "parameterized_proxy:no_extra_moving_leeway; target_server_probe_pending"
    ),
    # Current Forever public Evocation row is a 6 s channel with Mana Surge
    # every 0.5 s, value 2.  Until the trigger spell is source-resolved we keep
    # the natural 12*2%=24% max-mana interpretation explicitly profile-scoped.
    evocation_enabled=True,
    evocation_channel_s=6.0,
    evocation_restore_fraction=0.24,
    # Current Forever row reports cooldown n/a. Keep that as an explicit 0 s
    # profile value rather than silently assuming Classic's historical CD.
    evocation_cooldown_s=0.0,
    evocation_provenance=(
        "parameterized_proxy:forever_evocation_1303599=6s; mana_surge_value_2_every_0.5s; interpreted_24pct_max_mana; probe_pending"
    ),
    mana_gem_enabled=True,
    mana_gem_cooldown_s=120.0,
    mana_gem_restock_s=3.0,
)
