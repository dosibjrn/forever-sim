"""Fail-closed, class-neutral compilation of versioned L0 talent effect clauses.

The source observations own all class/spell facts. This compiler only knows
semantic effect types and the GameIR's actual action families, damage schools
and actor stats. A whole rank is executed or not executed: never drop a clause.
"""
from __future__ import annotations

from dataclasses import replace
from math import isfinite

from src.game.model.ir import TalentModifier

# Semantic operators, not class/talent/spell fact tables. All unlisted domains
# stay L0-only until the generic runtime can execute them faithfully.
_PERCENT_OPERATORS = {
    'spell_hit_bonus_pct': ('hit_chance_bonus', 1),
    'critical_chance_bonus_pct': ('crit_chance_pct', 1),
    'mana_cost_reduction_pct': ('resource_cost_pct', -1),
    'threat_reduction_pct': ('threat_factor_pct', -1),
    'critical_damage_bonus_pct': ('critical_damage_bonus_pct', 1),
}

_STAGED_FRACTION_SEMANTICS = {
    'spell_critical_damage_bonus_fraction': 'critical_damage_bonus_pct',
    'spell_threat_reduction_fraction': 'threat_reduction_pct',
}


def _school_scope(target: str, schools: set[str]) -> str | None:
    """A versioned target like frost_and_fire_spells -> GameIR school filter.

    Do not infer arbitrary target names; every listed school must exist in IR.
    """
    if not target.endswith('_spells'):
        return None
    tokens = target[:-7].split('_and_')
    if not tokens or any(token not in schools for token in tokens):
        return None
    return 'damage_schools:' + ','.join(tokens)


def _compile_avoidance_clause(effect: dict, *, actor_stats: set[str],
                              provenance: dict):
    """Convert sourced avoidance observations without talent/class switches."""
    domain = effect['domain']
    target = effect['target']
    value = effect['sourced_value']
    condition = effect['condition']
    if (domain == 'dodge_bonus_pct' and target == 'dodge_chance'
            and target in actor_stats and condition == 'passive'
            and value <= 100.):
        return TalentModifier(kind='actor_stat_flat',target_type='actor_stat',
                              target_id=target,value=float(value)/100.,
                              provenance=provenance)
    if (domain == 'avoidance_resource_proc_chance_pct' and condition == 'on_dodge'
            and 'dodge_chance' in actor_stats and value <= 100.
            and isinstance(effect.get('gain_amount'), (int,float))
            and not isinstance(effect.get('gain_amount'), bool)
            and isfinite(effect['gain_amount']) and effect['gain_amount'] > 0.
            and type(effect.get('source_build_verified')) is bool
            and type(effect.get('proc_distribution_verified')) is bool):
        provenance.update(gain_amount=float(effect['gain_amount']),
                          source_build_verified=effect['source_build_verified'],
                          proc_distribution_verified=effect['proc_distribution_verified'])
        return TalentModifier(kind='avoidance_resource_proc',target_type='resource',
                              target_id=target,value=float(value)/100.,
                              provenance=provenance)
    return None


def _compile_clause(effect: dict, *, actions: set[str], schools: set[str],
                    actor_stats: set[str], build: str):
    domain = effect.get('domain')
    target = effect.get('target')
    value = effect.get('sourced_value')
    url = effect.get('source')
    condition = effect.get('condition')
    if (not isinstance(domain, str) or not isinstance(target, str)
            or not isinstance(value, (int, float)) or isinstance(value, bool)
            or not isfinite(value) or value < 0
            or not isinstance(url, str) or not url.startswith('https://')
            or not isinstance(condition, str) or not condition):
        return None
    provenance = {'authority': 'source_l0_semantic_compiler_experimental',
                  'url': url, 'source_build': build,
                  'source_domain': domain, 'source_condition': condition}
    if domain == 'cast_time_reduction_s' and target in actions:
        return TalentModifier(kind='cast_time_delta_s', target_type='action_family',
                              target_id=target, value=-float(value), provenance=provenance)
    if domain == 'wand_damage_pct' and target == 'wand' and 'wand_dps' in actor_stats:
        return TalentModifier(kind='actor_stat_pct', target_type='actor_stat',
                              target_id='wand_dps', value=float(value) / 100, provenance=provenance)
    if (domain == 'actor_stat_bonus_pct' and target in actor_stats
            and condition == 'passive'):
        return TalentModifier(kind='actor_stat_pct', target_type='actor_stat',
                              target_id=target, value=float(value) / 100,
                              provenance=provenance)
    avoidance = _compile_avoidance_clause(effect, actor_stats=actor_stats,
                                         provenance=provenance)
    if avoidance is not None:
        return avoidance
    if (domain == 'critical_chance_bonus_pct' and target in actions
            and condition == 'passive'):
        return TalentModifier(kind='crit_chance_pct', target_type='action_family',
                              target_id=target, value=float(value) / 100,
                              provenance=provenance)
    scope = _school_scope(target, schools)
    if scope is None:
        return None
    if domain in _PERCENT_OPERATORS:
        kind, sign = _PERCENT_OPERATORS[domain]
        # Threat is currently only meaningful for single-player encounters;
        # record the execution constraint, never claim multiparty parity.
        if kind == 'threat_factor_pct':
            provenance['threat_scope'] = 'single_actor_solo_no_competing_threat_only'
        return TalentModifier(kind=kind, target_type='action_filter',
                              target_id=scope, value=sign * float(value) / 100,
                              provenance=provenance)
    prefix, damage_kind = domain.split('_', 1) if '_' in domain else ('', '')
    if prefix not in schools:
        return None
    if damage_kind == 'damage_bonus_pct':
        kind = 'effect_damage_pct'
    elif damage_kind == 'critical_damage_bonus_pct':
        kind = 'critical_damage_bonus_pct'
    else:
        return None
    if prefix not in scope.removeprefix('damage_schools:').split(','):
        return None
    return TalentModifier(kind=kind, target_type='action_filter', target_id=scope,
                          value=float(value) / 100, provenance=provenance)


