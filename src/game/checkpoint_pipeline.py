"""One class-agnostic checkpoint entry point: source admission -> paid 100-mob probe.

A source-based proxy is useful diagnostic evidence, never a certificate for an
exact Forever encounter or an optimized checkpoint. No class, spell or item
allowlists and no caller-supplied HP in the checkpoint interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from time import perf_counter, process_time

from src.shared.leveling.objective import representative_hp
from src.game.data.forever import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
from src.game.data.forever.target_combat_source import load_target_combat_profile
from src.game.data.forever.source_indexed_action_coverage import indexed_ability_coverage
from src.game.model import PolicyDefinition, PolicyRuleDefinition
from src.game.recovery_threshold_search import search_recovery_thresholds


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


def checkpoint_preflight(*, class_key: str, level: int, ir=None) -> dict:
    """Automatic, typed blockers for every class; no manual Mage/Druid toggle.

    P1/P2 accepted L0 certificates are separate from strict executable L2
    coverage. We report the latter instead of silently counting source-indexed
    entries as executable. P3 inventory is NOT a build-specific Top5 certificate.
    """
    if not class_key or not 1 <= int(level) <= 60:
        raise ValueError('CHECKPOINT_INVALID_CLASS_LEVEL')
    if ir is None:
        ir = build_game_ir_slice(class_key=class_key, level=level)
    if ir is None:
        blocker={'scope':'game_ir','code':'NO_EXECUTABLE_GAME_IR_AT_CHECKPOINT',
                 'details':'Class source presence does not imply an executable runtime slice'}
        return {
            'checkpoint':{'class_key':str(class_key).lower(), 'level':int(level),
                          'profile':'unrestricted'},
            'enemy':None, 'class_source_action_inventory':None,
            'equipment_l0_inventory':None, 'incoming_attack_count':None,
            'blockers':[blocker], 'eligible_for_checkpoint_acceptance':False,
            'is_complete_checkpoint':False, 'further_gates':'NOT_EVALUATED_NO_GAME_IR',
        }
    if str(ir.actor.metadata.get('class_key','')).lower() != str(class_key).lower():
        raise ValueError('CHECKPOINT_CLASS_IR_MISMATCH')
    enemy = checkpoint_enemy(ir=ir, level=level)
    indexed = indexed_ability_coverage(ir, class_key=class_key, level=level)
    inventory_error = None
    try:
        inventory = checkpoint_item_l0(class_key=class_key, level=level)
    except ValueError as exc:
        if str(exc) not in ('P3_NO_SOURCE_LEGAL_ITEMS', 'P3_SPEC_PROFILE_REQUIRES_EXPLICIT_EQUIPMENT_RULES'):
            raise
        inventory_error = str(exc)
        inventory = None
    blockers = []
    advisories = []
    if not enemy.exact_forever_enemy_verified:
        blockers.append({'scope':'encounter', 'code':'FOREVER_NAMED_ENEMY_UNVERIFIED',
            'details':'Level-class CMaNGOS HP, armor/hit are explicitly Classic proxies'})
    if not ir.incoming_attacks:
        blockers.append({'scope':'encounter', 'code':'NO_SOURCED_INCOMING_ATTACK_ACTIONS'})
    if indexed['status'] != 'COMPLETE':
        blockers.append({'scope':'abilities', 'code':'INDEXED_L2_ACTION_COVERAGE_INCOMPLETE',
            'indexed_unrepresented':indexed['unrepresented_rank_count'],
            'indexed_total':indexed['indexed_ability_rank_count'],
            'note':'Includes unlearned/uncertain ranks; not equivalent to P1 L0 failure'})
    # PROCESS v2 explicitly removed *complete external class catalogue*
    # attestation as a P3 prerequisite. The currently available legal top-five
    # ilvl items need an actual contextual scoring smoke, which this cheap
    # preflight never performs. That real missing proof remains a blocker.
    if inventory is None or not inventory['source_items']:
        blockers.append({'scope':'equipment', 'code':'P3_NO_AVAILABLE_LEGAL_ITEM_SAMPLE',
            'reason':inventory_error})
    else:
        blockers.append({'scope':'equipment',
            'code':'P3_ILVL_TOP5_CONTEXTUAL_SMOKE_NOT_RUN',
            'sample_count':len(inventory['source_items']),
            'note':'Run source-legal ilvl-top-five by slot and nonnegative meaningful build weights'})
        if not inventory['source_membership_verified']:
            advisories.append({'scope':'equipment',
                'code':'SOURCE_CLASS_ITEM_MEMBERSHIP_UNATTESTED_ADVISORY',
                'note':'Improve external catalogue coverage, but PROCESS v2 does not make it a P3 gate'})
        if inventory['missing_required_slots']:
            advisories.append({'scope':'equipment',
                'code':'SOURCE_ITEM_SLOTS_NOT_YET_OBSERVED_ADVISORY',
                'slots':list(inventory['missing_required_slots'])})
    from src.game.talent_execution_coverage import compile_talent_runtime
    _, talent_coverage = compile_talent_runtime(ir)
    blockers.append({'scope':'talents',
        'code':('L2_TALENT_RANK_EXECUTION_INCOMPLETE' if talent_coverage['rank_missing_executor']
                else 'L2_TALENT_EXECUTION_NOT_CERTIFIED_BY_PREFLIGHT'),
        'ranks_missing_executor':talent_coverage['rank_missing_executor'],
        'ranks_with_modifiers':talent_coverage['rank_with_modifiers'],
        'details':'All-class source-rank coverage check; even every rank having modifiers is not full L2 proof'})
    blockers.append({'scope':'search', 'code':'JOINT_BUILD_OPTIMUM_NOT_CERTIFIED',
        'details':'Must optimize gear, talent, APL, recovery and verify 100 mobs with independent challenger'})
    return {
        'checkpoint': {'class_key':str(class_key).lower(),'level':int(level),'profile':'unrestricted'},
        'enemy':enemy.as_dict(),
        'class_source_action_inventory': {
            'indexed_ranks':indexed['indexed_ability_rank_count'],
            'exact_rank_matches_in_ir':indexed['exact_source_rank_in_ir_count'],
            'unrepresented_ranks':indexed['unrepresented_rank_count'],
            'l2_coverage_status':indexed['status'],
            'index_is_not_legal_spellbook':True,
        },
        'equipment_l0_inventory': {
            'legal_items':None if inventory is None else inventory['legal_item_count'],
            'slots':None if inventory is None else len(inventory['slot_frontiers']),
            'unknown_item_effects':None if inventory is None else inventory['unknown_effect_item_count'],
            'source_membership_verified':False if inventory is None else inventory['source_membership_verified'],
            'l0_universe_pass':False if inventory is None else inventory['p3_pass'],
            'is_build_specific_top5':False,
        },
        'incoming_attack_count':len(ir.incoming_attacks),
        'talent_execution_coverage':{k:v for k,v in talent_coverage.items() if k!='missing'},
        'blockers':blockers,'advisories':advisories,
        'eligible_for_checkpoint_acceptance':not blockers,
        'is_complete_checkpoint':False,
    }


def checkpoint_recovery_probe(*, class_key: str, level: int, policy: PolicyDefinition,
                              ir=None, health_fractions: tuple[float,...] = (0.5,),
                              mana_fractions: tuple[float,...] = (0.1,0.3,0.6)) -> dict:
    """Pay the 100-mob objective in the canonical CombatRuntime with NO HP knob.

    This does not optimize talent/gear/APL, and is strictly a diagnostic even if
    all 100 mobs die. Incoming attacks and defense are always ON; they cannot
    be disabled through caller kwargs or mistaken for a certified scenario.
    """
    if ir is None:
        ir = build_game_ir_slice(class_key=class_key, level=level)
    preflight = checkpoint_preflight(class_key=class_key, level=level, ir=ir)
    enemy = preflight['enemy']
    if not ir.incoming_attacks:
        return {'preflight':preflight,'status':'BLOCKED_NO_INCOMING_ATTACKS',
                'eligible_for_checkpoint_acceptance':False}
    start_wall, start_cpu = perf_counter(), process_time()
    result = search_recovery_thresholds(
        ir_slice=ir, policy=policy, level=level, target_health=float(enemy['hp']),
        count=100, pack_size=1, schedule_incoming_attacks=True,
        apply_target_defense=True,
        health_fractions=health_fractions, mana_fractions=mana_fractions,
    )
    return {'preflight':preflight, 'enemy':enemy, 'search':result,
        'status':'SOURCE_PROXY_DIAGNOSTIC' if result['best'] else 'NO_SURVIVING_CANDIDATE',
        'objective_mobs':100, 'defense_applied':True, 'incoming_enabled':True,
        'diagnostic_only':True, 'eligible_for_checkpoint_acceptance':False,
        'elapsed_wall_s':perf_counter()-start_wall,'elapsed_cpu_s':process_time()-start_cpu}


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


def checkpoint_auto_screen(*, class_key: str, level: int, max_policies: int = 6) -> dict:
    """Run class-independent real 100-mob recovery/APL screen and retain failures.

    All candidates use the same sourced enemy and paid recovery, including
    armor, enemy swings, and real carried health/mana. No generated policies
    are claimed as exhaustive and no checkpoint counter is incremented.
    """
    if type(max_policies) is not int or not 1 <= max_policies <= 16:
        raise ValueError('INVALID_SCREEN_BUDGET')
    ir=build_game_ir_slice(class_key=class_key,level=level)
    preflight=checkpoint_preflight(class_key=class_key,level=level,ir=ir)
    if preflight['enemy'] is None:
        return {'checkpoint':preflight['checkpoint'],'preflight':preflight,
                'status':'BLOCKED_NO_EXECUTABLE_GAME_IR',
                'candidates':[], 'best':None,'eligible_for_checkpoint_acceptance':False}
    seeds=discover_source_damage_seeds(ir)
    if not seeds:
        return {'checkpoint':preflight['checkpoint'],'preflight':preflight,
            'status':'BLOCKED_NO_LEGAL_DIRECT_DAMAGE_SEED',
            'failure_detail':'Generic seed generator does not currently include autoattack/form-entry/rage builders',
            'candidates':[],'best':None,'eligible_for_checkpoint_acceptance':False}
    rows=[]
    for policy in seeds[:max_policies]:
        run=checkpoint_recovery_probe(class_key=class_key,level=level,policy=policy,ir=ir,
            health_fractions=(0.5,),mana_fractions=(0.1,))
        result=run['search']
        rows.append({'policy_id':policy.id,
            'action_ids':[r.action_id for r in policy.rules],
            'status':result['status'],
            'best':result['best'],
            'candidates':result['candidates'],
            'elapsed_wall_s':run['elapsed_wall_s']})
    wins=[x for x in rows if x['best']]
    best=min(wins,key=lambda x:(float(x['best']['seconds_per_mob']),x['policy_id'])) if wins else None
    return {'checkpoint':preflight['checkpoint'],'preflight':preflight,
        'status':'SCREENED_SOURCE_PROXY' if best is not None else 'NO_100MOB_SURVIVING_SEED',
        'enemy':preflight['enemy'],'mobs':100,
        'seed_policy_count':len(seeds), 'tested_policy_count':len(rows),
        'candidates':rows,'best':best,
        'diagnostic_only':True,'complete_apl_search':False,
        'complete_gear_talent_search':False,
        'eligible_for_checkpoint_acceptance':False}
