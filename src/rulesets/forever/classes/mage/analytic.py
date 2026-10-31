"""Analytic Mage stat-gradient helpers.

Split from ``engine.py`` in v0.11.46.8; public names remain re-exported from
``mage.engine`` for compatibility.
"""
from __future__ import annotations

from . import wowhead_facts as wh
from .engine import (
    CRAFTED_ITEMS, Rank, SPELLS, SimConfig, Stats, Talents, WATER_SELF, WATER_USABLE,
    crit_mult, effective_magic_resistance_percent, latest, latest_pair,
    peer_exchange_budget_units, player_stats_for_config, spell_hit,
    spell_power_direct_coeff, spell_power_dot_coeff,
)

def _analytic_gradient_rank(spell: str, level: int):
    table = SPELLS.get(str(spell))
    return latest(table, int(level)) if table else None


def _analytic_gradient_static_crit(rank: Rank, t: Talents, stats: Stats) -> float:
    """Representative crit probability for the smooth gearing surrogate.

    Dynamic Shatter/Winter's Chill/Combustion state remains in the discrete
    validation kernel.  Those effects add crit chance but do not change the
    derivative of base Mage crit with respect to Intellect until the crit cap,
    so omitting their occupancy keeps this local surrogate simple and stable.
    """
    c = float(stats.spell_crit)
    if rank.spell in ('scorch', 'fire_blast', 'ice_lance', 'arcane_blast'):
        c += .02 * float(getattr(t, 'incineration', 0))
    if rank.school == 'arcane':
        c += .02 * float(getattr(t, 'arcane_impact', 0))
    if rank.school == 'fire':
        c += .02 * float(getattr(t, 'critical_mass', 0))
    return max(0.0, min(.99, c))


def _analytic_gradient_spell_terms(level: int, t: Talents, stats: Stats, cfg: SimConfig,
                                   rank: Rank) -> tuple[float, float, float]:
    """Return (modeled damage, dDamage/dSP, dDamage/dINT) for one cast/channel.

    This is deliberately a continuous local surrogate, not a second combat
    simulator.  It mirrors the expected direct-damage algebra while smoothing
    away root/proc/cast-count state.  The event simulator remains the validation
    authority for candidate ordering.
    """
    mob_level = int(level) + 1
    hit = float(spell_hit(int(level), mob_level, rank.school, t))
    # Reuse the same expected resistance model used by the deterministic kernel.
    resist = 1.0 - float(effective_magic_resistance_percent(
        int(level), mob_level, rank.school, t, cfg, binary=False
    ))
    resist = max(0.0, min(1.0, resist))

    mod = 1.0
    if rank.school == 'frost':
        mod *= 1.0 + .02 * float(getattr(t, 'piercing_ice', 0))
    if rank.school == 'fire':
        mod *= 1.0 + .02 * float(getattr(t, 'fire_power', 0))
    mod *= 1.0 + .01 * float(getattr(t, 'arcane_instability', 0))

    if rank.spell == 'arcane_missiles':
        base_direct = float(rank.channel_tick_damage) * max(1, int(rank.channel_ticks))
    else:
        base_direct = .5 * (float(rank.dmin) + float(rank.dmax))
    direct_coeff = float(spell_power_direct_coeff(rank,cfg.server_profile))
    direct_noncrit = (base_direct + float(stats.spell_power) * direct_coeff) * mod * resist

    crit = _analytic_gradient_static_crit(rank, t, stats)
    crit_mult_value = float(crit_mult(rank, t))
    # Ignite is additional expected damage conditional on a Fire crit.  In the
    # event kernel it receives 8% of crit damage per rank.
    ignite = .08 * float(getattr(t, 'ignite', 0)) if rank.school == 'fire' else 0.0
    crit_gain = crit_mult_value * (1.0 + ignite) - 1.0
    crit_factor = 1.0 + crit * crit_gain

    direct_damage = hit * direct_noncrit * crit_factor
    d_direct_d_sp = hit * (direct_coeff * mod * resist) * crit_factor

    # CMaNGOS/Forever Mage crit formula used by player_stats().  One Intellect
    # therefore has a closed-form crit derivative independent of probe size.
    dcrit_d_int = 1.0 / (100.0 * (14.77 + .65 * float(level)))
    if crit >= .99 - 1e-12:
        dcrit_d_int = 0.0
    d_direct_d_int = hit * direct_noncrit * crit_gain * dcrit_d_int

    # Attached periodic component. Pyroblast has an audited SP coefficient;
    # Fireball's attached DoT currently has none. Current Forever spell rows
    # explicitly flag Fireball/Pyroblast periodic damage as crit-capable.
    dot_base = float(rank.dot_total or 0.0)
    dot_coeff = float(spell_power_dot_coeff(rank))
    dot_noncrit = hit * (dot_base + float(stats.spell_power) * dot_coeff) * mod * resist
    dot_crit_factor = (1.0 + crit * (crit_mult_value - 1.0)) if rank.spell in wh.PERIODIC_CAN_CRIT_SPELLS else 1.0
    dot_damage = dot_noncrit * dot_crit_factor
    d_dot_d_sp = hit * dot_coeff * mod * resist * dot_crit_factor
    d_dot_d_int = (dot_noncrit * (crit_mult_value - 1.0) * dcrit_d_int
                     if rank.spell in wh.PERIODIC_CAN_CRIT_SPELLS else 0.0)

    return (
        max(0.0, direct_damage + dot_damage),
        max(0.0, d_direct_d_sp + d_dot_d_sp),
        max(0.0, d_direct_d_int + d_dot_d_int),
    )