def _staged_fraction_clause(capture: dict, *, source_build: str | None,
                            actions: set[str], schools: set[str], actor_stats: set[str]):
    """Compile a complete, version-matched one-clause fraction from SQLite.

    The staged 70338 schema stores an explicit typed domain and fraction,
    whereas the later source-positions schema stores a list of percent clauses.
    This adapter is semantic and class-neutral; it never interprets tooltip
    strings, infers a talent ID, or discards a second sourced effect.
    """
    domain = capture.get('effect_domain')
    target = capture.get('target')
    fraction = capture.get('value')
    build = capture.get('source_build')
    if (not isinstance(domain, str) or not isinstance(target, str)
            or not isinstance(source_build, str) or build != source_build
            or capture.get('additional_effect_domain') is not None
            or capture.get('additional_target') is not None
            or capture.get('additional_value') is not None
            or not isinstance(fraction, (int, float)) or isinstance(fraction, bool)
            or not isfinite(fraction) or not 0. < fraction <= 1.):
        return None
    normalized = _STAGED_FRACTION_SEMANTICS.get(domain)
    if (normalized is None and domain.endswith('_stat_increase_fraction')
            and domain[:-len('_stat_increase_fraction')] == target
            and target in actor_stats):
        normalized = 'actor_stat_bonus_pct'
    if domain == 'casting_pushback_avoidance_probability':
        # Exact source target `arcane_and_nature_casts`; the compiler only
        # understands effect schools, never a class or ability allowlist.
        if not target.endswith('_casts'):
            return None
        cast_schools = target[:-6].split('_and_')
        if not cast_schools or any(school not in schools for school in cast_schools):
            return None
        url = capture.get('source_url')
        if not isinstance(url, str) or not url.startswith('https://'):
            return None
        return TalentModifier(kind='cast_pushback_avoidance_chance',
            target_type='action_filter', target_id='damage_schools:' + ','.join(cast_schools),
            value=float(fraction), provenance={
                'authority':'source_l0_staged_probability', 'url':url,
                'source_build':source_build, 'source_domain':domain,
                'source_target':target,
                'baseline_cast_pushback_seconds':'REQUIRES_SEPARATELY_SOURCED_INCOMING_PROFILE',
            })
    if normalized is None:
        return None
    clause = {'domain': normalized, 'target': target,
              'sourced_value': float(fraction) * 100.,
              'condition': 'passive', 'source': capture.get('source_url')}
    return _compile_clause(clause, actions=actions, schools=schools,
                           actor_stats=actor_stats, build=source_build)


def _staged_control_target_cap_clause(capture: dict, *, source_build: str | None,
                                      action_caps: dict[str, dict]):
    """Compile a rank-specific target-cap bonus only with an attested base cap."""
    family=capture.get('target')
    fact=action_caps.get(family) if isinstance(family,str) else None
    value=capture.get('value')
    if (capture.get('source_build') != source_build
            or capture.get('effect_domain') != 'extra_concurrent_rooted_targets'
            or capture.get('additional_effect_domain') is not None
            or capture.get('additional_value') is not None
            or not fact or fact.get('source_build') != source_build
            or type(value) not in (int,float) or not isfinite(value)
            or not float(value).is_integer() or not 0 < value <= 16
            or int(fact.get('base_max_targets',0))+int(value)>16
            or not str(capture.get('source_url','')).startswith('https://')):
        return None
    return TalentModifier(kind='control_target_cap_bonus',target_type='action_family',
        target_id=family,value=float(value),provenance={
            'authority':'source_pinned_control_target_cap',
            'source_build':source_build,'source_url':capture['source_url'],
            'base_source_url':fact['base_source_url'],
            'base_max_targets':fact['base_max_targets'],
            'control_id':fact['control_id'],'source_domain':capture['effect_domain']})


def _staged_charge_exchange_clause(capture: dict, *, source_build: str | None,
                                   actions: set[str]):
    """Compile source-pinned producer/consumer charge facts, never a static cast buff.

    A staged reduction number alone does not establish charge count, duration,
    or the generator. All must be separately attested by the exact-build DB.
    """
    producer=capture.get('charge_producer_family')
    consumer=capture.get('charge_consumer_family')
    target=capture.get('target')
    domain=capture.get('effect_domain')
    value=capture.get('value')
    count=capture.get('charge_grant_per_cast')
    cap=capture.get('charge_capacity')
    duration=capture.get('charge_duration_s')
    url=capture.get('source_url')
    if (capture.get('source_build') != source_build
            or not isinstance(source_build,str)
            or not isinstance(producer,str) or not isinstance(consumer,str)
            or not producer or not consumer or producer==consumer
            or producer not in actions or consumer not in actions
            or target != producer+'_then_'+consumer
            or domain != consumer+'_cast_time_reduction_seconds_per_charge'
            or capture.get('additional_effect_domain') is not None
            or capture.get('additional_value') is not None
            or type(count) is not int or type(cap) is not int
            or not 0 < count <= cap <= 16
            or not isinstance(duration,(int,float)) or isinstance(duration,bool)
            or not isfinite(duration) or not 0 < duration <= 120
            or not isinstance(value,(int,float)) or isinstance(value,bool)
            or not isfinite(value) or not 0 < value <= 10
            or not isinstance(url,str) or not url.startswith('https://')
            or capture.get('charge_source_url') != url
            or not str(capture.get('charge_source_basis_url','')).startswith('https://')):
        return None
    return TalentModifier(kind='cast_charge_exchange',target_type='action_family',
        target_id=consumer,value=float(value),provenance={
            'authority':'source_pinned_cast_charge_exchange',
            'source_build':source_build,'source_url':url,
            'source_basis_url':capture['charge_source_basis_url'],
            'producer_family':producer,'consumer_family':consumer,
            'bank_id':'source_cast_charges:'+producer+':'+consumer,
            'grant_per_cast':count,'capacity':cap,'duration_s':float(duration),
            'source_domain':domain})


