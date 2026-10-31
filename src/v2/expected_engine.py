from __future__ import annotations

"""Small deterministic combat scorer for the v2 optimizer.

Design goal: enumerate only state that changes decisions (cooldowns/cadence),
reduce ordinary RNG (damage range, hit/resist, crit) to expectations, and leave
v1 as the stochastic validation oracle.

This is deliberately a search model, not a second server emulator.  It keeps
cast/GCD/kill boundaries discrete, because replacing combat with continuous DPS
would destroy important breakpoints.
"""

from dataclasses import dataclass, field, replace
from functools import lru_cache
import math
from typing import Dict, Iterable, Optional, Tuple

from src.engine_registry import eng
from src.rulesets.forever.classes.mage.resources import (
    best_mage_water, mana_gem_tier, ooc_mana_regen_per_s,
)
from src.rulesets.forever.shared.recovery import solve_recovery, RECOVERY_SOLVER_ID
from src.shared.leveling.timing import between_pull_travel_s

EPS = 1e-9


@dataclass(frozen=True)
class CooldownState:
    """Cooldown state at pull start, in seconds until ready.

    Keeping this explicit is intentional: a future finite-state / semi-Markov
    solver can enumerate states and build a transition matrix directly from
    ``simulate_fight_expected`` outcomes.
    """

    fire_blast: float = 0.0
    nova: float = 0.0
    blink: float = 0.0
    combustion: float = 0.0
    ice_barrier: float = 0.0
    ice_barrier_absorb: float = 0.0
    ice_barrier_duration: float = 0.0

    def tick(self, seconds: float) -> "CooldownState":
        dt = max(0.0, float(seconds))
        duration=max(0.0,self.ice_barrier_duration-dt)
        absorb=max(0.0,self.ice_barrier_absorb) if duration>EPS else 0.0
        return CooldownState(
            max(0.0, self.fire_blast - dt),
            max(0.0, self.nova - dt),
            max(0.0, self.blink - dt),
            max(0.0, self.combustion - dt),
            max(0.0, self.ice_barrier - dt),
            absorb,
            duration,
        )

    def ready_mask(self) -> Tuple[bool, bool, bool, bool]:
        return tuple(x <= EPS for x in (self.fire_blast, self.nova, self.blink, self.combustion))  # type: ignore[return-value]


@dataclass
class ExpectedDot:
    kind: str
    next_tick: float
    interval: float
    remaining: int
    damage: float


@dataclass
class ExpectedProjectile:
    """Expected-value projectile with cast-completion snapshot semantics.

    Damage/crit expectation is frozen when the cast completes, matching the
    stochastic oracle.  Control/debuff side effects occur at impact, allowing
    a previous Frostbolt to proc Frostbite while the next Frostbolt is already
    being cast (the key Shatter pipeline interaction).
    """
    impact: float
    rank: eng.Rank
    comp: dict


@dataclass
class ExpectedState:
    t: float
    hp: float
    mana: float
    max_mana: float
    distance: float
    engaged: bool = False
    in_melee: bool = False
    next_swing: float = math.inf
    last_mana_spend: float = -1e9
    slow_until: float = -1e9
    slow_frac: float = 0.0
    # Expected debuff state.  These are continuous expected values, not RNG rolls.
    scorch_stacks: float = 0.0
    scorch_until: float = -1e9
    wc_stacks: float = 0.0
    wc_until: float = -1e9
    root_until: float = -1e9
    root_probability: float = 0.0
    # Expected Fingers of Frost resource.  This is deliberately continuous: the
    # event backend remains authority for proc timing, while the deterministic
    # scorer only needs enough signal to value Ice Lance talent paths.
    fingers_of_frost_charges: float = 0.0
    fingers_of_frost_until: float = -1e9
    stun_until: float = -1e9
    stun_probability: float = 0.0
    # Probability that Clearcasting is active before the next mana-spending spell.
    # v2 treats this as an expectation, not a branch.
    clearcast_probability: float = 0.0
    # Long-run analytical Combustion contribution expressed as an additive
    # Fire crit probability.  The analytic steady-state wrapper solves this.
    combustion_extra_crit: float = 0.0
    fire_cycle_pos: int = 0
    pyro_opener_used: bool = False
    arcane_blast_stacks: int = 0
    arcane_blast_until: float = -1e9
    # I12: expected Missile Barrage state. Probability is carried explicitly
    # instead of pretending the structural scorer has deterministic proc timing.
    missile_barrage_probability: float = 0.0
    missile_barrage_until: float = -1e9
    # I13: continuous expected Hot Streak stack occupancy. Exact proc timing
    # remains the event backend authority.
    hot_streak_stacks: float = 0.0
    hot_streak_until: float = -1e9
    cooldowns: CooldownState = field(default_factory=CooldownState)
    dots: list[ExpectedDot] = field(default_factory=list)
    ice_barrier_absorb: float = 0.0
    ice_barrier_until: float = -1e9
    projectiles: list[ExpectedProjectile] = field(default_factory=list)
    wand_finisher_committed: bool = False
    # Structural-screen player-health carry.  This mirrors the stochastic
    # backend's generic incoming-melee proxy closely enough to prevent weak
    # control candidates from receiving free HP between pulls.
    expected_unabsorbed_swings: float = 0.0
    expected_incoming_swings: float = 0.0
    hp_barrier_absorb: float = 0.0
    hp_barrier_until: float = -1e9
    expected_melee_contact_s: float = 0.0
    expected_pushback_s: float = 0.0


@dataclass
class FightOutcome:
    kill_s: float
    recovery_s: float
    total_s: float
    mana_spent: float
    mana_left: float
    end_cooldowns: CooldownState
    casts: Dict[str, float]
    mob_level: int
    active_dps: float
    hp_missing: float = 0.0
    unabsorbed_swings: float = 0.0
    melee_contact_s: float = 0.0
    pushback_s: float = 0.0
    approximation_flags: Tuple[str, ...] = ()


@lru_cache(maxsize=4096)
def _expected_resist_scalar(level: int, mob_level: int, school: str, binary: bool,
                            arcane_subtlety: int, magic_res: float, fire_res: float,
                            frost_res: float, arcane_res: float) -> float:
    specific = {"fire": fire_res, "frost": frost_res, "arcane": arcane_res}.get(school, 0.0)
    raw_res = specific if specific else magic_res
    resist = max(0.0, float(raw_res) - 5.0 * int(arcane_subtlety))
    skill = max(float(level) * 5.0, 100.0)
    pct = 0.75 * (resist / skill)
    if not binary:
        pct += 0.004 * max(float(mob_level) * 5.0 - skill, 0.0)
    pct = max(0.0, min(0.75, pct))
    if binary:
        return 1.0 - pct
    chances = eng._partial_resist_chances(pct)
    expected_resist = sum((0.25 * i) * (c / 10000.0) for i, c in enumerate(chances))
    return 1.0 - expected_resist


def _expected_resist_multiplier(level: int, mob_level: int, rank: eng.Rank,
                                talents: eng.Talents, cfg: eng.SimConfig) -> float:
    return _expected_resist_scalar(
        int(level), int(mob_level), str(rank.school),
        rank.spell in getattr(eng, "_BINARY_DAMAGE_SPELLS", ()),
        int(talents.arcane_subtlety),
        float(getattr(cfg, "mob_magic_resistance", 0.0) or 0.0),
        float(getattr(cfg, "mob_fire_resistance", 0.0) or 0.0),
        float(getattr(cfg, "mob_frost_resistance", 0.0) or 0.0),
        float(getattr(cfg, "mob_arcane_resistance", 0.0) or 0.0),
    )


def _direct_mod(rank: eng.Rank, talents: eng.Talents, state: ExpectedState) -> float:
    m = 1.0
    if rank.school == "frost":
        m *= 1.0 + 0.02 * talents.piercing_ice
    if rank.school == "fire":
        m *= 1.0 + 0.02 * talents.fire_power
        if state.scorch_stacks > EPS and state.t < state.scorch_until:
            m *= 1.0 + 0.03 * state.scorch_stacks
    if rank.spell != "arcane_blast" and state.arcane_blast_stacks and state.t < state.arcane_blast_until:
        m *= 1.0 + eng.wh.ARCANE_BLAST_OTHER_SPELL_DAMAGE_BONUS_PER_STACK * state.arcane_blast_stacks
    m *= 1.0 + 0.01 * talents.arcane_instability
    return m


def _expected_crit_chance(rank: eng.Rank, talents: eng.Talents, state: ExpectedState,
                          stats: eng.Stats) -> float:
    c = stats.spell_crit
    if rank.school == "frost":
        if state.t < state.wc_until:
            c += 0.02 * state.wc_stacks
        # Shatter is weighted by expected root occupancy rather than a sampled root.
        c += (eng.shatter_crit_bonus(talents) if hasattr(eng,'shatter_crit_bonus') else .10*talents.shatter) * max(0.0, min(1.0, state.root_probability))
    if rank.spell in ("scorch", "fire_blast", "ice_lance", "arcane_blast"):
        c += 0.02 * getattr(talents, "incinerate", 0)
    if rank.school == "arcane":
        c += 0.02 * getattr(talents, "arcane_impact", 0)
    if rank.school == "fire":
        c += 0.02 * talents.critical_mass
        c += max(0.0, state.combustion_extra_crit)
    return max(0.0, min(0.99, c))


@lru_cache(maxsize=4096)
def _spell_hit_scalar(level: int, mob_level: int, school: str,
                      elemental_precision: int, arcane_focus: int) -> float:
    diff = int(mob_level) - int(level)
    miss = 4.0 + (diff if diff <= 2 else 2 + 11 * (diff - 2))
    if school in ("frost", "fire"):
        miss -= 2.0 * int(elemental_precision)
    if school == "arcane":
        miss -= 2.0 * int(arcane_focus)
    return 1.0 - max(0.01, min(1.0, miss / 100.0))



def _spell_power_direct_coeff(rank, cfg) -> float:
    """Call the active engine without assuming Forever-only config fields."""
    profile = getattr(cfg, "server_profile", None)
    if profile is not None:
        try:
            return float(eng.spell_power_direct_coeff(rank, profile))
        except TypeError:
            pass
    return float(eng.spell_power_direct_coeff(rank))

