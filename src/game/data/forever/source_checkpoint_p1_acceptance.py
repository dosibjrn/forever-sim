"""One reusable P1 admission contract for any (class, level, profile, runes) checkpoint.

No class/name/level-specific ability whitelist. This is a *fail-closed* verdict on
source-enumerated actions and L0 utility's participation in an optimizer frontier.
A semantic label is never a rankable optimizer score. L2 support is not required.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class CheckpointP1:
    class_key: str
    level: int
    profile: str = 'unrestricted'
    use_runes: bool = False

    def __post_init__(self):
        if not self.class_key or not 1 <= self.level <= 60:
            raise ValueError('INVALID_CHECKPOINT_CLASS_OR_LEVEL')
        if not self.profile:
            raise ValueError('MISSING_PROFILE_CONSTRAINT')


def _acquisition(db: sqlite3.Connection, cls: str) -> dict[int, dict]:
    # NPC method is authoritative *source* evidence of a learnable skill. It
    # does not claim that a particular vendor is currently spawned or accessed.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ability_acquisition_evidence'").fetchone():
        return {}
    result = {}
    for sid, status, methods in db.execute('''SELECT spell_id,evidence_status,methods_observed_json
              FROM ability_acquisition_evidence WHERE class_key=?''', (cls,)):
        seen = json.loads(methods)
        if not isinstance(seen, dict):
            raise ValueError('INVALID_ACQUISITION_METHOD_EVIDENCE')
        result[int(sid)] = {'status': status, 'methods': seen}
    return result


def _status(row: dict, acquisition: dict | None, *, profile: str) -> tuple[str, str]:
    reason = row.get('eligibility', '')
    if reason == 'RUNE_ENGRAVING_DISABLED_BY_DEFAULT':
        return 'ILLEGAL', 'ENGRAVING_DISABLED'
    if reason == 'RUNE_CONDITIONAL_GRANT_DISABLED_TALENT_PATH_UNVERIFIED':
        return 'ILLEGAL', 'NO_VERIFIED_NONRUNE_GRANT'
    if reason == 'AUXILIARY_OR_PASSIVE_NOT_STANDALONE_ACTION':
        return 'ILLEGAL', 'TRIGGER_OR_PASSIVE_NOT_PLAYER_BUTTON'
    if reason == 'PASSIVE_OR_TALENT_UNRESOLVED':
        return 'ILLEGAL', 'PASSIVE_NOT_PLAYER_BUTTON_P2_HANDLES_TALENTS'
    if reason == 'REMOVED_CHANGESET_BUILD_APPLICABILITY_UNRESOLVED':
        return 'UNRESOLVED', 'REMOVAL_PATCH_APPLICABILITY_UNKNOWN'
    if reason == 'RUNE_SETUP_ACQUISITION_UNRESOLVED':
        return 'UNRESOLVED', 'RUNE_ENABLED_DOES_NOT_PROVE_ACQUISITION'
    if row.get('verified_talent_grant_exact_id_and_level'):
        # Talent spend and prerequisites must be enforced by the talent system.
        # For restricted profiles we cannot infer permitted talent builds.
        return ('CONDITIONAL', 'TALENT_ALLOCATION_REQUIRED') if profile == 'unrestricted' else (
            'UNRESOLVED', 'PROFILE_TALENT_ELIGIBILITY_UNPROVEN')
    if reason != 'POTENTIALLY_LEGAL_RANK_ACQUISITION_UNRESOLVED':
        return 'UNRESOLVED', 'UNRECOGNIZED_SOURCE_ROLE'
    if str(row.get('source_acquisition_evidence_status','')).startswith('STALE_'):
        return 'UNRESOLVED', 'STALE_ACQUISITION_SOURCE_BATCH_OR_SHA'
    # Existing GameIR is generated for this class+level from canonical source
    # ranks; an exact-ID action match is positive in-game action evidence, not
    # just a listview name or a generic low required-level hint.
    if row.get('ir_action_ids') and row.get('source_level_hint') is not None:
        if profile == 'unrestricted':
            return 'LEGAL', 'SOURCE_INDEX_EXACT_ID_CHECKPOINT_GAME_IR_ACTION'
        return 'UNRESOLVED', 'PROFILE_ACTION_ELIGIBILITY_UNPROVEN'
    # Exact source/batch provenance beats any lower-trust acquisition hint.
    # A stale method cannot legalize a spell even if an older GameIR action
    # happens to match the source spell ID.
    acq = acquisition or {}
    if 'taught_by_npc' in acq.get('methods', {}) and acq['methods']['taught_by_npc'] > 0:
        if profile != 'unrestricted':
            return 'UNRESOLVED', 'SPEC_PROFILE_LEGALITY_UNPROVEN'
        return 'LEGAL', 'SOURCE_OBSERVED_NPC_TRAINING_METHOD'
    return 'UNRESOLVED', 'INDEX_LEVEL_HINT_IS_NOT_ACQUISITION'


def _utility_proxy(row: dict, *, runtime_context: dict | None = None,
                   source_numeric: dict | None = None, contextual_zero: str | None = None) -> dict:
    """Comparable L0 damage potential, never treated as predicted seconds/mob.

    Separate domains remain separate. Unknown benefit/cost never becomes zero,
    and source-only numerical signals still participate in the L0 candidate pool.
    """
    f = row.get('index_features') or {}
    context = row.get('source_text_context_evidence') or {}
    contextual = context.get('numeric_context_features') or {}
    irs = row.get('ir_proxies') or []
    base_damage = float(f.get('direct_damage') or 0) + float(f.get('periodic_damage_total') or 0)
    healing = float(f.get('direct_healing') or 0) + float(f.get('absorption') or 0)
    resource = float(f.get('resource_gain') or 0)
    healing += float(contextual.get('periodic_heal_total') or 0)
    reactive = float(contextual.get('reactive_damage_per_incoming_hit') or 0)
    queued = 0.
    for proxy in irs:
        p = proxy.get('features') or {}
        base_damage = max(base_damage, float(p.get('direct_damage') or 0) + float(p.get('periodic_damage_total') or 0))
        healing = max(healing, float(p.get('direct_healing') or 0))
        resource = max(resource, float(p.get('resource_gain') or 0))
        queued = max(queued, float(p.get('on_next_swing_bonus_damage') or 0))
    # No guessed incoming-hit count, mana-to-damage conversion, buff duration
    # or fake actor HP. These are distinct Pareto dimensions with a numeric
    # ordering *within* each effect domain.
    v = {'damage_per_activation':base_damage,
         'heal_or_absorb_per_activation':healing,
         'resource_gain_per_activation':resource,
         'retaliation_damage_per_incoming_hit':reactive,
         'queued_swing_bonus_damage':queued,
         'enemy_attack_power_reduction':float(contextual.get('enemy_melee_attack_power_reduction') or 0),
         'caster_armor_increase':float(contextual.get('friendly_armor_bonus') or 0),
         'all_attribute_increase':float(contextual.get('all_attributes_bonus') or 0),
         'enemy_armor_reduction':float(f.get('armor_reduction') or 0),
         'target_control_seconds':float((runtime_context or {}).get('control_duration_s') or 0),
         'mode_reachable_followup_damage':float((runtime_context or {}).get('mode_followup_damage') or 0),
         'mode_reachable_damage_filler_count':float((runtime_context or {}).get('mode_followup_count') or 0),
         'target_debuff_magnitude':float((runtime_context or {}).get('target_debuff_magnitude') or 0)}
    for domain,value in (source_numeric or {}).items():
        if domain in v:
            v[domain]=max(v[domain],float(value))
        else:
            v[domain]=float(value)
    quantitative = any(x > 0 for x in v.values())
    if contextual_zero and quantitative:
        raise ValueError('CONTRADICTORY_CONTEXTUAL_ZERO_AND_POSITIVE_PROXY')
    # All-zero numeric vectors are not proof of zero value: form changes,
    # debuffs, stuns, positional/utility effects may have positive benefit.
    return {'rankable_numeric_domain_proxy':quantitative or bool(contextual_zero), 'value_domains':v,
            'candidate_is_l0_evaluated':quantitative or bool(contextual_zero),
            'explicit_context_zero_reason':contextual_zero,
            'comparability':'PARETO_BY_EFFECT_DOMAIN_UNTIL_CONTEXT_CONVERSION',
            'has_explicit_no_benefit_evidence':bool(contextual_zero)}


def _talent_requirement(grant: dict) -> dict:
    return {'tree':grant['talent_tree'],
            'prior_tree_points':grant['prior_tree_points'],
            'rank':grant['talent_rank']}


def evaluate_p1(frontier: dict, db_path: str | Path, checkpoint: CheckpointP1, *, ir=None,
                spellbook_path: str | Path | None = None,
                target_source_build: str | None = None,
                source_delta_path: str | Path | None = None) -> dict:
    c = frontier['checkpoint']
    if (c['class_key'].lower(), int(c['level']), c['profile']) != (
            checkpoint.class_key.lower(), checkpoint.level, checkpoint.profile):
        raise ValueError('P1_CHECKPOINT_FRONTIER_MISMATCH')
    if bool(frontier['use_runes']) != checkpoint.use_runes:
        raise ValueError('P1_RUNE_CONFIGURATION_MISMATCH')
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True) as db:
        methods = _acquisition(db, checkpoint.class_key.lower())
    from .source_checkpoint_spellbook import SourceSpellbook
    spellbook = (SourceSpellbook(spellbook_path,class_key=checkpoint.class_key,level=checkpoint.level,use_runes=checkpoint.use_runes)
                 if spellbook_path is not None else None)
    source_build_bridge = None
    original_build = spellbook.data['build'] if spellbook is not None else None
    effective_build = target_source_build or original_build
    if target_source_build is not None and spellbook is None:
        raise ValueError('SOURCE_BUILD_BRIDGE_REQUIRES_SPELLBOOK')
    if spellbook is not None:
        from .source_build_delta import resolve_spellbook_build
        source_build_bridge = resolve_spellbook_build(
            spellbook,class_key=checkpoint.class_key,target_build=effective_build,
            delta_path=source_delta_path,missing_error='SOURCE_BUILD_BRIDGE_REQUIRED')
    if spellbook is not None and spellbook.data['source_index_sha256'] != frontier['source_index_sha256']:
        raise ValueError('SPELLBOOK_SOURCE_INDEX_SNAPSHOT_MISMATCH')
    runtime_context_by_action={}
    if ir is not None:
        # Derive contextual form and control value from the *existing* GameIR
        # and mode-aware paid-search envelope, never from hardcoded spell IDs.
        from src.v2.source_budgeted_prefix import source_prefix_envelope
        from src.game.runtime.effect_capabilities import effect_role
        actions={a.id:a for a in ir.actions}
        for a in ir.actions:
            control=max((float(getattr(e,'duration_s',0)) for e in a.effects
                         if effect_role(e)=='control'),default=0.)
            debuff=max((abs(float(getattr(e,'delta',0))) for e in a.effects
                        if effect_role(e)=='target_debuff'),default=0.)
            runtime_context_by_action[a.id]={'control_duration_s':control,
                                              'target_debuff_magnitude':debuff}
        # An activation aura can have real numeric CC value through a
        # source-declared event trigger, even though the cast itself only
        # applies a status aura. Propagate the trigger's effect domains to the
        # owning cast without inventing any proc frequency or DPS conversion.
        by_aura={getattr(e,'aura_id',None):a.id for a in ir.actions
                 for e in a.effects if getattr(e,'effect_type',None)=='status_aura'}
        for trigger in ir.triggers:
            parent=by_aura.get(trigger.required_aura_id)
            if not parent:continue
            control=max((float(getattr(e,'duration_s',0.)) for e in trigger.effects
                         if effect_role(e)=='control'),default=0.)
            if control>0.:
                context=runtime_context_by_action[parent]
                context['control_duration_s']=max(context.get('control_duration_s',0.),control)
        envelope=source_prefix_envelope(ir,level=checkpoint.level)
        for path in envelope['mode_paths']:
            followup=0.
            for aid in path['fillers']:
                a=actions[aid]
                for e in a.effects:
                    if effect_role(e)=='direct_damage':
                        mn=getattr(e,'base_min',None)
                        mx=getattr(e,'base_max',None)
                        if mn is not None and mx is not None:
                            followup=max(followup,(float(mn)+float(mx))/2)
            if path['fillers']:
                mode=runtime_context_by_action.setdefault(path['entry'],{})
                mode['mode_followup_damage']=followup
                mode['mode_followup_count']=len(path['fillers'])
    candidates=[]
    for row in frontier['records']:
        if 'spell_id' not in row:
            continue  # IR-only actions are inventoried separately, not silently declared legal.
        status,reason=_status(row,methods.get(int(row['spell_id'])),profile=checkpoint.profile)
        if spellbook is not None and checkpoint.profile == 'unrestricted':
            override=spellbook.source_decision(row)
            if override is not None:
                status,reason=override
        matching_context={}
        for aid in row.get('ir_action_ids',[]):
            for key,value in runtime_context_by_action.get(aid,{}).items():
                matching_context[key]=max(matching_context.get(key,0.),value)
        numeric,zero=spellbook.contextual_proxy(row) if spellbook is not None else ({},None)
        indexed_grant = (spellbook.grant_by_id.get(int(row['spell_id']))
                         if spellbook is not None and status=='CONDITIONAL' else None)
        if indexed_grant is not None:
            numeric.update(indexed_grant['l0_domains'])
        proxy=_utility_proxy(row,runtime_context=matching_context,source_numeric=numeric,contextual_zero=zero)
        # A real IR action or scored source feature enters the cheap L0
        # candidate set, even if currently not runnable by paid L2.
        candidate = status in ('LEGAL','CONDITIONAL','PASSIVE') and proxy['candidate_is_l0_evaluated']
        candidates.append({'spell_id':int(row['spell_id']), 'name':row['name'],
            'status':status,'legality_reason':reason,
            'legal_level_hint':row.get('source_level_hint'),
            'source_row_sha256':row['source_row_sha256'],
            'source_url':row['source_url'],
            'source_acquisition_category':row.get('source_acquisition_category'),
            'source_acquisition_evidence_status':row.get('source_acquisition_evidence_status'),
            'l0_candidate':candidate, 'l0_utility':proxy,
            'paid_l2_action_ids':row.get('paid_search_action_ids',[]),
            'ir_action_ids':row.get('ir_action_ids',[]),
            'paid_l2_not_required_for_p1':True,
            'conditional_talent_rank_requirement':(
                spellbook.conditional_rank_requirement(row) if spellbook is not None and status=='CONDITIONAL' else None),
            **({'talent_requirement':_talent_requirement(indexed_grant)}
               if indexed_grant is not None else {})})
    if spellbook is not None:
        for grant in spellbook.grants:
            sid=int(grant['spell_id'])
            indexed=next((r for r in candidates if r['spell_id']==sid),None)
            if indexed is not None:
                if indexed['name'] != grant['name'] or indexed['status']!='CONDITIONAL':
                    raise ValueError('EXTERNAL_TALENT_GRANT_COLLIDES_WITH_SOURCE_INDEX')
                continue  # Exact sourced ID already represented, never double-count.
            # A source-only talent grant obeys the SAME fixed scenario as indexed
            # actions: secondary-target-only effects are not useful when
            # there is exactly one enemy.  This is a generic context rule
            # supplied by the versioned spellbook, not a hardcoded talent.
            grant_context_zero = (spellbook.data.get(
                'contextual_zero_when_solo_land_mob_no_allies_or_debuffs', {})
                .get(grant['name']))
            proxy=_utility_proxy({'name':grant['name']},
                source_numeric=(grant['l0_domains'] if not grant_context_zero else {}),
                contextual_zero=grant_context_zero)
            candidates.append({'spell_id':sid,'name':grant['name'],'status':'CONDITIONAL',
                'legality_reason':'SOURCE_SPELLBOOK_TALENT_GRANT_REQUIRES_ALLOCATION',
                'legal_level_hint':grant['learned_level'],
                'source_url':grant['source_url'], 'source_row_sha256':None,
                'source_acquisition_category':'CLIENT_TALENT_GRANT',
                'source_acquisition_evidence_status':'CLIENT_SPELLBOOK_TALENT',
                'l0_candidate':proxy['candidate_is_l0_evaluated'],'l0_utility':proxy,
                'paid_l2_action_ids':[], 'ir_action_ids':[],
                'paid_l2_not_required_for_p1':True,
                'talent_requirement':_talent_requirement(grant),
                'source_only_not_yet_in_IR':True})
        for action in spellbook.source_only:
            sid=int(action['spell_id'])
            if any(r['spell_id']==sid for r in candidates):
                raise ValueError('SOURCE_ONLY_ACTION_COLLIDES_WITH_SOURCE_INDEX')
            proxy=_utility_proxy({'name':action['name']},
                source_numeric=action.get('l0_domains',{}),
                contextual_zero=action.get('contextual_zero'))
            candidates.append({'spell_id':sid,'name':action['name'],'status':'LEGAL',
                'legality_reason':'CLIENT_SPELLBOOK_EXACT_SOURCE_ONLY_LEARNED_ACTION',
                'legal_level_hint':int(action['learned_level']),
                'source_url':action['source_url'],'source_row_sha256':None,
                'source_acquisition_category':'CLIENT_SPELLBOOK_LEARNED_ACTION',
                'source_acquisition_evidence_status':'CLIENT_SPELLBOOK_SOURCE_ONLY',
                'l0_candidate':proxy['candidate_is_l0_evaluated'],'l0_utility':proxy,
                'paid_l2_action_ids':[],'ir_action_ids':[],
                'paid_l2_not_required_for_p1':True,
                'source_only_not_yet_in_IR':True})
    for row in frontier['excluded_above_level']:
        candidates.append({'spell_id':int(row['spell_id']),'status':'ILLEGAL',
            'legality_reason':'ABOVE_CHECKPOINT_LEVEL','l0_candidate':False})
    if not candidates:
        raise ValueError('EMPTY_SOURCE_CANDIDATE_SET')
    counts=Counter(r['status'] for r in candidates)
    missing=[r['spell_id'] for r in candidates if r['status'] in ('LEGAL','CONDITIONAL','PASSIVE') and not r['l0_candidate']]
    unknown=[r['spell_id'] for r in candidates if r['status']=='UNRESOLVED']
    # P1 is never silently certified for a spec profile that was not applied
    # upstream. The engine has not yet proven class/level action legality for
    # profiles other than unrestricted.
    profile_applied=bool(frontier['profile_constraint_applied'])
    nonindexed=[r['ir_only_action_id'] for r in frontier['records'] if 'ir_only_action_id' in r]
    # Runtime-generated form exits are control transitions, not extra learned
    # spell ranks. Check their explicit generic-mode-control provenance rather
    # than introducing an artificial trainer/acquisition gate for them.
    ir_by_id={a.id:a for a in ir.actions} if ir is not None else {}
    runtime_mode_controls=[]
    unclassified_ir_only=[]
    for aid in nonindexed:
        action=ir_by_id.get(aid)
        if (action is not None and action.effects
            and all(getattr(e,'effect_type',None)=='mode_change' for e in action.effects)
            and any(p.get('authority')=='generic_mode_control_semantic'
                    for p in action.provenance)):
            runtime_mode_controls.append(aid)
        else:
            unclassified_ir_only.append(aid)
    spellbook_coverage=spellbook.coverage(frontier['records']) if spellbook is not None else None
    unmatched=(spellbook_coverage or {}).get('missing_learned_action_rows',[])
    pass1 = (counts['LEGAL']+counts['CONDITIONAL']+counts['PASSIVE']>0 and not missing
             and not unknown and not unmatched and profile_applied and not unclassified_ir_only)
    return {'schema':'checkpoint_p1_acceptance_v1',
        'checkpoint':{'class_key':checkpoint.class_key.lower(),'level':checkpoint.level,
                      'profile':checkpoint.profile,'use_runes':checkpoint.use_runes},
        'legal':counts['LEGAL'],'conditional':counts['CONDITIONAL'],
        'learned_passive':counts['PASSIVE'],
        'spellbook_evidence':spellbook_coverage,
        'source_build':effective_build,
        'source_spellbook_original_build':original_build,
        'source_build_bridge':source_build_bridge,
        'illegal':counts['ILLEGAL'],'unresolved':counts['UNRESOLVED'],
        'scored_legal_or_conditional':sum(r['l0_candidate'] for r in candidates),
        'legal_without_rankable_l0':missing,'unresolved_ids':unknown,
        'unresolved_by_source_acquisition_category':dict(Counter(
            r.get('source_acquisition_category') or 'NO_SOURCE_CATEGORY'
            for r in candidates if r['status']=='UNRESOLVED')), 
        'ir_only_actions_without_index_acquisition':unclassified_ir_only,
        'runtime_generated_mode_controls':runtime_mode_controls,
        'profile_constraint_applied':profile_applied,
        'PASS1':pass1,
        'blockers':([*(['UNRESOLVED_SOURCE_LEGALITY'] if unknown else []),
                     *(['LEGAL_ACTION_MISSING_RANKABLE_L0'] if missing else []),
                     *(['CLIENT_SPELLBOOK_LEARNED_ACTION_NOT_IN_SOURCE_INDEX'] if unmatched else []),
                     *(['PROFILE_CONSTRAINT_UNPROVEN'] if not profile_applied else []),
                     *(['IR_ONLY_ACTION_ACQUISITION_UNMAPPED'] if unclassified_ir_only else [])]),
        'admission_contract':'LEGAL_OR_CONDITIONAL_REQUIRES_NUMERIC_L0_SEARCH_CANDIDATE; UNKNOWN_NEVER_ZERO',
        'records':candidates}


def l0_paid_action_priority(verdict: dict) -> dict[str, int]:
    """Bring P1-scored *existing* executable actions into the real scout order.

    No unknown, illegal, or source-unmapped spell is silently inserted into L2.
    Ranking uses Pareto-dominant dimensions as cheap, provisional priorities;
    execution and survival outcomes remain the real scorer.
    """
    options=[]
    for row in verdict['records']:
        if not row.get('l0_candidate'):
            continue
        values=row['l0_utility']['value_domains']
        best=max(values.items(),key=lambda kv:(kv[1],kv[0]))
        for aid in row.get('paid_l2_action_ids',[]):
            options.append((aid,best[0],float(best[1])))
    # Round-robin across effect domains so damage alone never eliminates
    # healing/control/resource paths. The numeric magnitudes are NOT globally
    # comparable between effects, only *within* the same source effect type.
    buckets={}
    for aid,domain,score in options:
        buckets.setdefault(domain,[]).append((aid,score))
    for group in buckets.values():
        group.sort(key=lambda x:(-x[1],x[0]))
    ordered=[]
    for rank in range(max((len(v) for v in buckets.values()),default=0)):
        for domain in sorted(buckets):
            if rank<len(buckets[domain]):
                aid=buckets[domain][rank][0]
                if aid not in ordered:
                    ordered.append(aid)
    return {aid:rank for rank,aid in enumerate(ordered)}


def l0_ranked_source_candidates(verdict: dict) -> dict:
    """Paid-search-independent L0 candidate ranking for ALL source-learned IDs.

    Exposes source-only conditional talent grants and passives to the generic
    discovery controller as scored L0 alternatives, not fictitious L2 actions.
    Numeric domains remain separate: round-robin domain leaders rather than
    summing incomparable units (seconds, HP, damage, range).
    """
    rows=[r for r in verdict['records'] if r.get('l0_candidate')]
    if not rows:
        raise ValueError('NO_SOURCE_L0_CANDIDATES')
    by_domain={}
    for row in rows:
        for domain,value in row['l0_utility']['value_domains'].items():
            if value>0:
                by_domain.setdefault(domain,[]).append((float(value),row['spell_id']))
    for domain in by_domain:
        by_domain[domain].sort(key=lambda v:(-v[0],v[1]))
    seen=set();ranked=[]
    # Round-robin across domains so e.g. healing isn't suppressed by damage.
    pending={k:list(v) for k,v in sorted(by_domain.items())}
    while pending:
        for domain in list(pending):
            if not pending[domain]:
                del pending[domain];continue
            _,sid=pending[domain].pop(0)
            if sid not in seen:
                seen.add(sid);ranked.append(sid)
    # Contextually justified zero remains evaluated and ranked last, not
    # falsely marked as an unknown zero-utility effect.
    ranked.extend(sorted(r['spell_id'] for r in rows if r['spell_id'] not in seen))
    if set(ranked)!={r['spell_id'] for r in rows} or len(ranked)!=len(rows):
        raise AssertionError('SOURCE_L0_RANKING_LOST_OR_DUPLICATED_CANDIDATE')
    return {'ranked_spell_ids':ranked,'ranked_count':len(ranked),
            'domain_count':len(by_domain),
            'source_only_candidates':[r['spell_id'] for r in rows if r.get('source_only_not_yet_in_IR')],
            'passive_modifier_candidates':[r['spell_id'] for r in rows if r['status']=='PASSIVE'],
            'context_zero_candidates':[r['spell_id'] for r in rows if r['l0_utility'].get('explicit_context_zero_reason')],
            'is_L2_executable_coverage':False}