def _staged_compound_control_clauses(capture: dict, *, source_build: str | None,
                                     actions: set[str]):
    """Translate a complete sourced action-cast reduction + control proc pair.

    The source observation owns the target family and probability; a separate
    version-matched SQLite fact owns the control duration. Never infer either.
    """
    target=capture.get('target')
    if (not isinstance(target,str) or target not in actions
            or capture.get('source_build') != source_build
            or capture.get('effect_domain') != target+'_cast_time_reduction_seconds'
            or not isinstance(capture.get('additional_control_id'),str)
            or not capture['additional_control_id'].replace('_','').isalpha()
            or capture.get('additional_effect_domain') !=
                target+'_'+capture['additional_control_id']+'_chance'
            or capture.get('additional_target') != target
            or type(capture.get('additional_control_prevents_enemy_actions')) is not bool
            or type(capture.get('additional_control_breaks_on_damage')) is not bool
            or capture.get('additional_control_source_url') != capture.get('source_url')):
        return None
    reduction=capture.get('value');chance=capture.get('additional_value')
    duration=capture.get('additional_control_duration_s')
    if (any(not isinstance(v,(int,float)) or isinstance(v,bool) or not isfinite(v)
            for v in (reduction,chance,duration))
            or not 0. < reduction <= 10. or not 0. < chance <= 1.
            or not 0. < duration <= 60.):
        return None
    url=capture.get('source_url')
    if not isinstance(url,str) or not url.startswith('https://'):
        return None
    prov={'authority':'source_staged_compound_control', 'url':url,
          'source_build':source_build, 'source_target':target,
          'control_id':capture['additional_control_id'], 'duration_s':float(duration),
          'prevents_enemy_actions':capture['additional_control_prevents_enemy_actions'],
          'breaks_on_damage':capture['additional_control_breaks_on_damage'],
          'source_domain':capture['additional_effect_domain']}
    return [TalentModifier(kind='cast_time_delta_s',target_type='action_family',
                target_id=target,value=-float(reduction),provenance=prov),
            TalentModifier(kind='action_control_proc',target_type='action_family',
                target_id=target,value=float(chance),provenance=prov)]


def _staged_verified_source_url(capture: dict, source_build: str | None) -> str | None:
    """Shared fail-closed provenance check for staged typed source effects."""
    url = capture.get('source_url')
    if (not isinstance(source_build, str) or capture.get('source_build') != source_build
            or not isinstance(url, str) or not url.startswith('https://')):
        return None
    return url


def _staged_melee_crit_and_stat_healing(capture: dict, *, source_build: str | None,
                                       actor_stats: set[str]):
    """An indivisible source pair: melee ability crit bonus + healing from a stat.

    The stat name comes from the typed domain, never from a class/talent ID.
    A partially matched tooltip is *not* an executable rank.
    """
    domain = capture.get('additional_effect_domain')
    prefix, suffix = 'spell_healing_from_', '_fraction'
    if not isinstance(domain, str) or not domain.startswith(prefix) or not domain.endswith(suffix):
        return None
    source_stat = domain[len(prefix):-len(suffix)]
    crit = capture.get('value')
    healing = capture.get('additional_value')
    url = _staged_verified_source_url(capture, source_build)
    if (url is None
            or capture.get('effect_domain') != 'melee_critical_damage_bonus_fraction'
            or capture.get('target') != 'melee_abilities'
            or capture.get('additional_target') != 'healing_spells'
            or source_stat not in actor_stats
            or any(type(v) not in (float, int) or not isfinite(v) or not 0 < v <= 1
                   for v in (crit, healing))):
        return None
    provenance = {'authority': 'source_pinned_compound_crit_healing',
                  'source_build': source_build, 'source_url': url,
                  'source_domains': [capture['effect_domain'], domain]}
    return [TalentModifier(kind='critical_damage_bonus_pct',
                          target_type='action_filter', target_id='melee_ability',
                          value=float(crit), provenance=provenance),
            TalentModifier(kind='healing_power_from_stat', target_type='actor_stat',
                          target_id='healing_power', value=float(healing),
                          provenance={**provenance, 'source_stat': source_stat})]


def _staged_form_crit_bonus(capture: dict, *, source_build: str | None,
                            modes: set[str]):
    """A form-scoped player component of a party crit aura.

    Other party members are not silently represented as actors. At this level,
    only forms present in GameIR are executable; future forms remain unclaimed.
    """
    target = capture.get('target')
    fraction = capture.get('value')
    url = _staged_verified_source_url(capture, source_build)
    if (url is None
            or capture.get('effect_domain') != 'form_party_crit_chance_fraction'
            or not isinstance(target, str) or not target.startswith('party_')
            or capture.get('additional_effect_domain') is not None
            or capture.get('additional_value') is not None
            or type(fraction) not in (float, int) or not isfinite(fraction)
            or not 0 < fraction <= 1):
        return None
    declared = target.removeprefix('party_').split('_')
    present = [mode for mode in declared if mode in modes]
    if not present or len(set(declared)) != len(declared) or not all(declared):
        return None
    provenance = {'authority': 'source_pinned_form_crit_player_only',
                  'source_build': source_build, 'source_url': url,
                  'source_modes': tuple(declared),
                  'unsupported_party_scope': 'PARTY_MEMBERS_AND_EXCLUSIVE_AURA_NOT_EXECUTED'}
    return [TalentModifier(kind='mode_stat_flat', target_type='mode',
                           target_id=mode, value=float(fraction),
                           provenance={**provenance, 'target_stat': stat})
            for mode in present for stat in ('melee_crit_chance', 'spell_crit_chance')]