def expected_direct_components(level: int, mob_level: int, rank: eng.Rank,
                               talents: eng.Talents, stats: eng.Stats,
                               cfg: eng.SimConfig, state: ExpectedState) -> dict:
    """Expected direct damage and expected on-crit mana refund for one cast."""
    hit = eng.spell_hit(level, mob_level, rank.school, talents)
    resist = _expected_resist_multiplier(level, mob_level, rank, talents, cfg)
    base = (0.5 * (rank.dmin + rank.dmax) + stats.spell_power * _spell_power_direct_coeff(rank, cfg)) * _direct_mod(rank, talents, state)
    if rank.spell == 'ice_lance':
        root_p = max(0.0, min(1.0, state.root_probability if state.t < state.root_until else 0.0))
        fof_p = max(0.0, min(1.0, state.fingers_of_frost_charges if state.t < state.fingers_of_frost_until else 0.0))
        frozen_p = 1.0 - (1.0-root_p)*(1.0-fof_p)
        mult = float(eng.ice_lance_frozen_multiplier(getattr(cfg,'server_profile',None)))
        base *= 1.0 + frozen_p * (mult - 1.0)
    crit_p = _expected_crit_chance(rank, talents, state, stats)
    cm = eng.crit_mult(rank, talents)
    noncrit = base * resist
    expected_damage = hit * noncrit * (1.0 + crit_p * (cm - 1.0))
    expected_crit_damage = hit * crit_p * noncrit * cm
    refund = 0.0
    if rank.school in ("fire", "frost") and talents.master_elements:
        refund = hit * crit_p * rank.mana * 0.10 * talents.master_elements
    return {
        "hit": hit,
        "resist": resist,
        "crit_p": crit_p,
        "damage": max(0.0, expected_damage),
        "expected_crit_damage": max(0.0, expected_crit_damage),
        "mana_refund": max(0.0, refund),
    }


def _mana_regen_rate(level: int, talents: eng.Talents, stats: eng.Stats,
                     cfg: eng.SimConfig, inside_5sr: bool) -> float:
    mps = (12.5 + stats.spirit / 4.0) / 2.0
    return mps * (eng.regen_fraction_in_5sr(level, talents, cfg) if inside_5sr else 1.0)


def _advance(state: ExpectedState, dt: float, level: int, talents: eng.Talents,
             stats: eng.Stats, cfg: eng.SimConfig, mob: eng.Mob, casts: Dict[str, float]) -> None:
    """Advance deterministic time with a bounded event sweep.

    The older implementation repeatedly chose the next floating-point boundary
    (slow/root/stun expiry or DoT tick) from a ``while remaining`` loop.  Around
    smooth HP perturbations, nearly-coincident boundaries could reduce the
    progress step to epsilon-sized increments and make one otherwise trivial
    analytical score take minutes.  Here the finite event set is materialized
    once and swept in chronological order, so work is O(number of status
    expiries + DoT ticks) and cannot spin on a numerical boundary.
    """
    dt = max(0.0, float(dt))
    if dt <= EPS or state.hp <= EPS:
        return

    start_t = float(state.t)
    end_t = start_t + dt

    # Build the finite set of times at which movement/status/damage semantics
    # may change during this advance.  Status expiries contribute at most three
    # boundaries; each active DoT contributes only its remaining finite ticks.
    events = {end_t}
    for when in (state.slow_until, state.root_until, state.stun_until):
        if start_t + EPS < when < end_t - EPS:
            events.add(float(when))
    for d in state.dots:
        tick = float(d.next_tick)
        for _ in range(max(0, int(d.remaining))):
            if tick > end_t + EPS:
                break
            if tick > start_t + EPS:
                events.add(min(tick, end_t))
            tick += float(d.interval)
    for proj in state.projectiles:
        if start_t + EPS < proj.impact <= end_t + EPS:
            events.add(min(float(proj.impact), end_t))

    def advance_segment(seg_end: float) -> None:
        if state.hp <= EPS:
            return
        seg_start = float(state.t)
        step = max(0.0, float(seg_end) - seg_start)
        if step <= EPS:
            state.t = max(state.t, float(seg_end))
            return

        # Spirit regeneration integrated across the exact 5SR boundary.
        boundary = state.last_mana_spend + 5.0
        if seg_start < boundary < seg_end:
            a = boundary - seg_start
            gain = _mana_regen_rate(level, talents, stats, cfg, True) * a
            gain += _mana_regen_rate(level, talents, stats, cfg, False) * (step - a)
        else:
            gain = _mana_regen_rate(level, talents, stats, cfg, seg_end <= boundary) * step
        state.mana = min(state.max_mana, state.mana + gain)

        # Status probabilities are constant inside each segment because every
        # expiry is present in ``events``.
        was_in_melee = bool(state.in_melee)
        contact_time_in_segment = None
        if state.engaged and not state.in_melee:
            rooted_fraction = (max(0.0, min(1.0, state.root_probability))
                               if seg_start < state.root_until - EPS else 0.0)
            stunned_fraction = (max(0.0, min(1.0, state.stun_probability))
                                if seg_start < state.stun_until - EPS else 0.0)
            immobilized = 1.0 - (1.0-rooted_fraction) * (1.0-stunned_fraction)
            slowed = seg_start < state.slow_until - EPS
            speed = mob.run_speed * ((1.0-state.slow_frac) if slowed else 1.0)
            effective_speed = max(0.0, speed * (1.0-immobilized))
            if effective_speed > EPS:
                gap=max(0.0,state.distance-mob.melee_reach)
                t_contact=gap/effective_speed
                if t_contact <= step + EPS:
                    contact_time=seg_start+min(step,max(0.0,t_contact))
                    contact_time_in_segment=contact_time
                    state.distance=mob.melee_reach
                    state.in_melee=True
                    # Event backend swings immediately on first contact.
                    state.next_swing=contact_time
                else:
                    state.distance=max(mob.melee_reach,state.distance-effective_speed*step)

        if was_in_melee:
            state.expected_melee_contact_s += step
        elif contact_time_in_segment is not None:
            state.expected_melee_contact_s += max(0.0, float(seg_end) - float(contact_time_in_segment))

        # Deterministic incoming-melee schedule for structural HP carry.  A full
        # expected stun suppresses swings without advancing the timer, matching
        # the event backend's immediate swing when the stun ends. Fractional
        # expected stuns weight the swing probability.
        if state.in_melee and math.isfinite(state.next_swing):
            stun_p=(max(0.0,min(1.0,state.stun_probability))
                    if seg_start < state.stun_until-EPS else 0.0)
            if stun_p < 1.0-EPS:
                while max(state.next_swing,seg_start) <= seg_end + EPS:
                    swing_time=max(state.next_swing,seg_start)
                    live_stun=(max(0.0,min(1.0,state.stun_probability))
                               if swing_time < state.stun_until-EPS else 0.0)
                    _record_expected_player_swing(state,1.0-live_stun,swing_time,mob,cfg)
                    state.next_swing=swing_time+max(EPS,mob.swing)

        state.t = float(seg_end)

    for when in sorted(events):
        if state.hp <= EPS:
            break
        advance_segment(when)

        # Projectile impacts happen at their real event time, before the next
        # cast decision.  This is essential for Frostbolt travel-time
        # pipelining: an in-flight bolt may proc Frostbite during the following
        # cast and therefore enable Shatter at that cast's completion.
        due=[p for p in state.projectiles if p.impact <= state.t + EPS]
        for proj in due:
            state.projectiles.remove(proj)
            _resolve_expected_projectile(state,proj,level,talents,stats,cfg,mob,casts)
            if state.hp <= EPS:
                break

        # Resolve all ticks due at this exact boundary.  Each DoT has a finite
        # remaining count, so these loops are intrinsically bounded.
        for d in list(state.dots):
            while d.remaining > 0 and d.next_tick <= state.t + EPS and state.hp > EPS:
                state.hp = max(0.0, state.hp-d.damage)
                d.remaining -= 1
                d.next_tick += d.interval
            if d.remaining <= 0:
                state.dots.remove(d)

        if state.scorch_until <= state.t + EPS:
            state.scorch_stacks = 0.0
        if state.wc_until <= state.t + EPS:
            state.wc_stacks = 0.0
        if state.root_until <= state.t + EPS:
            state.root_probability = 0.0
        if state.stun_until <= state.t + EPS:
            state.stun_probability = 0.0


def _expected_break_root(state: ExpectedState, damage: float, mob: eng.Mob, school: str, cfg: eng.SimConfig) -> None:
    if state.t >= state.root_until or state.root_probability <= EPS or damage <= 0:
        return
    if cfg.root_break_mode == 'never': return
    if cfg.root_break_mode == 'first':
        state.root_probability=0.0; state.root_until=-1e9; return
    frac=damage/max(1.0,mob.hp)
    p=cfg.root_break_base+cfg.root_break_damage_scale*frac+(cfg.root_break_fire_bonus if school=='fire' else 0.0)
    p=min(.98,max(.05,p))
    state.root_probability*=1.0-p
    if state.root_probability<=1e-6:
        state.root_probability=0.0; state.root_until=-1e9


def _apply_expected_impact(state: ExpectedState, talents: eng.Talents, landed_probability: float) -> None:
    if talents.impact<=0: return
    impact_p=(eng.impact_proc_chance(talents) if hasattr(eng,'impact_proc_chance') else .02*talents.impact)
    p=max(0.0,min(1.0,float(landed_probability)*impact_p))
    state.stun_probability=1.0-(1.0-state.stun_probability)*(1.0-p)
    state.stun_until=max(state.stun_until,state.t+2.0)


