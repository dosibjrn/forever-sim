"""Source-IR compatibility helpers used by the live bounded-joint frontier.

These are transitional runtime helpers, not a second P1/P2 or P3 gate.
Retired non-certifying Python preflight and 100-mob screen code is not retained.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from src.scenarios.leveling_targets import representative_hp
from src.game.data.forever.target_combat_source import load_target_combat_profile
from src.game.model import PolicyDefinition, PolicyRuleDefinition


HEALTH_SOURCE = ('https://raw.githubusercontent.com/mangoszero/database/'
                 '325948a78015794e6cc626212bc19fee70c805b2/'
                 'World/Setup/FullDB/creature_template_classlevelstats.sql')


@dataclass(frozen=True)
class CheckpointEnemy:
    player_level: int
    enemy_level: int
    hp: float
    hp_authority: str
    hp_source_url: str
    combat_authority: str
    combat_capture_id: str
    armor: float
    melee_hit: float
    spell_hit: float
    scenario_key: str
    exact_forever_enemy_verified: bool

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def checkpoint_enemy(*, ir, level: int) -> CheckpointEnemy:
    """Resolve the SAME class-neutral enemy from the game's canonical sources.

    Refuse to infer real Forever NPC health from a Classic class-level mean.
    For real named mob source data, this resolver must be extended with verified
    level, NPC identity, abilities and their source hashes before certification.
    """
    if int(level) != int(ir.actor.metadata['level']):
        raise ValueError('CHECKPOINT_ENEMY_LEVEL_IR_MISMATCH')
    if int(level) < 1 or int(level) > 60:
        raise ValueError('CHECKPOINT_ENEMY_INVALID_LEVEL')
    profile = load_target_combat_profile(int(level))
    embedded = ir.provenance.get('target_combat_profile')
    if not embedded:
        raise ValueError('CHECKPOINT_ENEMY_IR_TARGET_COMBAT_NOT_SOURCED')
    if (str(embedded['capture_id']) != str(profile['capture_id']) or
        str(embedded['source_status']) != str(profile['source_status']) or
        float(embedded['target_armor']) != float(profile['target_armor'])):
        raise ValueError('CHECKPOINT_ENEMY_IR_DB_PROFILE_MISMATCH')
    hp = float(representative_hp(int(level)))
    if not isfinite(hp) or hp <= 0:
        raise ValueError('CHECKPOINT_ENEMY_MISSING_HP')
    return CheckpointEnemy(
        player_level=int(level), enemy_level=int(level), hp=hp,
        hp_authority='CMANGOS_CLASSLEVEL_BASE_HEALTH_CLASS1_NOT_FOREVER_NPC',
        hp_source_url=HEALTH_SOURCE,
        combat_authority=str(profile['source_status']),
        combat_capture_id=str(profile['capture_id']),
        armor=float(profile['target_armor']), melee_hit=float(profile['melee_hit']),
        spell_hit=float(profile['spell_hit']),
        scenario_key=str(profile['scenario_key']), exact_forever_enemy_verified=False,
    )


def discover_source_damage_seeds(ir, *, max_actions: int = 4) -> tuple[PolicyDefinition, ...]:
    """Generate a bounded APL *screen* from currently legal executable IR.

    This is deliberately not an optimum proof. Any inaccessible damaging
    action is reported by the separate ability-coverage preflight; this
    generator must not quietly certify that its candidate set is complete.
    """
    from src.game.model import DamageEffect
    from src.game.runtime import ActorState, TargetState, action_eligibility
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    target = TargetState.with_health('seed_legality_target', 1.0)
    actions = []
    for action in ir.actions:
        if not any(isinstance(effect, DamageEffect) for effect in action.effects):
            continue
        if not action_eligibility(action=action, actor=actor, target=target).eligible:
            continue
        actions.append(action)
    # Bound by source/IR action ordering rather than a hardcoded Mage or Druid
    # list. Later search can use the full admitted P1 action universe.
    actions = actions[:max_actions]
    seeds=[]
    for action in actions:
        seeds.append(PolicyDefinition(
            id='source_damage_screen:'+action.id,
            label='Source IR single-action probe',
            rules=(PolicyRuleDefinition(id='source:'+action.id,action_id=action.id),),
            provenance={'authority':'generic_executable_source_damage_screen',
                        'complete_apl_search':False}))
    # Include a reusable two-action ordering to discover fallbacks for
    # cooldowns or expensive actions, without class-specific ability names.
    for i in range(len(actions)):
        for j in range(i+1,len(actions)):
            first,second=actions[i],actions[j]
            seeds.append(PolicyDefinition(
                id='source_damage_screen:'+first.id+'+'+second.id,
                label='Source IR two-action probe',
                rules=(PolicyRuleDefinition(id='source:'+first.id,action_id=first.id),
                       PolicyRuleDefinition(id='source:'+second.id,action_id=second.id)),
                provenance={'authority':'generic_executable_source_damage_screen',
                            'complete_apl_search':False}))
    return tuple(seeds)