def _staged_critical_resource_pair(capture: dict, *, source_build: str | None,
                                   resources: set[str], modes: set[str]):
    """Two independently activated on-crit resource gains, always atomic.

    Chance comes from the exact-build source talent rank; flat resource amounts
    come from a separately versioned DB fact. A cross-build amount retains an
    explicit uncertified marker, rather than being silently treated as 70338.
    """
    fact=capture.get('critical_resource_source')
    url=_staged_verified_source_url(capture,source_build)
    if (not isinstance(fact,dict) or url is None or
            capture.get('effect_domain')!='critical_bear_rage_proc_probability' or
            capture.get('target')!='bear_direbear' or
            capture.get('additional_effect_domain')!=
                'critical_cat_bonus_combo_point_proc_probability' or
            capture.get('additional_target')!='cat_combo_generators' or
            fact.get('target_build')!=source_build or
            not str(fact.get('source_url','')).startswith('https://') or
            fact.get('source_url')!=url or
            not str(fact.get('resource_amount_source_url','')).startswith('https://') or
            not isinstance(fact.get('resource_amount_source_build'),str) or
            not isinstance(fact.get('resource_bridge_verified'),int) or
            fact['resource_bridge_verified'] not in (0,1) or
            ('bear' not in modes or 'cat' not in modes)):
        return None
    bear_resource,cat_resource=fact.get('bear_resource'),fact.get('cat_resource')
    bear_amount,cat_amount=fact.get('bear_amount'),fact.get('cat_amount')
    bear_chance,cat_chance=capture.get('value'),capture.get('additional_value')
    if (bear_resource not in resources or cat_resource not in resources or
            any(type(v) not in (float,int) or not isfinite(v) or
                not 0 < v <= 100 for v in (bear_amount,cat_amount)) or
            any(type(v) not in (float,int) or not isfinite(v) or
                not 0 < v <= 1 for v in (bear_chance,cat_chance))):
        return None
    prov={'authority':'source_pinned_critical_resource_pair',
          'source_build':source_build,'source_url':url,
          'resource_amount_source_url':fact['resource_amount_source_url'],
          'resource_amount_source_build':fact['resource_amount_source_build'],
          'source_domains':(capture['effect_domain'],capture['additional_effect_domain']),
          'unsupported_expected_value_distribution':
              'FRACTIONAL_COMBO_POINTS_ARE_NOT_EXACT_DISCRETE_PROC_DISTRIBUTION'}
    if not fact['resource_bridge_verified']:
        prov['unsupported_build_bridge']='CRITICAL_RESOURCE_AMOUNT_NOT_VERIFIED_IN_TARGET_BUILD'
    return [TalentModifier(kind='critical_resource_gain',target_type='resource',
            target_id=str(bear_resource),value=float(bear_chance),provenance={**prov,
            'required_mode_id':'bear','bonus_resource_amount':float(bear_amount),
            'requires_resource_generator':False}),
        TalentModifier(kind='critical_resource_gain',target_type='resource',
            target_id=str(cat_resource),value=float(cat_chance),provenance={**prov,
            'required_mode_id':'cat','bonus_resource_amount':float(cat_amount),
            'requires_resource_generator':True})]


def _staged_resource_action_grant(capture: dict, *, source_build: str | None,
                                  resources: set[str], modes: set[str], actor_stats: set[str]):
    """Compile only complete, sourced instant conversion actions as one grant.

    No ability/class numeric values live in the executor. The value/cost/mode
    belong to an explicit SQLite fact with separate original-build authority.
    """
    fact=capture.get('resource_action_source')
    url=_staged_verified_source_url(capture, source_build)
    if (not isinstance(fact,dict) or url is None or
            capture.get('effect_domain')!='on_use_energy_restoration' or
            capture.get('additional_effect_domain') is not None or
            capture.get('additional_value') is not None or
            capture.get('target')!=fact.get('family_key') or
            fact.get('source_build')!=source_build or
            fact.get('resource_id') not in resources or
            fact.get('required_mode_id') not in modes or
            fact.get('cost_resource_id') not in resources or
            not isinstance(fact.get('cost_reduction_group'),str) or
            not fact['cost_reduction_group'] or
            not str(fact.get('source_url','')).startswith('https://') or
            not str(fact.get('mechanics_source_url','')).startswith('https://') or
            not isinstance(fact.get('mechanics_source_build'),str) or
            fact.get('bridge_verified') not in (0,1)):
        return None
    names=('resource_gain','base_resource_cost_fraction','gcd_s','cooldown_s')
    if any(type(fact.get(n)) not in (int,float) or
           not isfinite(fact[n]) for n in names):
        return None
    if (not 0.<float(fact['resource_gain'])<=1000. or
        not 0.<float(fact['base_resource_cost_fraction'])<=1. or
        not 0.<=float(fact['gcd_s'])<=5. or
        not 0.<float(fact['cooldown_s'])<=3600. or
        int(fact.get('spell_id',0))<=0 or
        float(capture.get('value',0))!=float(fact['resource_gain']) or
        fact.get('must_have_room') not in (0,1)):
        return None
    prov={'authority':'source_pinned_instant_resource_action',
          'source_build':source_build,'source_url':url,
          'mechanics_source_build':fact['mechanics_source_build'],
          'mechanics_source_url':fact['mechanics_source_url'],
          'source_action_fact':fact}
    if not fact['bridge_verified']:
        prov['unsupported_build_bridge']='INSTANT_RESOURCE_MECHANICS_NOT_REVERIFIED_AT_TARGET_BUILD'
    return TalentModifier(kind='grant_source_resource_action',target_type='action_family',
                          target_id=fact['family_key'],value=float(fact['resource_gain']),
                          provenance=prov)