def _expected_contact_and_swings_during_interval(state: ExpectedState, dt: float,
                                                   mob: eng.Mob) -> tuple[float, float]:
    """Expected contact-seconds and incoming swings during a stationary interval.

    The event backend can enter melee *during* a hard cast and swings immediately
    on first contact.  The old deterministic screen only priced pushback when the
    cast started in melee, systematically under-valuing control.  Keep this as a
    bounded expectation rather than branching the structural scorer.
    """
    dt=max(0.0,float(dt))
    if dt<=EPS or not state.engaged:
        return 0.0, 0.0
    active_stun=(max(0.0,min(1.0,state.stun_probability))
                 if state.t < state.stun_until-EPS else 0.0)
    if state.in_melee:
        live=max(0.0,1.0-active_stun)
        contact=dt*live
        return contact, contact/max(EPS,mob.swing)

    root_p=(max(0.0,min(1.0,state.root_probability))
            if state.t < state.root_until-EPS else 0.0)
    immobilized=1.0-(1.0-root_p)*(1.0-active_stun)
    mobile_p=max(0.0,1.0-immobilized)
    if mobile_p<=EPS:
        return 0.0,0.0
    slowed=state.t < state.slow_until-EPS
    speed=mob.run_speed*((1.0-state.slow_frac) if slowed else 1.0)
    if speed<=EPS:
        return 0.0,0.0
    gap=max(0.0,state.distance-mob.melee_reach)
    t_contact=gap/speed
    if t_contact>dt+EPS:
        return 0.0,0.0
    contact_window=max(0.0,dt-t_contact)
    expected_contact=mobile_p*contact_window
    # Event semantics schedule a swing at the instant first contact is made,
    # then one per mob.swing. Weight that first swing by the mobile branch.
    expected_swings=mobile_p + expected_contact/max(EPS,mob.swing)
    return expected_contact,expected_swings


def _expected_pushback_s(cast_s: float, state: ExpectedState, mob: eng.Mob,
                         talents: eng.Talents, rank: eng.Rank, cfg: eng.SimConfig) -> float:
    """Expected pushback, including contact that begins during this cast."""
    if cast_s <= EPS:
        return 0.0
    _contact_s,swings=_expected_contact_and_swings_during_interval(state,cast_s,mob)
    protected=_consume_expected_barrier_swings(state,swings,mob,cfg)
    swings=max(0.0,swings-protected)
    mean_push = 0.6  # mean of the early Classic pushback sequence
    resist = ((eng.burning_soul_protection(talents) if hasattr(eng,'burning_soul_protection') else .35*talents.burning_soul) if rank.school == "fire" else 0.0)
    return min(3.0, swings * mean_push * (1.0 - resist))


def _clearcast_discount_and_consume(state: ExpectedState, nominal_cost: float) -> float:
    """Expected mana cost of the next spell under Clearcasting.

    The stochastic v1 policy normally does not change on Clearcasting; it only
    zeroes the next spell cost.  Therefore the sufficient state is simply the
    probability that CC is active before this cast.
    """
    p=max(0.0,min(1.0,state.clearcast_probability))
    state.clearcast_probability=0.0
    return max(0.0, nominal_cost) * (1.0-p)


def _set_clearcast_after_landed_spell(state: ExpectedState, talents: eng.Talents,
                                       landed_probability: float) -> None:
    proc=0.02*max(0.0,float(talents.arcane_concentration))
    state.clearcast_probability=max(0.0,min(1.0,float(landed_probability)*proc))


def _spend(state: ExpectedState, amount: float) -> bool:
    amount = max(0.0, amount)
    if state.mana + EPS < amount:
        return False
    if amount > EPS:
        state.mana -= amount
        state.last_mana_spend = state.t
    return True


def _record_expected_player_swing(state: ExpectedState, weight: float, swing_time: float,
                                  mob: eng.Mob, cfg: eng.SimConfig) -> None:
    """Record expected incoming melee for HP-carry scoring.

    Keep a separate Barrier mirror from the pushback approximation so player
    health accounting cannot double-consume the same absorb state.  The event
    backend remains authority; this is only the deterministic structural screen.
    """
    w=max(0.0,min(1.0,float(weight)))
    if w<=EPS:
        return
    state.expected_incoming_swings += w
    protected=0.0
    if state.hp_barrier_absorb>EPS and swing_time+EPS<state.hp_barrier_until:
        hit=max(EPS,eng.generic_melee_hit_damage(mob,cfg))
        protected=min(w,state.hp_barrier_absorb/hit)
        state.hp_barrier_absorb=max(0.0,state.hp_barrier_absorb-w*hit)
    elif swing_time+EPS>=state.hp_barrier_until:
        state.hp_barrier_absorb=0.0
    state.expected_unabsorbed_swings += max(0.0,w-protected)


def _consume_expected_barrier_swings(state: ExpectedState, swings: float,
                                     mob: eng.Mob, cfg: eng.SimConfig) -> float:
    swings=max(0.0,float(swings))
    if swings<=EPS or state.ice_barrier_absorb<=EPS or state.t+EPS>=state.ice_barrier_until:
        state.ice_barrier_absorb=0.0
        return 0.0
    hit=max(EPS,eng.generic_melee_hit_damage(mob,cfg))
    protected=min(swings,state.ice_barrier_absorb/hit)
    state.ice_barrier_absorb=max(0.0,state.ice_barrier_absorb-swings*hit)
    return protected


def _maybe_cast_ice_barrier(state: ExpectedState, level: int, talents: eng.Talents,
                            stats: eng.Stats, cfg: eng.SimConfig, mob: eng.Mob,
                            casts: Dict[str, float]) -> bool:
    if not talents.ice_barrier or state.cooldowns.ice_barrier>EPS:
        return False
    rank=eng.ice_barrier_rank(level)
    if rank is None:
        return False
    cost=eng.ice_barrier_mana_cost(level,talents)
    if not _spend(state,cost):
        return False
    state.ice_barrier_absorb=float(rank.absorb)
    state.ice_barrier_until=state.t+60.0
    state.hp_barrier_absorb=float(rank.absorb)
    state.hp_barrier_until=state.t+60.0
    state.cooldowns=replace(state.cooldowns,ice_barrier=30.0,
                            ice_barrier_absorb=float(rank.absorb),ice_barrier_duration=60.0)
    casts['ice_barrier']=casts.get('ice_barrier',0.0)+1.0
    _advance(state,eng.GCD,level,talents,stats,cfg,mob,casts)
    state.cooldowns=state.cooldowns.tick(eng.GCD)
    return True


def _active_hot_streak_stacks(state: ExpectedState) -> float:
    if state.t + EPS >= state.hot_streak_until:
        state.hot_streak_stacks = 0.0
        return 0.0
    return max(0.0, float(state.hot_streak_stacks))


def _grant_expected_hot_streak(state: ExpectedState, talents: eng.Talents, rank: eng.Rank, comp: dict) -> None:
    effect = eng._hot_streak_effect(talents) if hasattr(eng, "_hot_streak_effect") else None
    if effect is None:
        return
    triggers = set(effect.metadata.get("trigger_spells") or ())
    if rank.spell not in triggers:
        return
    max_stacks = float(effect.metadata.get("max_stacks", 3))
    duration = float(effect.metadata.get("duration_s", 15.0))
    # One qualifying landed critical grants one stack. Structural scoring carries
    # the expectation; event simulation owns discrete streak timing.
    expected_crit = max(0.0, min(1.0, float(comp.get("hit", 0.0)) * float(comp.get("crit_p", 0.0))))
    if expected_crit <= EPS:
        return
    state.hot_streak_stacks = min(max_stacks, _active_hot_streak_stacks(state) + expected_crit)
    state.hot_streak_until = state.t + duration


def _apply_expected_direct_impact(state: ExpectedState, rank: eng.Rank, comp: dict,
                                  level: int, talents: eng.Talents, stats: eng.Stats,
                                  cfg: eng.SimConfig, mob: eng.Mob, casts: Dict[str, float]) -> None:
    """Apply impact-time side effects for a direct spell expectation."""
    state.engaged = True
    was_rooted=state.t < state.root_until and state.root_probability>EPS
    state.hp = max(0.0, state.hp - comp["damage"])
    if was_rooted:
        _expected_break_root(state,comp["damage"],mob,rank.school,cfg)
    if rank.school=='fire':
        _apply_expected_impact(state,talents,comp["hit"])
    _grant_expected_hot_streak(state, talents, rank, comp)

    # Attached spell DoTs and Ignite begin at impact, matching the stochastic
    # event ordering instead of cast completion.
    if rank.spell in ("fireball", "pyroblast") and rank.dot_total > 0 and state.hp > EPS:
        state.dots[:] = [d for d in state.dots if d.kind != rank.spell]
        interval = max(EPS, rank.dot_interval)
        ticks = max(1, int(round(rank.dot_duration / interval)))
        dot_total = (rank.dot_total + stats.spell_power * eng.spell_power_dot_coeff(rank)) * _direct_mod(rank, talents, state) * eng.resistance_damage_multiplier(
            level, talents, cfg, "fire", mob.level
        ) * comp["hit"]
        wh = getattr(eng, 'wh', None)
        periodic_can_crit = getattr(wh, 'PERIODIC_CAN_CRIT_SPELLS', ()) if wh is not None else ()
        if rank.spell in periodic_can_crit:
            dot_crit=_expected_crit_chance(rank,talents,state,stats)
            dot_total*=1.0 + dot_crit * (eng.crit_mult(rank,talents)-1.0)
        state.dots.append(ExpectedDot(rank.spell, state.t + interval, interval, ticks, dot_total / ticks))
    if rank.school == "fire" and talents.ignite and comp["expected_crit_damage"] > EPS and state.hp > EPS:
        ignite_total = 0.08 * talents.ignite * comp["expected_crit_damage"]
        state.dots[:] = [d for d in state.dots if d.kind != "ignite"]
        state.dots.append(ExpectedDot("ignite", state.t + 2.0, 2.0, 2, ignite_total / 2.0))

    if rank.spell == "frostbolt" and state.hp > EPS:
        state.slow_frac = (0.40 + [0.0, 0.04, 0.07, 0.10][talents.permafrost]) * comp["hit"]
        state.slow_until = state.t + rank.slow_duration + talents.permafrost
        if talents.winters_chill:
            state.wc_stacks = min(5.0, state.wc_stacks + comp["hit"] * 0.20 * talents.winters_chill)
            state.wc_until = state.t + 15.0
        if talents.frostbite:
            p = comp["hit"] * 0.05 * talents.frostbite
            state.root_probability = 1.0 - (1.0 - state.root_probability) * (1.0 - p)
            state.root_until = max(state.root_until, state.t + 5.0)
        if getattr(talents,'fingers_of_frost',0):
            proc = float(getattr(eng.wh,'FINGERS_OF_FROST_CHILL_PROC_CHANCE',0.15)) * float(comp['hit'])
            charges = float(getattr(getattr(cfg,'server_profile',None),'fingers_of_frost_charges',2))
            state.fingers_of_frost_charges = min(charges, state.fingers_of_frost_charges + proc*charges)
            state.fingers_of_frost_until = max(state.fingers_of_frost_until, state.t + float(getattr(eng.wh,'FINGERS_OF_FROST_DURATION_S',15.0)))

    if rank.spell == "scorch" and talents.imp_scorch and state.hp > EPS:
        proc = (1.0 / 3.0, 2.0 / 3.0, 1.0)[talents.imp_scorch - 1]
        state.scorch_stacks = min(5.0, state.scorch_stacks + comp["hit"] * proc)
        state.scorch_until = state.t + 30.0


