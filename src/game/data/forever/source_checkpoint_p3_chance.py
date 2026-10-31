"""CombatRuntime chance sensitivity, independent of item source normalization.

Item raw-to-displayed-percent interpretation lives in
``source_checkpoint_p3_ratings``. TBC historical scaling is intentionally
not part of the active combat optimization path.
"""
from __future__ import annotations
from dataclasses import replace
from math import isfinite

def chance_perturbed_ir(ir, kind: str, fraction: float):
    """Perturb existing executor's *probability* axis, not an item rating.

    No per-class rules or spell identities. The caller measures resulting
    100-mob duration with the same build and persistent state.
    """
    if not 0. < float(fraction) <= .20 or not isfinite(float(fraction)):
        raise ValueError('chance perturbation must be finite and in (0,0.20]')
    if kind in {'crit', 'dodge'}:
        stat = {'crit':'melee_crit_chance','dodge':'dodge_chance'}[kind]
        values = dict(ir.actor.base_stats)
        values[stat] = float(values.get(stat, 0.) or 0.) + float(fraction)
        return replace(ir, actor=replace(ir.actor, base_stats=values))
    if kind == 'hit':
        # The executor's physical hit chance is the TARGET profile metadata,
        # not the per-AutoAttack.hit_chance (which is already 1.0).  Perturb
        # the same expected-value multiplier used by all source physical
        # melee damage, without rewriting the real pinned source database.
        original = ir.provenance.get('target_combat_profile')
        if not original or not 0.0 < float(original.get('melee_hit', 0)) <= 1.0:
            raise ValueError('no valid sourced target melee hit profile')
        profile = dict(original)
        profile['melee_hit'] = min(1.,float(profile['melee_hit']) + fraction)
        provenance = dict(ir.provenance)
        provenance['target_combat_profile'] = profile
        provenance['synthetic_hit_chance_sensitivity_delta'] = fraction
        return replace(ir, provenance=provenance)
    raise ValueError('unsupported executor chance axis')


def context_weapon_speed_semantics(ir):
    """Return sourced speed semantics: zero only if every weapon mode form-fixed."""
    from src.game.gear import _weapon_facts_for_ir
    facts = _weapon_facts_for_ir(ir)
    if not facts:
        return 'NO_SOURCE_AUTHORIZED_WEAPON_SPEED'
    modes={fact.weapon_speed_semantics for fact, _ in facts}
    if modes == {'form_fixed'}:
        return 'FORM_FIXED_WEAPON_SPEED_NO_ITEM_SENSITIVITY'
    if modes == {'equipped'}:
        return 'EQUIPPED_SPEED_REQUIRES_EXECUTOR_SENSITIVITY'
    return 'MIXED_OR_UNVERIFIED_SPEED_SEMANTICS'