def _staged_action_cooldown_reduction(capture: dict, *, source_build: str | None):
    target=capture.get('target')
    value=capture.get('value')
    url=_staged_verified_source_url(capture,source_build)
    if (url is None or not isinstance(target,str) or not target or
            capture.get('effect_domain') != target+'_cooldown_reduction_seconds' or
            capture.get('additional_effect_domain') is not None or
            capture.get('additional_value') is not None or
            capture.get('condition') != 'when_'+target+'_learned' or
            type(value) not in (int,float) or not isfinite(value) or
            not 0.<value<=3600.):
        return None
    return TalentModifier(kind='cooldown_delta_s',target_type='action_family',
                          target_id=target,value=-float(value),provenance={
        'authority':'source_pinned_action_cooldown_reduction',
        'source_build':source_build,'source_url':url,
        'source_domain':capture['effect_domain']})



def _staged_compound_control_duration_cooldown(capture:dict, *,source_build:str|None,
                                               actions:dict):
    """Atomic typed rank: extend named control ability families and reduce CD.

    Future-tier control families need not be trained at the current level.
    Fail closed unless at least one named control action exists and the
    cooldown target has a real executing action in the compiled GameIR.
    """
    url=_staged_verified_source_url(capture,source_build)
    families=capture.get('target','').split('_and_') if isinstance(capture.get('target'),str) else []
    cd_target=capture.get('additional_target')
    delta=capture.get('value');reduce=capture.get('additional_value')
    if (url is None or len(families)<1 or len(set(families))!=len(families) or
            any(not str(k).replace('_','').isalpha() for k in families) or
            capture.get('effect_domain')!='stun_duration_bonus_seconds' or
            capture.get('additional_effect_domain')!=str(cd_target)+'_cooldown_reduction_seconds' or
            capture.get('condition')!='control_ability_available' or
            cd_target not in families or
            type(delta) not in (float,int) or not 0<float(delta)<=60 or
            type(reduce) not in (float,int) or not 0<float(reduce)<=3600 or
            not actions.get(cd_target)):
        return None
    checked=[a for a in actions[cd_target]
             if a.metadata.get('source_semantic_type')=='direct_control' and
                a.metadata.get('source_build_bridge_verified') is False and
                any(e.effect_type=='control' and e.control_id=='stun' for e in a.effects)]
    if not checked:return None
    prov={'authority':'source_compound_control_duration_cooldown',
          'source_build':source_build,'source_url':url,
          'source_domains':(capture['effect_domain'],capture['additional_effect_domain']),
          'source_target_families':families,
          'unsupported_build_bridge':'CONTROL_ABILITY_MECHANICS_FROM_NEWER_SOURCE_BUILD',
          'unsupported_future_action_scope':'TARGET_FAMILY_NOT_YET_LEGAL_AT_CURRENT_LEVEL'}
    return [TalentModifier(kind='control_duration_delta_s',target_type='action_family_group',
            target_id=','.join(families),value=float(delta),provenance=prov),
            TalentModifier(kind='cooldown_delta_s',target_type='action_family',
            target_id=cd_target,value=-float(reduce),provenance=prov)]


def _staged_spatial_charge_grant(capture:dict, *,source_build:str|None,modes:set[str]):
    fact=capture.get('spatial_charge_action_source')
    url=_staged_verified_source_url(capture,source_build)
    if (url is None or not isinstance(fact,dict) or
            capture.get('effect_domain')!='charge_immobilize_interrupt_seconds' or
            capture.get('target')!=fact.get('talent_effect_target') or
            capture.get('value')!=fact.get('root_duration_s') or
            capture.get('additional_effect_domain') is not None or
            capture.get('additional_value') is not None or
            fact.get('source_build')!=source_build or
            fact.get('source_build_verified') is not False or
            not isinstance(fact.get('forms'),list) or len(fact['forms'])!=2 or
            len({x.get('mode_id') for x in fact['forms']})!=2 or
            not all(x.get('mode_id') in modes for x in fact['forms']) or
            not str(fact.get('source_url','')).startswith('https://')):
        return None
    return TalentModifier(kind='grant_source_spatial_charge_actions',
        target_type='action_family',target_id=fact['family_key'],value=1.,
        provenance={'authority':'source_index_spatial_charge_grant',
            'source_build':source_build,'source_url':url,
            'source_action_fact':fact,
            'unsupported_build_bridge':'SPATIAL_ABILITY_CLIENT_BUILD_BRIDGE_UNVERIFIED',
            'unsupported_interrupt_cast':'ENEMY_SPELL_CAST_INTERRUPT_RUNTIME_NOT_CERTIFIED',
            'unsupported_target_orientation':'ENEMY_FACING_AND_BEHIND_PROXY',
            'unsupported_out_of_2d':'SOLO_SPATIAL_CHARGE_NOT_MODELED'})