def _resolve_expected_projectile(state: ExpectedState, proj: ExpectedProjectile,
                                 level: int, talents: eng.Talents, stats: eng.Stats,
                                 cfg: eng.SimConfig, mob: eng.Mob, casts: Dict[str, float]) -> None:
    _apply_expected_direct_impact(state,proj.rank,proj.comp,level,talents,stats,cfg,mob,casts)
    # In v1 Clearcasting from missile spells procs when the projectile lands.
    _set_clearcast_after_landed_spell(state,talents,proj.comp["hit"])


def _arcane_blast_nominal_cost(state: ExpectedState, stats: eng.Stats) -> float:
    stacks = state.arcane_blast_stacks if state.t < state.arcane_blast_until else 0
    return stats.base_mana * eng.wh.ARCANE_BLAST_BASE_MANA_PCT * (
        1.0 + eng.wh.ARCANE_BLAST_MANA_COST_INCREASE_PER_STACK * stacks
    )


def _consume_arcane_blast_buff(state: ExpectedState) -> int:
    stacks = state.arcane_blast_stacks if state.t < state.arcane_blast_until else 0
    state.arcane_blast_stacks = 0
    state.arcane_blast_until = -1e9
    return int(stacks)


def _cast_direct(state: ExpectedState, rank: eng.Rank, level: int, talents: eng.Talents,
                 stats: eng.Stats, cfg: eng.SimConfig, mob: eng.Mob,
                 casts: Dict[str, float]) -> bool:
    nominal_cost = (_arcane_blast_nominal_cost(state, stats)
                    if rank.spell == "arcane_blast" else eng.mana_cost(rank, talents, stats))
    cost = _clearcast_discount_and_consume(state, nominal_cost)
    # v1 checks affordability before beginning the cast, but the mana spend and
    # 5SR timestamp happen only if the cast actually completes.  This matters
    # once projectiles are pipelined: a previous bolt can kill the mob while the
    # next cast is still in progress.
    if state.mana + EPS < cost:
        return False
    cast_s = rank.cast
    if rank.spell == "frostbolt":
        cast_s = max(0.5, cast_s - 0.1 * talents.imp_frostbolt)
    elif rank.spell == "fireball":
        cast_s = max(0.5, cast_s - 0.1 * talents.imp_fireball)
    elif rank.spell == "pyroblast" and getattr(talents, "hot_streak", 0):
        hs = eng._hot_streak_effect(talents) if hasattr(eng, "_hot_streak_effect") else None
        stacks = _active_hot_streak_stacks(state)
        if hs is not None and stacks > EPS:
            cast_s = max(eng.GCD, cast_s * (1.0 - float(hs.base_value or 0.0) * stacks))
    expected_pushback = _expected_pushback_s(cast_s, state, mob, talents, rank, cfg)
    state.expected_pushback_s += expected_pushback
    cast_s += expected_pushback
    cast_start=state.t
    contact_probe=replace(state)
    contact_before=state.expected_melee_contact_s
    swings_before=state.expected_incoming_swings
    _advance(state, cast_s, level, talents, stats, cfg, mob, casts)
    elapsed=max(0.0,state.t-cast_start)
    target_contact,target_swings=_expected_contact_and_swings_during_interval(contact_probe,elapsed,mob)
    observed_contact=max(0.0,state.expected_melee_contact_s-contact_before)
    state.expected_melee_contact_s += max(0.0,target_contact-observed_contact)
    observed_swings=max(0.0,state.expected_incoming_swings-swings_before)
    residual_swings=max(0.0,target_swings-observed_swings)
    while residual_swings>EPS:
        w=min(1.0,residual_swings)
        _record_expected_player_swing(state,w,state.t,mob,cfg)
        residual_swings-=w
    state.cooldowns=state.cooldowns.tick(elapsed)
    if state.hp <= EPS:
        return True
    if not _spend(state, cost):
        # Affordability was checked at cast start; only pathological floating
        # point drift could make this fail after in-cast regeneration.
        return False

    # Snapshot hit/damage/crit expectation at cast completion.  Missile impacts
    # are queued instead of blocking the next cast for their travel time.
    comp = expected_direct_components(level, mob.level, rank, talents, stats, cfg, state)
    state.mana = min(state.max_mana, state.mana + comp["mana_refund"])
    casts[rank.spell] = casts.get(rank.spell, 0.0) + 1.0

    if rank.missile_speed > 0:
        travel = max(5.0, state.distance) / rank.missile_speed
        state.projectiles.append(ExpectedProjectile(state.t + travel, rank, comp))
        # Hostile projectile does not make the mob move until impact in the v1
        # model, so engaged remains false until the first missile lands.
        return True

    _set_clearcast_after_landed_spell(state, talents, comp["hit"])
    _apply_expected_direct_impact(state,rank,comp,level,talents,stats,cfg,mob,casts)
    if rank.spell == "arcane_blast":
        old = state.arcane_blast_stacks if state.t < state.arcane_blast_until else 0
        state.arcane_blast_stacks = min(eng.wh.ARCANE_BLAST_MAX_STACKS, old + 1)
        state.arcane_blast_until = state.t + eng.wh.ARCANE_BLAST_STACK_DURATION_S
        if getattr(talents, "missile_barrage", 0):
            # AB has a source-backed 40% MB proc chance. The structural engine
            # carries expected occupancy; event simulation remains timing authority.
            active = state.missile_barrage_probability if state.t < state.missile_barrage_until else 0.0
            trigger = comp["hit"] * eng.wh.MISSILE_BARRAGE_ARCANE_BLAST_PROC_CHANCE
            state.missile_barrage_probability = 1.0 - (1.0-active) * (1.0-trigger)
            state.missile_barrage_until = state.t + eng.wh.MISSILE_BARRAGE_DURATION_S
    elif state.arcane_blast_stacks:
        _consume_arcane_blast_buff(state)
    if rank.spell == "pyroblast" and getattr(talents, "hot_streak", 0) and _active_hot_streak_stacks(state) > EPS:
        state.hot_streak_stacks = 0.0
        state.hot_streak_until = -1e9
    return True

def _cast_fire_blast(state: ExpectedState, rank: eng.Rank, level: int, talents: eng.Talents,
                     stats: eng.Stats, cfg: eng.SimConfig, mob: eng.Mob,
                     casts: Dict[str, float]) -> bool:
    if state.cooldowns.fire_blast > EPS:
        return False
    nominal_cost = eng.mana_cost(rank, talents, stats)
    cost = _clearcast_discount_and_consume(state, nominal_cost)
    if not _spend(state, cost):
        return False
    comp = expected_direct_components(level, mob.level, rank, talents, stats, cfg, state)
    _set_clearcast_after_landed_spell(state, talents, comp["hit"])
    state.mana = min(state.max_mana, state.mana + comp["mana_refund"])
    state.engaged = True
    was_rooted=state.t < state.root_until and state.root_probability>EPS
    state.hp = max(0.0, state.hp - comp["damage"])
    if was_rooted: _expected_break_root(state,comp["damage"],mob,rank.school,cfg)
    _apply_expected_impact(state,talents,comp["hit"])
    _grant_expected_hot_streak(state, talents, rank, comp)
    cd = (eng.fire_blast_cooldown(rank,talents) if hasattr(eng,'fire_blast_cooldown') else max(1.0,rank.cooldown-.5*talents.imp_fire_blast))
    state.cooldowns = replace(state.cooldowns, fire_blast=cd)
    casts[rank.spell] = casts.get(rank.spell, 0.0) + 1.0
    _advance(state, eng.GCD, level, talents, stats, cfg, mob, casts)
    state.cooldowns = state.cooldowns.tick(eng.GCD)
    return True


def _cast_nova(state: ExpectedState, rank: eng.Rank, level: int, talents: eng.Talents,
               stats: eng.Stats, cfg: eng.SimConfig, mob: eng.Mob,
               casts: Dict[str, float]) -> bool:
    if state.cooldowns.nova > EPS:
        return False
    nominal_cost = eng.mana_cost(rank, talents, stats)
    cost = _clearcast_discount_and_consume(state, nominal_cost)
    if not _spend(state, cost):
        return False
    comp = expected_direct_components(level, mob.level, rank, talents, stats, cfg, state)
    _set_clearcast_after_landed_spell(state, talents, comp["hit"])
    state.hp = max(0.0, state.hp - comp["damage"])
    state.engaged = True
    # Binary root: use expected landed probability as root occupancy.
    state.root_probability = comp["hit"] * comp["resist"]
    state.root_until = state.t + rank.root_duration
    cd = max(0.0, rank.cooldown - 2.0 * talents.imp_frost_nova)
    state.cooldowns = replace(state.cooldowns, nova=cd)
    casts["frost_nova"] = casts.get("frost_nova", 0.0) + 1.0
    _advance(state, eng.GCD, level, talents, stats, cfg, mob, casts)
    state.cooldowns = state.cooldowns.tick(eng.GCD)
    return True


def _blink(state: ExpectedState, level: int, talents: eng.Talents, stats: eng.Stats,
           cfg: eng.SimConfig, mob: eng.Mob, casts: Dict[str, float]) -> bool:
    if level < 20 or state.cooldowns.blink > EPS:
        return False
    cost = 0.35 * stats.base_mana
    if not _spend(state, cost):
        return False
    state.distance += 20.0
    state.in_melee = False
    state.cooldowns = replace(state.cooldowns, blink=15.0)
    casts["blink"] = casts.get("blink", 0.0) + 1.0
    _advance(state, eng.GCD, level, talents, stats, cfg, mob, casts)
    state.cooldowns = state.cooldowns.tick(eng.GCD)
    return True


