from __future__ import annotations

"""G36: one Forever-sourced duration with synthetic damage, not a playable build.

Forever Wowhead spell 467079 declares 15 s Force of Nature/Treant lifetime.
This is *not* authority for a player-available spell, talent or Treant DPS.
"""

from src.game.model import (ActorDefinition, ActionDefinition, AutoAttackDamageSource,
    AutoAttackDefinition, DamageEffect, TimedSummonDefinition)
from .simulator import CombatRuntime
from .state import ActorState, TargetState

FOREVER_TREANT_SPELL = 'https://www.wowhead.com/forever/spell=467079/force-of-nature'
TREANT_DURATION_S = 15.0


def create_probe_runtime(*, with_summon: bool, schedule_spawn: bool = True) -> CombatRuntime:
    defs = (
        ActorDefinition('g36:player', 'player', state_status='synthetic_damage_fixture'),
        ActorDefinition('g36:pet', 'pet', state_status='synthetic_damage_fixture'),
        ActorDefinition('g36:treant', 'summon', state_status='source_duration_synthetic_damage',
                        provenance=({'url': FOREVER_TREANT_SPELL, 'field': 'duration_s', 'value': 15},)),
    )
    actors = [ActorState.from_ir(d, ()) for d in defs]
    attacks = (
        AutoAttackDefinition('g36:player:auto', 'Player swings', defs[0].id,
            'melee', 4, 'physical',
            AutoAttackDamageSource(kind='synthetic_fixture', flat_dps=2)),
        AutoAttackDefinition('g36:pet:auto', 'Permanent pet swings', defs[1].id,
            'melee', 3, 'physical',
            AutoAttackDamageSource(kind='synthetic_fixture', flat_dps=3)),
    )
    if with_summon:
        attacks += (AutoAttackDefinition('g36:treant:auto', 'Summon swings', defs[2].id,
            'melee', 2, 'physical',
            AutoAttackDamageSource(kind='synthetic_fixture', flat_dps=5)),)
    summon = TimedSummonDefinition(
        id='g36:force_of_nature:sample_treant', owner_actor_id=defs[0].id,
        summoned_actor_id=defs[2].id, duration_s=TREANT_DURATION_S,
        provenance=({'source': FOREVER_TREANT_SPELL, 'field': 'summon_duration',
                     'value_s': TREANT_DURATION_S},),
        metadata={'availability': 'unverified_player_spell',
                  'count': 'one_representative_actor_not_full_spell_count',
                  'damage': 'synthetic_mechanics_fixture'},
    )
    runtime = CombatRuntime(actor=actors[0],
        companions=tuple(actors[1:] if with_summon else actors[1:2]),
        target=TargetState.with_health('g36:large_target', 1000),
        auto_attacks=attacks, timed_summons=(summon,) if with_summon else ())
    if with_summon and schedule_spawn:
        runtime.enqueue_summon(summon.id)
    return runtime


def execute_timed_summon_mechanics_probe() -> dict:
    base = create_probe_runtime(with_summon=False)
    base.advance_to(20.0)
    active = create_probe_runtime(with_summon=True)
    active.advance_to(14.0)
    # Cast completes after despawn and must not apply damage.
    delayed = ActionDefinition(
        id='g36:treant:slow_spell', family_key='test_delayed_summon_cast',
        name='Delayed test cast', owner_actor_id='g36:treant',
        requirements=(), costs=(), cast_time_s=3, gcd_s=1.5, cooldown_s=0,
        effects=(DamageEffect('damage', 'nature', 'enemy', 50, 50),),
        provenance=({'status': 'synthetic_mechanics_fixture'},),
    )
    active.enqueue_action(delayed)
    active.advance_to(20.0)
    result = active.result()
    baseline = base.result()
    lifecycle = [x.as_dict() for x in result.events
                 if x.kind in ('SummonSpawn', 'SummonDespawn')]
    attempted_after = [x.as_dict() for x in result.events
                       if x.kind == 'SummonEventSkipped']
    return {
        'status': 'executed', 'scope': 'timed_summon_mechanics_not_playable_druid',
        'source_spell': FOREVER_TREANT_SPELL, 'duration_s': TREANT_DURATION_S,
        'numeric_authority': 'source_duration_and_synthetic_damage',
        'baseline_damage': baseline.total_damage,
        'with_summon_damage': result.total_damage,
        'summon_added_damage': result.total_damage - baseline.total_damage,
        'damage_by_actor': result.damage_by_actor,
        'damage_by_role': result.damage_by_role,
        'actor_roles': result.actor_roles,
        'lifecycle': lifecycle, 'skipped_after_despawn': attempted_after,
        'summon_damage_times_s': [x.time_s for x in result.events
             if x.kind == 'Damage' and x.actor_id == 'g36:treant' and x.payload.get('applied')],
        'source_limits': ['player_spell_availability_unverified',
                          'summoned_actor_count_unverified',
                          'summon_base_damage_synthetic', 'no_class_route_score'],
        'legacy_fallback': False,
    }