def _staged_active_periodic_full_heal_grant(capture: dict, *, source_build: str | None,
                                             actions: dict, modes: set[str]):
    fact=capture.get('active_periodic_heal_action_source')
    url=_staged_verified_source_url(capture,source_build)
    if (url is None or not isinstance(fact,dict)
            or capture.get('effect_domain')!='instant_hot_full_remaining_heal_multiplier'
            or capture.get('target')!=fact.get('talent_effect_target')
            or capture.get('condition')!='requires_active_regrowth_or_rejuvenation'
            or capture.get('additional_effect_domain') is not None
            or capture.get('additional_value') is not None
            or capture.get('value')!=1.0
            or fact.get('required_mode_id') not in modes
            or fact.get('source_build_verified') is not False
            or fact.get('source_build')!=source_build
            or not 0 < fact.get('base_mana_cost_fraction',0) <= 1
            or not 0 < fact.get('cooldown_s',0) <= 3600
            or fact.get('cast_time_s')!=0
            or not 0 < fact.get('gcd_s',0) <= 10
            or not str(fact.get('source_url','')).startswith('https://')
            or not isinstance(fact.get('source_families'),list)
            or len(fact['source_families'])<1
            or not all(family in actions and any(
                any(type(e).__name__=='PeriodicHealEffect' for e in a.effects)
                for a in actions[family]) for family in fact['source_families'])):
        return None
    return TalentModifier(kind='grant_source_active_periodic_full_heal',
        target_type='action_family',target_id=fact['family_key'],value=1.,
        provenance={'authority':'source_index_active_periodic_full_heal',
                    'source_build':source_build,'source_url':url,
                    'source_action_fact':fact,
                    'unsupported_build_bridge':'INDEX_SOURCE_70338_NOT_CLIENT_BUILD_VERIFIED',
                    'unsupported_multi_hot_selection':'FULL_DURATION_MULTIPLE_HOT_PRIORITY_NOT_SOURCE_ATTESTED',
                    'unsupported_healing_snapshot':'HOT_HEALING_POWER_AT_APPLICATION_NOT_ATTESTED'})


def _staged_next_cast_instant_grant(capture: dict, *, source_build: str | None,
                                    modes: set[str]):
    """Compile one exact typed rank to a talent-granted instant-next-cast action.

    Action numeric facts are in source observation JSON in the SQLite, and a
    newer-build observation remains an explicit semantic acceptance blocker.
    """
    fact=capture.get('next_cast_action_source')
    url=_staged_verified_source_url(capture,source_build)
    if (url is None or not isinstance(fact,dict) or
            capture.get('effect_domain')!='instant_next_nature_cast_count' or
            capture.get('target')!=fact.get('source_talent_target') or
            capture.get('condition')!='active_and_cast' or
            capture.get('additional_effect_domain') is not None or
            capture.get('additional_value') is not None or
            type(capture.get('value')) not in (float,int) or
            capture['value']!=fact.get('next_cast_count') or
            fact.get('required_mode_id') not in modes or
            fact.get('source_mechanics_version_verified') is not False or
            fact.get('source_index_kind')!='talents' or
            fact.get('next_cast_count')!=1 or
            fact.get('self_cast') is not True or
            fact.get('cost_resource_id') is not None or fact.get('cost_amount')!=0 or
            fact.get('gcd_s')!=0 or
            type(fact.get('cooldown_s')) not in (int,float) or
            not 0 < float(fact['cooldown_s']) <=3600 or
            not isinstance(fact.get('spell_school'),str) or
            not str(fact.get('source_url','')).startswith('https://') or
            not str(fact.get('mechanics_source_url','')).startswith('https://') or
            type(fact.get('spell_id')) is not int or fact['spell_id']<=0):
        return None
    return TalentModifier(kind='grant_source_next_cast_instant_action',
         target_type='action_family',target_id=fact['family_key'],value=1.0,
         provenance={'authority':'source_index_next_cast_instant_grant',
             'source_build':source_build,'source_url':url,
             'source_action_fact':fact,
             'unsupported_build_bridge':'NEXT_INSTANT_COOLDOWN_GCD_MECHANICS_NOT_AT_70338',
             'unsupported_heal_school_binding':'HEAL_ONLY_ACTIONS_NEED_VERIFIED_NATURE_SCHOOL'})


def _staged_timed_spell_crit_haste(capture: dict, *, source_build: str | None):
    """Generic, complete source-typed crit -> temporary cast/GCD haste.

    The target is a source event category, not a specific class/talent spell.
    Percentages and expiration are read solely from the pinned rank row.
    """
    url=_staged_verified_source_url(capture,source_build)
    speed=capture.get('value');gcd=capture.get('additional_value')
    if (url is None or capture.get('effect_domain')!='on_spell_crit_cast_speed_bonus_fraction'
            or capture.get('additional_effect_domain')!='on_spell_crit_gcd_reduction_fraction'
            or capture.get('target')!='nonperiodic_spell_crit'
            or capture.get('additional_target')!='nonperiodic_spell_crit'
            or capture.get('condition')!='critical_hit_then_next_3s'
            or any(type(v) not in (int,float) or not isfinite(v) or not 0 < v < 1
                   for v in (speed,gcd))):
        return None
    # The 3-second timing is explicitly in the pinned typed *condition*;
    # never infer it for other source events or tooltip wording.
    import re
    match=re.fullmatch(r'critical_hit_then_next_(\d+)s',capture['condition'])
    if not match or not 0 < int(match.group(1)) <= 60:return None
    return TalentModifier(kind='timed_spell_crit_cast_haste',target_type='actor_proc',
        target_id=capture['target'],value=float(speed),provenance={
        'authority':'source_pinned_timed_crit_haste', 'source_build':source_build,
        'source_url':url,'source_condition':capture['condition'],
        'source_domains':(capture['effect_domain'],capture['additional_effect_domain']),
        'gcd_reduction_fraction':float(gcd), 'duration_s':float(match.group(1)),
        'unsupported_expected_value_distribution':
            'DIRECT_DAMAGE_IS_EXPECTED_CRIT_WHILE_BUFF_TRIGGER_IS_SEEDED_DISCRETE_SAMPLE'})