def _cast_am(state: ExpectedState, rank: eng.Rank, level: int, talents: eng.Talents,
             stats: eng.Stats, cfg: eng.SimConfig, mob: eng.Mob,
             casts: Dict[str, float]) -> bool:
    barrage_p = (state.missile_barrage_probability
                 if getattr(talents, "missile_barrage", 0) and state.t < state.missile_barrage_until
                 else 0.0)
    barrage_p = max(0.0, min(1.0, barrage_p))
    # Missile Barrage makes AM free and halves channel duration. For structural
    # scoring use the expected mixture; event simulation owns discrete proc timing.
    wh = getattr(eng, 'wh', None)
    mb_cost_reduction = float(getattr(wh, 'MISSILE_BARRAGE_MANA_COST_REDUCTION', 0.0)) if wh is not None else 0.0
    nominal = rank.mana * (1.0 - barrage_p * mb_cost_reduction)
    cost=_clearcast_discount_and_consume(state, nominal)
    if not _spend(state, cost):
        return False
    state.engaged = True
    hit = eng.spell_hit(level, mob.level, "arcane", talents)
    resist = eng.resistance_damage_multiplier(level, talents, cfg, "arcane", mob.level)
    crit_p = stats.spell_crit
    am_sp_per_tick = stats.spell_power * _spell_power_direct_coeff(rank, cfg) / max(1, rank.channel_ticks)
    ab_stacks = state.arcane_blast_stacks if state.t < state.arcane_blast_until else 0
    ab_mult = 1.0
    if ab_stacks:
        ab_mult += float(getattr(wh, 'ARCANE_BLAST_OTHER_SPELL_DAMAGE_BONUS_PER_STACK', 0.0) if wh is not None else 0.0) * ab_stacks
        _consume_arcane_blast_buff(state)
    per_tick = (rank.channel_tick_damage + am_sp_per_tick) * (1.0 + 0.01 * talents.arcane_instability) * ab_mult * hit * resist * (1.0 + 0.5 * crit_p)
    # Expected interruption: once in melee, each tick survives with the expected
    # Improved AM protection.  Keep ticks discrete for kill breakpoints.
    survival = 1.0
    protect = (eng.am_pushback_protection(talents) if hasattr(eng,'am_pushback_protection') else .20*talents.imp_arcane_missiles)
    mb_channel_mult = float(getattr(wh, 'MISSILE_BARRAGE_CHANNEL_DURATION_MULT', 1.0)) if wh is not None else 1.0
    tick_s = 1.0 - barrage_p * (1.0-mb_channel_mult)
    for _ in range(rank.channel_ticks):
        if state.hp <= EPS:
            break
        _advance(state, tick_s, level, talents, stats, cfg, mob, casts)
        state.cooldowns = state.cooldowns.tick(tick_s)
        if state.in_melee:
            # v1 only suppresses the current AM tick when a melee swing lands
            # during that one-second tick; it does not permanently kill later
            # ticks.  Approximate the probability of >=1 swing in the tick from
            # the swing period, then weight by Improved AM protection.
            p_swing = min(1.0, 1.0 / max(mob.swing, EPS))
            shielded=_consume_expected_barrier_swings(state,p_swing,mob,cfg)
            unshielded=max(0.0,p_swing-shielded)
            tick_survival = 1.0 - unshielded * (1.0 - max(0.0, min(1.0, protect)))
        else:
            tick_survival = 1.0
        dmg=per_tick*tick_survival
        was_rooted=state.t < state.root_until and state.root_probability>EPS
        state.hp = max(0.0, state.hp - dmg)
        if was_rooted: _expected_break_root(state,dmg,mob,'arcane',cfg)
    # v1 rolls Arcane Concentration once at channel end if at least one tick
    # landed.  Approximate that event probability analytically.
    tick_land=max(0.0,min(1.0,hit))
    p_any=1.0-(1.0-tick_land)**max(1,int(rank.channel_ticks))
    _set_clearcast_after_landed_spell(state, talents, p_any)
    if barrage_p > 0.0:
        state.missile_barrage_probability = 0.0
        state.missile_barrage_until = -1e9
    casts["arcane_missiles"] = casts.get("arcane_missiles", 0.0) + 1.0
    return True


def _regen_until_affordable(state: ExpectedState, need: float, level: int, talents: eng.Talents,
                            stats: eng.Stats, cfg: eng.SimConfig, mob: eng.Mob,
                            casts: Dict[str, float]) -> None:
    """Deterministic OOM fallback.

    v2.0 uses expected best-wand DPS continuously while waiting for mana.  This
    is intentionally simpler than v1's discrete ranged-autoattack roll and is a
    calibration target rather than search noise.
    """
    deficit = max(0.0, need - state.mana)
    if deficit <= EPS:
        return
    five = max(0.0, state.last_mana_spend + 5.0 - state.t)
    inside = _mana_regen_rate(level, talents, stats, cfg, True)
    outside = _mana_regen_rate(level, talents, stats, cfg, False)
    gain_inside = inside * five
    if deficit <= gain_inside and inside > EPS:
        wait = deficit / inside
    else:
        wait = five + max(0.0, deficit - gain_inside) / max(outside, EPS)
    # Expected wand damage while waiting. Shoot uses the ranged-weapon hit
    # table, then magic-school resistance; Mage spell-hit talents do not apply.
    wand = eng.best_wand(level)
    neutral = eng.replace(talents, arcane_subtlety=0)
    hit = eng.wand_hit_chance(level, mob.level)
    if wand.school in ("fire", "frost", "arcane", "nature", "shadow"):
        pct = eng.effective_magic_resistance_percent(level, mob.level, wand.school, neutral, cfg, binary=False)
        mult = 1.0 - pct
    else:
        mult = 1.0
    dps = wand.dps * hit * mult
    state.hp = max(0.0, state.hp - dps * wait)
    casts["wand_expected_s"] = casts.get("wand_expected_s", 0.0) + wait
    _advance(state, wait, level, talents, stats, cfg, mob, casts)
    state.cooldowns = state.cooldowns.tick(wait)


def _next_primary(policy: eng.Policy, state: ExpectedState, level: int) -> Optional[eng.Rank]:
    if policy.pyro_opener and not state.pyro_opener_used:
        return eng.latest(eng.PYROBLAST, level)
    if getattr(policy, "arcane_blast_to_stacks", 0) > 0 and policy.primary == "arcane_blast":
        stacks = state.arcane_blast_stacks if state.t < state.arcane_blast_until else 0
        if stacks >= getattr(policy, "arcane_blast_to_stacks", 0):
            return eng.latest(eng.ARCANE_MISSILES, level)
        return eng.latest(eng.ARCANE_BLAST, level)
    if policy.fireball_block > 0 and policy.scorch_block > 0:
        cycle = policy.fireball_block + policy.scorch_block
        pos = (state.fire_cycle_pos + policy.fire_cycle_phase) % cycle
        return eng.latest(eng.FIREBALL if pos < policy.fireball_block else eng.SCORCH, level)
    table = {
        "frostbolt": eng.FROSTBOLT,
        "fireball": eng.FIREBALL,
        "scorch": eng.SCORCH,
    }
    arr = table.get(policy.primary)
    return eng.latest(arr, level) if arr else None


def _expected_wand_finisher_hit(level:int, talents:eng.Talents, cfg:eng.SimConfig, mob:eng.Mob)->float:
    wand=eng.best_wand(level)
    raw=.5*(float(wand.dmin)+float(wand.dmax))
    neutral=eng.replace(talents, arcane_subtlety=0)
    raw*=eng.wand_hit_chance(level,mob.level)
    if wand.school in ('fire','frost','arcane','nature','shadow'):
        pct=eng.effective_magic_resistance_percent(level,mob.level,wand.school,neutral,cfg,binary=False)
        raw*=max(0.0,1.0-pct)
    return max(EPS,raw)


def _try_expected_wand_finisher(state:ExpectedState, level:int, talents:eng.Talents,
                                 stats:eng.Stats, cfg:eng.SimConfig, mob:eng.Mob,
                                 policy:eng.Policy, casts:Dict[str,float])->bool:
    hits=max(0,int(getattr(policy,'wand_finisher_max_hits',0)))
    if hits<=0 or state.wand_finisher_committed or state.hp<=EPS:
        return False
    per_hit=_expected_wand_finisher_hit(level,talents,cfg,mob)
    if state.hp > hits*per_hit + EPS:
        return False
    state.wand_finisher_committed=True
    wand=eng.best_wand(level)
    for _ in range(hits):
        if state.hp<=EPS:
            break
        dt=float(wand.speed)
        _advance(state,dt,level,talents,stats,cfg,mob,casts)
        state.cooldowns=state.cooldowns.tick(dt)
        if state.hp<=EPS:
            break
        state.hp=max(0.0,state.hp-per_hit)
        casts['wand_finisher']=casts.get('wand_finisher',0.0)+1.0
        casts['wand_finisher_s']=casts.get('wand_finisher_s',0.0)+dt
    return True