def item_budget_units(level: int, *, baseline=None, profile: str = "all", stats=()) -> dict:
    """Shared empirical equal-budget exchange scale for Forever itemization."""
    return peer_exchange_budget_units(CRAFTED_ITEMS, int(level), stats=stats or ("intellect", "spirit", "spell_power"))


def analytic_stat_gradient(level: int, t: Talents, *, baseline: dict,
                           policy=None, cfg: SimConfig | None = None,
                           profile: str = 'all', options=None) -> dict:
    """Class-backend implementation of the shared analytic stat-gradient API.

    The smooth surrogate answers the gearing question continuously instead of
    asking whether a finite +/- stat probe happens to cross a cast-count step.
    It uses actual selected-policy cast mix from the analytical scorer, exact
    local Int->crit and SP coefficients, and a continuous mana-recovery model.
    The discrete/event score is still the ground-truth validator.
    """
    level = int(level)
    cfg = cfg or SimConfig(use_best_water=True)
    stats = player_stats_for_config(level, t, cfg)
    baseline = dict(baseline or {})
    total_s = float(baseline.get('total_s', 0.0) or 0.0)
    kill_s = float(baseline.get('kill_s', total_s) or 0.0)
    recovery_s = float(baseline.get('recovery_s', max(0.0, total_s - kill_s)) or 0.0)
    wand_s = float(baseline.get('casts_wand_expected_s', 0.0) or 0.0)
    spell_kill_s = max(0.0, kill_s - wand_s)

    modeled_damage = 0.0
    d_damage_sp = 0.0
    d_damage_int = 0.0
    cast_mix: dict[str, float] = {}
    for spell in SPELLS:
        count = float(baseline.get(f'casts_{spell}', 0.0) or 0.0)
        if count <= 1e-12:
            continue
        rank = _analytic_gradient_rank(spell, level)
        if rank is None:
            continue
        dmg, dsp, dint = _analytic_gradient_spell_terms(level, t, stats, cfg, rank)
        modeled_damage += count * dmg
        d_damage_sp += count * dsp
        d_damage_int += count * dint
        cast_mix[spell] = count

    # A route with no published cast mix should be rare.  Use the selected
    # policy's primary spell as a one-cast local basis rather than returning a
    # fake zero gradient.
    if modeled_damage <= 1e-12 and policy is not None:
        primary = str(getattr(policy, 'primary', '') or '')
        rank = _analytic_gradient_rank(primary, level)
        if rank is not None:
            modeled_damage, d_damage_sp, d_damage_int = _analytic_gradient_spell_terms(level, t, stats, cfg, rank)
            cast_mix[primary] = 1.0

    if modeled_damage > 1e-12:
        dkill_sp = -spell_kill_s * (d_damage_sp / modeled_damage)
        dkill_int_crit = -spell_kill_s * (d_damage_int / modeled_damage)
    else:
        dkill_sp = 0.0
        dkill_int_crit = 0.0

    # Continuous recovery derivative.  Drinking and passive Spirit regen add in
    # parallel in the existing recovery model, so dT/T = -dR/R is the natural
    # smooth local approximation.  In-combat OOM wand time gets the same Spirit
    # elasticity against passive regen only.
    spirit_mps = (12.5 + float(stats.spirit) / 4.0) / 2.0
    d_spirit_mps = 1.0 / 8.0
    water = latest_pair(WATER_USABLE if cfg.use_best_water else WATER_SELF, level)
    drink_mps = (float(water[1]) / float(water[2])) if water else 0.0
    total_recovery_rate = max(1e-12, drink_mps + spirit_mps)
    drecovery_spirit = -recovery_s * d_spirit_mps / total_recovery_rate
    dwind_spirit = -wand_s * d_spirit_mps / max(1e-12, spirit_mps)

    # Max-mana capacity is a threshold effect in the discrete kernel.  The
    # surrogate replaces that step with a bounded elasticity only when the
    # selected route actually spends time wanding for mana.  This keeps Int's
    # mana component continuous without inventing free value on non-OOM routes.
    d_mana_d_int = (1.0 if float(stats.intellect) < 20.0 else 15.0) * (1.0 + .02 * float(t.arcane_mind))
    dwind_int_capacity = -wand_s * d_mana_d_int / max(1.0, float(stats.max_mana))

    objective_gradient = {
        'intellect': dkill_int_crit + dwind_int_capacity,
        'spirit': drecovery_spirit + dwind_spirit,
        'spell_power': dkill_sp,
    }
    return {
        'method': 'analytic_continuous_gearing_surrogate_v1',
        'baseline_s_per_100': total_s,
        'reference_stat': 'spell_power',
        'objective_gradient': objective_gradient,
        'components': {
            'intellect': {
                'kill_time_via_spell_crit': dkill_int_crit,
                'oom_capacity': dwind_int_capacity,
                'dcrit_per_int': 1.0 / (100.0 * (14.77 + .65 * float(level))),
                'dmana_per_int': d_mana_d_int,
            },
            'spirit': {
                'drink_recovery': drecovery_spirit,
                'oom_regen': dwind_spirit,
                'dregen_mps_per_spirit': d_spirit_mps,
            },
            'spell_power': {
                'kill_time_via_damage': dkill_sp,
                'modeled_damage_per_100': modeled_damage,
                'dmodeled_damage_per_sp': d_damage_sp,
            },
        },
        'declared_stats': ('intellect', 'spirit', 'spell_power', 'stamina', 'armor', 'defense', 'shield_armor', 'block_value'),
        'stat_status': {
            'stamina': {
                'status': 'not_probeable',
                'reason': 'Player HP is modeled in event/MC combat, but the analytic expected scorer does not carry incoming HP loss through its local gearing gradient.',
            },
            'armor': {
                'status': 'not_probeable',
                'reason': 'Physical mitigation is modeled in event/MC combat, but the analytic expected scorer cannot publish a reliable local armor derivative.',
            },
            'defense': {
                'status': 'not_modeled',
                'reason': 'Mage leveling gear/combat has no Defense-skill linkage in the current Forever backend.',
            },
            'shield_armor': {'status': 'not_modeled', 'reason': 'Mage does not use shields.'},
            'block_value': {'status': 'not_modeled', 'reason': 'Mage does not use shield block.'},
        },
        'metadata': {
            'cast_mix': cast_mix,
            'spell_kill_s_per_100': spell_kill_s,
            'wand_wait_s_per_100': wand_s,
            'recovery_s_per_100': recovery_s,
            'modeled_damage_per_100': modeled_damage,
            'gradient_scope': 'fixed talents + selected policy local surrogate',
        },
        'note': (
            'Class-agnostic stat-weight framework; Mage backend supplies a smooth local '
            'surrogate gradient. Intellect includes closed-form crit value plus a bounded '
            'OOM-capacity term; Spirit uses continuous regen elasticity; Spell Power uses '
            'audited rank coefficients. Discrete/event scoring remains validation authority.'
        ),
    }