def _staged_channel_cooldown_threat_fraction(capture:dict, *,source_build:str|None,actions:dict):
    """Atomic paired action cooldown and threat reduction from pinned rank source.

    The target channel action must actually exist with a typed periodic heal.
    A single player actor cannot verify group healing or threat competition;
    both modifiers carry that explicit RED partial-semantics marker.
    """
    target=capture.get('target');url=_staged_verified_source_url(capture,source_build)
    fraction=capture.get('value');threat=capture.get('additional_value')
    candidates=actions.get(target,()) if isinstance(target,str) else ()
    if (url is None or capture.get('effect_domain')!=target+'_cooldown_reduction_fraction'
            or capture.get('additional_effect_domain')!=target+'_threat_reduction_fraction'
            or capture.get('additional_target')!=target
            or capture.get('condition')!='trained_'+str(target)
            or type(fraction) not in (int,float) or not 0 < fraction < 1
            or type(threat) not in (int,float) or not 0 < threat <= 1
            or not any(a.metadata.get('source_semantic_type')=='channeled_group_heal'
                   and a.metadata.get('channel') and
                   a.metadata.get('source_build_bridge_verified') is False
                   for a in candidates)):
        return None
    shared={'authority':'source_pinned_compound_channel_talent',
        'source_build':source_build,'source_url':url,
        'source_domains':(capture['effect_domain'],capture['additional_effect_domain']),
        'unsupported_party_scope':'GROUP_HEAL_AND_COMPETING_THREAT_NOT_IMPLEMENTED',
        'unsupported_build_bridge':'CHANNEL_SOURCE_INDEX_IS_NOT_70338_VERSION_VERIFIED'}
    return [TalentModifier(kind='cooldown_factor_pct',target_type='action_family',
               target_id=target,value=-float(fraction),provenance=shared),
            TalentModifier(kind='threat_factor_pct',target_type='action_family',
               target_id=target,value=-float(threat),provenance=shared)]


def _capture_ledger_sources(capture: dict):
    """Report original source domains, not normalized executor opcodes."""
    effects = capture.get('effects') or []
    if isinstance(effects, list) and effects:
        return ([e.get('domain') for e in effects],
                [e.get('source') for e in effects])
    if capture.get('effect_domain') is not None:
        return ([capture['effect_domain']], [capture.get('source_url')])
    return ([], [])