def simulate_fight_expected(level: int, talents: eng.Talents, policy: eng.Policy,
                            cfg: eng.SimConfig, *, mob_level: Optional[int] = None,
                            mob_swing: Optional[float] = None,
                            cooldowns: CooldownState = CooldownState(),
                            hp_mult: float = 1.0,
                            combustion_extra_crit: float = 0.0,
                            initial_mana: Optional[float] = None,
                            recover_after: bool = True) -> FightOutcome:
    """One deterministic discrete fight from an explicit cooldown start state."""
    if mob_level is None:
        ml = int(level + (int(getattr(cfg,'target_level_offset',0)) if hasattr(cfg,'server_profile') else 1))
    else:
        ml = int(mob_level)
    swing = float(cfg.mob_swing if mob_swing is None else mob_swing)
    mob = eng.Mob(ml, eng.MOB_BASE_HP[ml] * hp_mult, cfg.mob_speed, swing, cfg.melee_reach)
    stats = eng.player_stats_for_config(level, talents, cfg)
    primary = _next_primary(policy, ExpectedState(0, mob.hp, stats.max_mana, stats.max_mana, 30), level)
    start_range = eng.effective_range(primary, talents) if primary is not None else 30.0
    if policy.fbo_r1_mode != "none" and policy.primary in ("fireball", "scorch"):
        start_range = min(start_range, eng.effective_range(eng.FROSTBOLT[0], talents))
    # v1 does not carry Clearcasting across pull boundaries.  A fresh mob starts
    # with CC inactive; the first landed spell can proc it for the *next* spell.
    # Seeding the fight with hit*proc here gave every pull an unearned free-cast
    # probability and systematically under-estimated mana/recovery time.
    initial_cc=0.0
    carried_duration=max(0.0,float(cooldowns.ice_barrier_duration))
    carried_absorb=max(0.0,float(cooldowns.ice_barrier_absorb)) if carried_duration>EPS else 0.0
    start_mana=stats.max_mana if initial_mana is None else max(0.0,min(stats.max_mana,float(initial_mana)))
    state = ExpectedState(0.0, mob.hp, start_mana, stats.max_mana, start_range,
                          cooldowns=cooldowns, combustion_extra_crit=max(0.0,combustion_extra_crit),
                          clearcast_probability=initial_cc,ice_barrier_absorb=carried_absorb,
                          ice_barrier_until=(carried_duration if carried_duration>EPS else -1e9),
                          hp_barrier_absorb=carried_absorb,
                          hp_barrier_until=(carried_duration if carried_duration>EPS else -1e9))
    casts: Dict[str, float] = {}
    mana_start = state.mana
    if policy.use_ice_barrier:
        _maybe_cast_ice_barrier(state,level,talents,stats,cfg,mob,casts)
    flags = {"expected_rng_v1"}
    if talents.ignite:
        flags.add("ignite_expected_refresh_approx")
    if talents.frostbite or talents.shatter:
        flags.add("root_probability_approx")
    if talents.impact:
        flags.add("impact_stun_probability_approx")
    if talents.combustion:
        flags.add("combustion_long_run_expected")
    if getattr(talents, "hot_streak", 0):
        flags.add("hot_streak_expected_stack_occupancy_event_authority")
    if talents.arcane_concentration:
        flags.add("clearcasting_expected_mana")
    if getattr(policy, "arcane_blast_to_stacks", 0) > 0 and getattr(talents, "missile_barrage", 0):
        flags.add("missile_barrage_proc_event_authority")
    if talents.ice_barrier and policy.use_ice_barrier:
        flags.add("ice_barrier_absorb_pushback_approx")
    if getattr(policy,'use_proc_ice_lance',False):
        flags.add('ice_lance_expected_frozen_occupancy_event_authority')

    for _step in range(256):
        if state.hp <= EPS:
            break
        hpfrac = state.hp / mob.hp
        if _try_expected_wand_finisher(state,level,talents,stats,cfg,mob,policy,casts):
            continue
        fb = eng.latest(eng.FIRE_BLAST, level)
        if (policy.use_fireblast and fb and state.cooldowns.fire_blast <= EPS
                and state.distance <= eng.effective_range(fb, talents) + EPS
                and hpfrac <= policy.fireblast_execute_frac):
            if _cast_fire_blast(state, fb, level, talents, stats, cfg, mob, casts):
                continue

        if policy.use_nova and policy.nova_cycle_pos < 0 and state.in_melee and state.cooldowns.nova <= EPS:
            nr = eng.FROST_NOVA[0] if policy.nova_rank1 else eng.latest(eng.FROST_NOVA, level)
            if nr and state.distance <= nr.radius * (1.0 + 0.1 * talents.arctic_reach):
                if _cast_nova(state, nr, level, talents, stats, cfg, mob, casts):
                    # deterministic expected separation while root occupancy lasts
                    yards = max(0.0, policy.nova_move_yards)
                    state.distance += yards * state.root_probability
                    _advance(state, yards / 7.0, level, talents, stats, cfg, mob, casts)
                    state.cooldowns = state.cooldowns.tick(yards / 7.0)
                    continue

        if (policy.use_blink and state.in_melee and level >= 20 and state.cooldowns.blink <= EPS
                and hpfrac >= policy.blink_min_hp_frac):
            if _blink(state, level, talents, stats, cfg, mob, casts):
                continue

        if getattr(policy, "hot_streak_pyro_stacks", 0) > 0 and getattr(talents, "hot_streak", 0) and getattr(talents, "pyroblast", 0):
            if _active_hot_streak_stacks(state) + EPS >= float(policy.hot_streak_pyro_stacks):
                py = eng.latest(eng.PYROBLAST, level)
                if py is not None:
                    nominal = eng.mana_cost(py, talents, stats)
                    need = nominal * (1.0 - max(0.0, min(1.0, state.clearcast_probability)))
                    if state.mana + EPS < need:
                        _regen_until_affordable(state, need, level, talents, stats, cfg, mob, casts)
                    else:
                        _cast_direct(state, py, level, talents, stats, cfg, mob, casts)
                    continue

        if getattr(policy,'use_proc_ice_lance',False) and getattr(talents,'ice_lance',0):
            root_p=max(0.0,min(1.0,state.root_probability if state.t < state.root_until else 0.0))
            fof_p=max(0.0,min(1.0,state.fingers_of_frost_charges if state.t < state.fingers_of_frost_until else 0.0))
            frozen_p=1.0-(1.0-root_p)*(1.0-fof_p)
            # Use Ice Lance only when the expected Frozen/FoF occupancy is
            # material. Event simulation owns exact proc timing.
            if frozen_p >= 0.50:
                il=eng.latest(eng.ICE_LANCE,level)
                if il is not None:
                    need=eng.mana_cost(il,talents,stats)*(1.0-max(0.0,min(1.0,state.clearcast_probability)))
                    if state.mana + EPS < need:
                        _regen_until_affordable(state,need,level,talents,stats,cfg,mob,casts)
                    else:
                        before_fof=fof_p
                        _cast_direct(state,il,level,talents,stats,cfg,mob,casts)
                        if before_fof>EPS and state.fingers_of_frost_charges>0:
                            state.fingers_of_frost_charges=max(0.0,state.fingers_of_frost_charges-1.0)
                    continue

        if policy.primary == "arcane_missiles":
            am = eng.latest(eng.ARCANE_MISSILES, level)
            if am is None:
                raise ValueError(f"Arcane Missiles unavailable at level {level}")
            need=am.mana*(1.0-max(0.0,min(1.0,state.clearcast_probability)))
            if state.mana + EPS < need:
                _regen_until_affordable(state, need, level, talents, stats, cfg, mob, casts)
                continue
            _cast_am(state, am, level, talents, stats, cfg, mob, casts)
            continue

        # Fire utility R1 opener/maintenance.
        if policy.fbo_r1_mode != "none" and policy.primary in ("fireball", "scorch"):
            r1 = eng.FROSTBOLT[0]
            use_r1 = False
            if policy.fbo_r1_mode == "opener" and not state.engaged:
                use_r1 = True
            elif (policy.fbo_r1_mode == "maintain" and not state.in_melee
                  and (not state.engaged or state.slow_until - state.t <= policy.fbo_r1_refresh_s)):
                use_r1 = True
            if use_r1:
                cost = eng.mana_cost(r1, talents, stats)*(1.0-max(0.0,min(1.0,state.clearcast_probability)))
                if state.mana + EPS < cost:
                    _regen_until_affordable(state, cost, level, talents, stats, cfg, mob, casts)
                else:
                    _cast_direct(state, r1, level, talents, stats, cfg, mob, casts)
                continue

        rank = _next_primary(policy, state, level)
        if rank is None:
            raise ValueError(f"No direct primary for policy {policy.name!r} at level {level}")
        if rank.spell == "arcane_missiles":
            need = rank.mana * (1.0 - max(0.0, min(1.0, state.clearcast_probability)))
            if state.mana + EPS < need:
                _regen_until_affordable(state, need, level, talents, stats, cfg, mob, casts)
                continue
            _cast_am(state, rank, level, talents, stats, cfg, mob, casts)
            continue
        if state.distance > eng.effective_range(rank, talents) + EPS:
            # Walk into range before aggro; after aggro let the mob close.
            target = eng.effective_range(rank, talents)
            if state.engaged:
                speed = mob.run_speed * ((1.0 - state.slow_frac) if state.t < state.slow_until else 1.0)
                dt = max(0.0, (state.distance - target) / max(speed, EPS))
            else:
                dt = max(0.0, (state.distance - target) / 7.0)
                state.distance = target
            _advance(state, max(dt, 1e-6), level, talents, stats, cfg, mob, casts)
            state.cooldowns = state.cooldowns.tick(max(dt, 1e-6))
            continue
        nominal = (_arcane_blast_nominal_cost(state, stats)
                   if rank.spell == "arcane_blast" else eng.mana_cost(rank, talents, stats))
        cost = nominal*(1.0-max(0.0,min(1.0,state.clearcast_probability)))
        if state.mana + EPS < cost:
            _regen_until_affordable(state, cost, level, talents, stats, cfg, mob, casts)
            continue
        _cast_direct(state, rank, level, talents, stats, cfg, mob, casts)
        if rank.spell == "pyroblast":
            state.pyro_opener_used = True
        if policy.fireball_block > 0 and policy.scorch_block > 0 and rank.spell in ("fireball", "scorch"):
            state.fire_cycle_pos += 1
        # Direct casts tick cooldowns by their actual elapsed cast time inside
        # _cast_direct.  Projectile travel is asynchronous and must not be
        # double-counted here.
    else:
        raise RuntimeError(f"expected simulator stalled at level {level}: {eng.policy_desc(policy, level)}")

    kill_s = state.t
    mana_left = max(0.0, state.mana)
    recovery = (eng.recovery_time(level, talents, mana_left, cfg, max(0.0, state.last_mana_spend + 5.0 - state.t))
                if recover_after else 0.0)
    barrier_duration=max(0.0,state.ice_barrier_until-state.t)
    barrier_absorb=max(0.0,state.ice_barrier_absorb) if barrier_duration>EPS else 0.0
    live_cd=replace(state.cooldowns,ice_barrier_absorb=barrier_absorb,
                    ice_barrier_duration=barrier_duration)
    end_cd = live_cd.tick(recovery)
    mana_spent = max(0.0, mana_start - mana_left)
    hp_missing=0.0
    if hasattr(eng,'_mage_player_hp_and_armor') and hasattr(eng,'normal_world_raw_dps'):
        _player_hp,player_armor=eng._mage_player_hp_and_armor(level,talents,cfg)
        raw_hit=eng.normal_world_raw_dps(mob.level)*mob.swing
        hit_after_armor=raw_hit*(1.0-eng.armor_reduction(player_armor,mob.level))
        hp_missing=max(0.0,state.expected_unabsorbed_swings*hit_after_armor)
    total = kill_s + recovery
    return FightOutcome(
        kill_s=kill_s, recovery_s=recovery, total_s=total,
        mana_spent=mana_spent, mana_left=mana_left, end_cooldowns=end_cd,
        casts=casts, mob_level=ml,
        active_dps=(mob.hp / kill_s if kill_s > EPS else 0.0),
        hp_missing=hp_missing, unabsorbed_swings=state.expected_unabsorbed_swings,
        melee_contact_s=state.expected_melee_contact_s, pushback_s=state.expected_pushback_s,
        approximation_flags=tuple(sorted(flags | {'player_hp_melee_swing_approx'})),
    )


def _score_policy_legacy(level: int, talents: eng.Talents, policy: eng.Policy, cfg: eng.SimConfig,
                 *, cycle_pulls: int = 6, hp_mult: float = 1.0,
                 initial_cooldowns: CooldownState = CooldownState()) -> dict:
    """Score one policy on a short deterministic pull cycle.

    Six pulls exactly cover the v1 target stream's +1/+2 mob alternation and the
    default 1.5/2.0/2.5 swing-speed mixture.  This is the temporary state solver;
    its input/output shape is intentionally compatible with replacing it by a
    small finite-state transition-matrix solver.
    """
    n = max(1, int(cycle_pulls))
    cd = initial_cooldowns
    total = kill = recovery = mana = damage = 0.0
    casts: Dict[str, float] = {}
    outcomes = []
    for i in range(n):
        ml = level + (1 if i % 2 == 0 else 2)
        swing = (cfg.mob_swing_mix[(i // 2) % len(cfg.mob_swing_mix)]
                 if cfg.mob_swing_mix else cfg.mob_swing)
        out = simulate_fight_expected(level, talents, policy, cfg, mob_level=ml,
                                      mob_swing=swing, cooldowns=cd, hp_mult=hp_mult)
        outcomes.append(out)
        cd = out.end_cooldowns
        total += out.total_s; kill += out.kill_s; recovery += out.recovery_s; mana += out.mana_spent
        damage += eng.MOB_BASE_HP[ml] * hp_mult
        for k, v in out.casts.items(): casts[k] = casts.get(k, 0.0) + v
    scale = 100.0 / n
    result = {
        "total_s": total * scale,
        "kill_s": kill * scale,
        "recovery_s": recovery * scale,
        "mana": mana * scale,
        "active_dps": damage / kill if kill > EPS else 0.0,
        "mean_s_per_mob": total / n,
        "simulated_pulls": n,
        "deterministic": True,
        "cooldown_start_mask": initial_cooldowns.ready_mask(),
        "cooldown_end_mask": cd.ready_mask(),
        "cooldown_end": cd,
        "outcomes": outcomes,
    }
    for k, v in casts.items(): result["casts_" + k] = v * scale
    return result



def score_policy(level: int, talents: eng.Talents, policy: eng.Policy, cfg: eng.SimConfig,
                 *, cycle_pulls: int = 6, hp_mult: float = 1.0,
                 initial_cooldowns: CooldownState = CooldownState()) -> dict:
    """Deterministic sustained same-level pull cycle with carried resources."""
    if not hasattr(cfg, "server_profile"):
        return _score_policy_legacy(level,talents,policy,cfg,cycle_pulls=cycle_pulls,
                                    hp_mult=hp_mult,initial_cooldowns=initial_cooldowns)
    n=max(1,int(cycle_pulls))
    cd=initial_cooldowns
    stats=eng.player_stats_for_config(level,talents,cfg)
    mana_now=float(stats.max_mana)
    prev_spend=0.0
    gem_cd=0.0
    evo_cd=0.0
    gem_needs_restock=False
    hp_missing_now=0.0
    player_hp, _player_armor = eng._mage_player_hp_and_armor(level,talents,cfg)
    gem_uses=evo_uses=full_recoveries=0
    total=kill=recovery=mana=damage=contact=pushback=0.0
    casts: Dict[str,float]={}
    outcomes=[]

    def primary_floor()->float:
        if policy.primary == 'arcane_missiles':
            r=eng.latest(eng.ARCANE_MISSILES,level); return float(r.mana if r else 0.0)
        table=eng.SPELLS.get(policy.primary,eng.FROSTBOLT); r=eng.latest(table,level) if table else None
        if r is None: return 0.0
        if r.spell == 'arcane_blast': return float(stats.base_mana)*float(eng.wh.ARCANE_BLAST_BASE_MANA_PCT)
        return float(eng.mana_cost(r,talents,stats))

    def tick(dt:float):
        nonlocal cd,gem_cd,evo_cd
        cd=cd.tick(dt); gem_cd=max(0.0,gem_cd-dt); evo_cd=max(0.0,evo_cd-dt)

    def resource_step(force_full:bool=False)->float:
        nonlocal mana_now,hp_missing_now,gem_cd,evo_cd,gem_needs_restock,gem_uses,evo_uses,full_recoveries
        need=min(stats.max_mana,max(primary_floor(),0.80*max(0.0,prev_spend)))
        hp_needs_recovery=hp_missing_now >= 0.55*player_hp
        if not force_full and mana_now+EPS >= need and not hp_needs_recovery: return 0.0
        profile=cfg.server_profile
        gem=mana_gem_tier(level) if profile.mana_gem_enabled else None
        if (not force_full and gem and gem_cd<=EPS and not gem_needs_restock
                and mana_now+EPS<need and mana_now<=stats.max_mana-0.55*gem.restore):
            mana_now=min(stats.max_mana,mana_now+gem.restore); gem_cd=float(profile.mana_gem_cooldown_s)
            gem_needs_restock=True; gem_uses+=1
            if mana_now+EPS>=need and not hp_needs_recovery: return 0.0
        if (not force_full and level>=20 and profile.evocation_enabled and evo_cd<=EPS
                and mana_now+EPS<need and not hp_needs_recovery):
            gain=stats.max_mana*max(0.0,float(profile.evocation_restore_fraction))
            evo_s=max(0.0,float(profile.evocation_channel_s))
            water=best_mage_water(level,best_available=bool(cfg.use_best_water))
            drink_to_need=max(0.0,need-mana_now)/max(EPS,water.rate_per_s + ooc_mana_regen_per_s(stats))
            if gain>0 and evo_s<=drink_to_need+EPS:
                mana_now=min(stats.max_mana,mana_now+gain); evo_uses+=1
                evo_cd=max(0.0,float(profile.evocation_cooldown_s)); tick(evo_s)
                if mana_now+EPS>=need: return evo_s
        water=best_mage_water(level,best_available=bool(cfg.use_best_water))
        recovered=solve_recovery(
            level, max(0.0,hp_missing_now), max(0.0, stats.max_mana-mana_now),
            passive_mana_regen_per_s=ooc_mana_regen_per_s(stats),
            water_override=water,
        )
        rt=float(recovered.total_s)
        if gem_needs_restock and gem is not None:
            rt+=max(0.0,float(profile.mana_gem_restock_s)); gem_needs_restock=False
        mana_now=stats.max_mana; hp_missing_now=0.0; full_recoveries+=1; tick(rt); return rt

    for i in range(n):
        pre=resource_step(False) if i>0 else 0.0
        swing=(cfg.mob_swing_mix[i%len(cfg.mob_swing_mix)] if cfg.mob_swing_mix else cfg.mob_swing)
        before=mana_now
        ml=level+int(getattr(cfg,'target_level_offset',0))
        out=simulate_fight_expected(level,talents,policy,cfg,mob_level=ml,mob_swing=swing,
                                    cooldowns=cd,hp_mult=hp_mult,initial_mana=mana_now,recover_after=False)
        outcomes.append(out); cd=out.end_cooldowns; mana_now=float(out.mana_left)
        hp_missing_now += max(0.0,float(out.hp_missing))
        prev_spend=max(0.0,before-mana_now)
        total+=pre+out.kill_s; recovery+=pre; kill+=out.kill_s; mana+=prev_spend
        contact+=float(out.melee_contact_s); pushback+=float(out.pushback_s)
        damage+=eng.MOB_BASE_HP[ml]*hp_mult
        gem_cd=max(0.0,gem_cd-out.kill_s); evo_cd=max(0.0,evo_cd-out.kill_s)
        for k,v in out.casts.items(): casts[k]=casts.get(k,0.0)+v
    tail=resource_step(True); total+=tail; recovery+=tail
    scale=100.0/n
    travel_per_mob=between_pull_travel_s()
    travel_s=travel_per_mob*100.0
    result={
        'total_s':total*scale+travel_s,'kill_s':kill*scale,'recovery_s':recovery*scale,
        'travel_s':travel_s,'mana':mana*scale,
        'active_dps':damage/kill if kill>EPS else 0.0,'mean_s_per_mob':total/n+travel_per_mob,
        'simulated_pulls':n,'deterministic':True,'cooldown_start_mask':initial_cooldowns.ready_mask(),
        'cooldown_end_mask':cd.ready_mask(),'cooldown_end':cd,'outcomes':outcomes,
        'mana_gem_uses':gem_uses,'evocation_uses':evo_uses,'full_recoveries':full_recoveries,
        'target_level_offset':int(getattr(cfg,'target_level_offset',0)),
        'evocation_end_cd_s':evo_cd,
        'hp_missing_end':hp_missing_now,
        'player_hp':player_hp,
        'melee_contact_s':contact*scale,
        'pushback_s':pushback*scale,
        'recovery_solver_id':RECOVERY_SOLVER_ID,
        'fire_state_model': {
            'id': 'fire_hot_streak_expected_state_v1',
            'hot_streak_modeled': bool(getattr(talents,'hot_streak',0) and getattr(talents,'pyroblast',0)),
            'hot_streak_stack_cap': 3,
            'hot_streak_duration_s': 15.0,
            'pyroblast_modeled': bool(getattr(talents,'pyroblast',0)),
            'fire_blast_modeled': bool(eng.latest(eng.FIRE_BLAST,level)),
            'aoe_assumptions': 'none_single_target_only',
        },
        'arcane_state_model': {
            'id': 'arcane_ab_mb_expected_state_v1',
            'arcane_blast_stack_cap': int(eng.wh.ARCANE_BLAST_MAX_STACKS),
            'arcane_blast_stack_duration_s': float(eng.wh.ARCANE_BLAST_STACK_DURATION_S),
            'missile_barrage_modeled': bool(getattr(talents,'missile_barrage',0)),
            'missile_barrage_ab_proc_chance': float(eng.wh.MISSILE_BARRAGE_ARCANE_BLAST_PROC_CHANCE),
            'missile_barrage_duration_s': float(eng.wh.MISSILE_BARRAGE_DURATION_S),
            'presence_of_mind': 'fail_closed_no_normalized_effect_authority' if getattr(talents,'presence_of_mind',0) else 'not_selected',
            'arcane_power': 'fail_closed_no_normalized_effect_authority' if getattr(talents,'arcane_power',0) else 'not_selected',
        },
    }
    for k,v in casts.items(): result['casts_'+k]=v*scale
    return result


def policy_basis(level: int, talents: eng.Talents) -> list[eng.Policy]:
    """Small v2 policy basis; search parameters are layered on later."""
    out: list[eng.Policy] = []
    if eng.latest(eng.FROSTBOLT, level):
        out += [
            eng.Policy("v2 FBo pure", "frostbolt", use_fireblast=False, use_nova=False, use_blink=False),
            eng.Policy("v2 FBo utility", "frostbolt", use_fireblast=True, use_nova=True, use_blink=True),
        ]
        if getattr(talents,'ice_lance',0) and eng.latest(eng.ICE_LANCE,level):
            out += [
                eng.Policy("v2 FBo + Frozen/FoF->IL", "frostbolt", use_fireblast=False, use_nova=True, nova_rank1=True, nova_move_yards=5, use_blink=False, use_proc_ice_lance=True),
                eng.Policy("v2 FBo utility + Frozen/FoF->IL", "frostbolt", use_fireblast=True, use_nova=True, nova_rank1=True, nova_move_yards=5, use_blink=True, use_proc_ice_lance=True),
            ]
    if eng.latest(eng.FIREBALL, level):
        out += [
            eng.Policy("v2 FBa pure", "fireball", use_fireblast=False, use_nova=False, use_blink=False),
            eng.Policy("v2 FBa utility", "fireball", use_fireblast=True, use_nova=True, use_blink=True),
        ]
    if eng.latest(eng.SCORCH, level):
        out += [
            eng.Policy("v2 Sc pure", "scorch", use_fireblast=False, use_nova=False, use_blink=False),
            eng.Policy("v2 Sc utility", "scorch", use_fireblast=True, use_nova=True, use_blink=True),
        ]
    if eng.latest(eng.ARCANE_MISSILES, level):
        out.append(eng.Policy("v2 AM", "arcane_missiles", use_fireblast=False, use_nova=False, use_blink=False))
    return out


def _dedup_policies(policies: Iterable[eng.Policy]) -> list[eng.Policy]:
    out=[]; seen=set()
    for p in policies:
        key=tuple(getattr(p,f) for f in p.__dataclass_fields__ if f != "name")
        if key not in seen:
            seen.add(key); out.append(p)
    return out


# Fireball/Scorch is the only policy family that used to have a wide cadence
# cross-product.  The useful solutions are highly structured: pure Fireball,
# pure Scorch, and a few short projectile-aware phase templates.  Improved
# Scorch rank changes which templates are worth considering, so keep a tiny
# rank-conditioned basis rather than 4*3*(a+b) = 54 cadence policies.
#
# Tuple = (fireball block, scorch block, phase).  phase=0 means e.g. 2/3 is
# FBa,FBa,Sc,Sc,Sc,...; phase=2 starts Sc,Sc,Sc,FBa,FBa,... .  The sets below
# were chosen from exhaustive analytical dominance/regret sweeps around Scorch
# rank breakpoints.  Pure FBa/Sc remain in policy_basis() for every rank.
_FIRE_COMPACT_TEMPLATES = {
    # Rank 0 still keeps mixed challengers: Scorch can be a strong rank-breakpoint
    # filler even without the vulnerability proc, and projectile-first phases can
    # overlap Fireball travel with subsequent Scorch casts.
    0: ((1,3,0),(2,3,0),(3,3,0),(4,1,0),(2,1,2),(3,3,3),(4,3,3)),
    1: ((1,3,0),(2,3,0),(3,3,0),(4,1,0),(2,3,2),(3,3,4),(4,2,4)),
    2: ((1,3,0),(2,3,0),(3,3,0),(4,1,0),(2,2,2),(3,2,3)),
    3: ((1,3,0),(2,3,0),(3,3,0),(4,1,0),(2,3,2),(2,3,3),(3,2,3)),
}


def compact_fire_cadence_policies(level:int,talents:eng.Talents)->list[eng.Policy]:
    """Small projectile-aware Fire rotation basis conditioned on Improved Scorch.

    This is a proposal basis, not a rule that a build must use Fire.  Family
    gating happens one layer above and pure Fireball/Scorch anchors are always
    available.  The old exhaustive cadence basis remains available through
    :func:`policy_candidates_expected_exhaustive` for differential validation.
    """
    if eng.latest(eng.FIREBALL,level) is None or eng.latest(eng.SCORCH,level) is None:
        return []
    imp=max(0,min(3,int(getattr(talents,'imp_scorch',0))))
    out=[]
    for fb_n,sc_n,phase in _FIRE_COMPACT_TEMPLATES[imp]:
        suffix=f'@{phase}' if phase else ''
        out.append(eng.Policy(
            f'KISS FBa{fb_n}/Sc{sc_n}{suffix}', primary='fireball',
            use_fireblast=True, fireblast_execute_frac=.22,
            use_nova=True, nova_rank1=True, nova_move_yards=5,
            use_blink=True, blink_min_hp_frac=.35,
            fireball_block=fb_n, scorch_block=sc_n,
            fire_cycle_phase=phase))
    return out


def policy_candidates_expected_exhaustive(level:int,talents:eng.Talents)->list[eng.Policy]:
    """Reference basis: anchors plus all 54 legacy Fire cadence policies."""
    base=list(policy_basis(level,talents))
    base.extend(eng.candidate_fire_cadence_policies(level))
    base=eng.with_ice_barrier_policy_variants(base,level,talents)
    return _dedup_policies(base)


def policy_candidates_expected(level: int, talents: eng.Talents) -> list[eng.Policy]:
    """KISS deterministic proposal set used by the live v2 search.

    Every spell family still has a cheap anchor.  Fire gets only a handful of
    Improved-Scorch-conditioned projectile-aware cadence templates instead of
    the old 54-policy cadence cross-product.
    """
    base=list(policy_basis(level,talents))
    base.extend(compact_fire_cadence_policies(level,talents))
    base=eng.with_ice_barrier_policy_variants(base,level,talents)
    return _dedup_policies(base)


def _policy_refinements(level: int, talents: eng.Talents, parents: list[eng.Policy]) -> list[eng.Policy]:
    """Small, explicit utility expansion around deterministic leaders."""
    import dataclasses
    out=list(parents)
    for p in parents:
        if p.primary in ("fireball","scorch") or (p.fireball_block and p.scorch_block):
            out.append(dataclasses.replace(p,name=p.name+"+FBoR1",fbo_r1_mode="maintain"))
            if talents.pyroblast and eng.latest(eng.PYROBLAST,level):
                out.append(dataclasses.replace(p,name=p.name+"+Pyro",pyro_opener=True))
            if p.fireball_block and p.scorch_block and p.use_nova:
                cycle=p.fireball_block+p.scorch_block
                # Scheduled Nova positions only around already-good cadence parents.
                for pos in range(cycle):
                    out.append(dataclasses.replace(p,name=p.name+f"+FN@{pos}",nova_cycle_pos=pos,
                                                   nova_rank1=True,nova_move_yards=6.0))
    return _dedup_policies(out)


def optimize_policy_expected(level: int, talents: eng.Talents, cfg: eng.SimConfig,
                             *, proposal_pulls: int = 2, refine_pulls: int = 6,
                             parent_k: int = 8, policies=None) -> tuple[eng.Policy, dict]:
    """Predict -> refine policy search without Monte Carlo precision ladders."""
    scored=[]
    skipped=0
    basis=list(policy_candidates_expected(level,talents) if policies is None else policies)
    allowed_schools=None if policies is None else {eng.policy_primary_school(p) for p in basis}
    for p in basis:
        try:
            r=score_policy(level,talents,p,cfg,cycle_pulls=proposal_pulls)
        except (RuntimeError, ValueError, OverflowError):
            skipped += 1
            continue
        scored.append((r["total_s"],eng.policy_desc(p,level),p,r))
    scored.sort(key=lambda x:(x[0],x[1]))
    parents=[x[2] for x in scored[:max(1,int(parent_k))]]
    finalists=_policy_refinements(level,talents,parents)
    if allowed_schools is not None:
        finalists=[p for p in finalists if eng.policy_primary_school(p) in allowed_schools]
    best=None
    for p in finalists:
        try:
            r=score_policy(level,talents,p,cfg,cycle_pulls=refine_pulls)
        except (RuntimeError, ValueError, OverflowError):
            skipped += 1
            continue
        item=(r["total_s"],eng.policy_desc(p,level),p,r)
        if best is None or item[:2] < best[:2]: best=item
    if best is None:
        raise ValueError(f"no policies available at level {level}")
    best[3]["proposal_pulls"]=int(proposal_pulls)
    best[3]["refine_pulls"]=int(refine_pulls)
    best[3]["proposal_count"]=len(scored)
    best[3]["finalist_count"]=len(finalists)
    best[3]["skipped_invalid_policies"]=skipped
    return best[2],best[3]