def promote_atomic_source_talent_effects(ir):
    """Compile only *complete* L0 rank effects; ledger includes uncovered ranks.

    Handles any number of independent compatible source clauses atomically.
    Clauses describing procs, context-specific mechanics, unknown conditions
    or absent actor targets remain blocked. This is NOT a P2/P3 certificate.
    """
    actions = {a.family_key for a in ir.actions}
    action_objects={family:tuple(a for a in ir.actions if a.family_key==family)
                    for family in actions}
    schools = {str(getattr(e, 'school')).lower() for a in ir.actions
               for e in a.effects if getattr(e, 'school', None)}
    actor_stats = set(ir.actor.base_stats)
    modes = {mode.id for mode in ir.modes}
    resources = {r.id for r in ir.resources}
    action_caps={a.family_key:dict(next(iter(a.metadata['source_control_target_caps'].values())))
                 for a in ir.actions if a.metadata.get('source_control_target_caps')}
    promoted, pending, preserved, updated = [], [], [], []
    for talent in ir.talents:
        rank_rows = []
        for rank in talent.ranks:
            if rank.modifiers:
                rank_rows.append(rank)
                preserved.append({'talent_id': talent.id, 'rank': rank.rank,
                                  'modifier_count': len(rank.modifiers)})
                continue
            capture = rank.provenance.get('checkpoint_source_l0') or {}
            effects = capture.get('effects') or []
            mods = []
            reason = 'MISSING_TYPED_SOURCE_EFFECTS' if not effects else 'UNSUPPORTED_SOURCE_SEMANTICS'
            if (effects and isinstance(effects, list)
                    and isinstance(capture.get('expected_clause_count'), int)
                    and capture['expected_clause_count'] == len(effects)):
                clauses = [_compile_clause(e, actions=actions, schools=schools,
                                           actor_stats=actor_stats,
                                           build=talent.metadata.get('checkpoint_source_build'))
                           for e in effects]
                # Mixed/partial clauses must NOT be accepted.
                if all(m is not None for m in clauses):
                    # A tooltip may use multiple contexts. Never merge them into
                    # one global modifier unless their source condition agrees.
                    conditions = {e.get('condition') for e in effects}
                    if len(conditions) == 1:
                        mods = clauses
                        reason = 'COMPLETE_TYPED_SOURCE_CLAUSES_EXECUTABLE'
                    else:
                        reason = 'COMPOUND_CONTEXT_NOT_EQUIVALENT'
            if effects and capture.get('expected_clause_count') != len(effects):
                reason = 'INCOMPLETE_SOURCE_CLAUSE_INTEGRITY'
            if not effects and capture.get('effect_domain') is not None:
                control_cap = _staged_control_target_cap_clause(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),
                    action_caps=action_caps)
                charge = _staged_charge_exchange_clause(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),
                    actions=actions)
                compound = _staged_compound_control_clauses(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),
                    actions=actions)
                crit_healing = _staged_melee_crit_and_stat_healing(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),
                    actor_stats=actor_stats)
                form_crit = _staged_form_crit_bonus(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),
                    modes=modes)
                critical_resources = _staged_critical_resource_pair(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),
                    resources=resources, modes=modes)
                resource_action = _staged_resource_action_grant(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),
                    resources=resources,modes=modes,actor_stats=actor_stats)
                channel_compound = _staged_channel_cooldown_threat_fraction(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),
                    actions=action_objects)
                control_duration_cd = _staged_compound_control_duration_cooldown(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),actions=action_objects)
                spatial_charge_grant = _staged_spatial_charge_grant(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),modes=modes)
                periodic_full_heal_grant = _staged_active_periodic_full_heal_grant(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),
                    actions=action_objects,modes=modes)
                next_cast_grant = _staged_next_cast_instant_grant(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),modes=modes)
                timed_crit_haste = _staged_timed_spell_crit_haste(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'))
                cooldown_reduction = _staged_action_cooldown_reduction(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'))
                staged = _staged_fraction_clause(capture,
                    source_build=talent.metadata.get('checkpoint_source_build'),
                    actions=actions, schools=schools, actor_stats=actor_stats)
                if control_cap is not None:
                    mods = [control_cap]
                    reason = 'COMPLETE_SOURCE_PINNED_CONTROL_TARGET_CAP'
                elif charge is not None:
                    mods = [charge]
                    reason = 'COMPLETE_SOURCE_PINNED_CAST_CHARGE_EXCHANGE'
                elif compound is not None:
                    mods = compound
                    reason = 'COMPLETE_STAGED_COMPOUND_CONTROL_CLAUSES_EXECUTABLE'
                elif crit_healing is not None:
                    mods = crit_healing
                    reason = 'COMPLETE_STAGED_COMPOUND_CRIT_HEALING_CLAUSES_EXECUTABLE'
                elif critical_resources is not None:
                    mods = critical_resources
                    reason = 'SOURCE_CRITICAL_RESOURCE_DUAL_PROC_WITH_EXPLICIT_BUILD_BRIDGE'
                elif resource_action is not None:
                    mods = [resource_action]
                    reason = 'SOURCE_RESOURCE_ACTION_GRANTED_WITH_VERSIONED_MECHANICS'
                elif channel_compound is not None:
                    mods=channel_compound
                    reason='SOURCE_COMPOUND_CHANNEL_COOLDOWN_THREAT_SOLO_RUNTIME_PARTIAL'
                elif control_duration_cd is not None:
                    mods=control_duration_cd
                    reason='SOURCE_COMPOUND_CONTROL_DURATION_COOLDOWN_WITH_BUILD_BRIDGE'
                elif spatial_charge_grant is not None:
                    mods=[spatial_charge_grant]
                    reason='SOURCE_SPATIAL_CHARGE_GRANT_AND_GEOMETRY_PARTIAL'
                elif periodic_full_heal_grant is not None:
                    mods=[periodic_full_heal_grant]
                    reason='SOURCE_ACTIVE_PERIODIC_FULL_DURATION_HEAL_RUNTIME_PARTIAL'
                elif next_cast_grant is not None:
                    mods=[next_cast_grant]
                    reason='SOURCE_NEXT_INSTANT_ACTION_WITH_UNVERIFIED_BUILD_BRIDGE'
                elif timed_crit_haste is not None:
                    mods=[timed_crit_haste]
                    reason='SOURCE_TIMED_SPELL_CRIT_HASTE_EXECUTABLE_PARTIAL_EXPECTED_DISTRIBUTION'
                elif cooldown_reduction is not None:
                    mods = [cooldown_reduction]
                    reason = 'SOURCE_ACTION_COOLDOWN_REDUCTION_EXECUTABLE'
                elif form_crit is not None:
                    mods = form_crit
                    reason = 'SOURCE_FORM_CRIT_PLAYER_COMPONENT_EXECUTABLE_PARTY_UNPROVEN'
                elif staged is not None:
                    mods = [staged]
                    reason = 'COMPLETE_STAGED_FRACTION_CLAUSE_EXECUTABLE'
                else:
                    reason = 'UNSUPPORTED_OR_COMPOUND_STAGED_FRACTION'
            domains, source_urls = _capture_ledger_sources(capture)
            if mods:
                rank_rows.append(replace(rank, modifiers=tuple(mods)))
                promoted.append({'talent_id': talent.id, 'rank': rank.rank,
                                 'domains': domains,
                                 'source_urls': source_urls,
                                 'modifier_count': len(mods),
                                 'execution_scope': ('build_bridge_unverified' if
                                     any(m.provenance.get('unsupported_build_bridge') for m in mods)
                                     else 'player_only_party_unproven' if
                                     any(m.provenance.get('unsupported_party_scope') for m in mods)
                                     else 'solo_only_threat_neutral' if
                                     any(m.kind == 'threat_factor_pct' for m in mods)
                                     else 'source_clause_complete')})
            else:
                rank_rows.append(rank)
                pending.append({'talent_id': talent.id, 'rank': rank.rank,
                                'domains': domains, 'reason': reason})
        updated.append(replace(talent, ranks=tuple(rank_rows)))
    ledger = {'promoted_rank_count': len(promoted),
              'preexisting_rank_count': len(preserved),
              'unscored_rank_count': len(pending),
              'total_rank_count': len(promoted) + len(preserved) + len(pending),
              'promoted': promoted, 'preexisting': preserved, 'unscored': pending,
              'full_talent_execution_certified': False,
              'candidate_objective_status': 'PARTIAL_SOURCE_RANK_EFFECTS_NOT_OPTIMUM'}
    return replace(ir, talents=tuple(updated), unsupported_semantics=(*ir.unsupported_semantics,
        {'code': 'SOURCE_TALENT_EXECUTION_COVERAGE_NOT_OPTIMUM',
         'promoted_rank_count': len(promoted), 'preexisting_rank_count': len(preserved),
         'missing_rank_count': len(pending)})), ledger
