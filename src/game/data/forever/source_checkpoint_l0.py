"""Checkpoint-scoped, sourced L0 action frontier (NOT an L2 legality certificate).

All source ranks are assessed, not just the actions the current search can
execute.  A source-index row is NOT a trained spell: passives, rune engravings,
removed entries, talent grants and unavailable ranks stay visible.  Unknown
mechanics are never ranked as having zero possible value or silently pruned.

The frontier complements the EXISTING SQLite -> IR -> CombatRuntime -> joint
search.  It never builds executable game-specific actions or invents facts.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
import json
import sqlite3

from .source_action_scope import classify_indexed_ability
from .source_effect_atoms import parse_effect_atoms
from .source_checkpoint_context_proxy import source_context_evidence
from .source_checkpoint_web_l0 import load_observations
from .source_checkpoint_detail_observations import load_detail_observations
from .source_checkpoint_acquisition import acquisition_frontier
from .source_indexed_action_coverage import _source_spell_ids
from .sqlite_talents import DEFAULT_DB
from src.game.runtime.effect_capabilities import effect_role
from src.shared.leveling.objective import representative_hp


def _features_from_atoms(atoms: list[dict]) -> dict:
    """Cheap combat-context vector; do NOT transform this into fictitious s/mob."""
    features = {'direct_damage': 0., 'periodic_damage_total': 0.,
                'direct_healing': 0., 'absorption': 0., 'resource_gain': 0.,
                'attack_power': 0., 'armor_reduction': 0., 'slow_percent': 0.,
                'weapon_damage_multiplier': 0., 'source_atom_kinds': []}
    for a in atoms:
        kind, v = a['kind'], a['values']
        features['source_atom_kinds'].append(kind)
        if kind == 'school_damage_range':features['direct_damage'] += (v['min'] + v['max']) / 2
        elif kind == 'school_damage_fixed':features['direct_damage'] += v['amount']
        elif kind in ('periodic_school_damage', 'periodic_damage'):
            features['periodic_damage_total'] += v['amount']
        elif kind == 'healing_range':features['direct_healing'] += (v['min'] + v['max']) / 2
        elif kind == 'damage_absorption':features['absorption'] += v['amount']
        elif kind == 'resource_gain':features['resource_gain'] += v['amount']
        elif kind == 'actor_attack_power_increase':features['attack_power'] += v['amount']
        elif kind == 'target_armor_reduction':features['armor_reduction'] += v['amount']
        elif kind == 'movement_slow':features['slow_percent'] += v['percent']
        elif kind in ('weapon_damage_multiplier', 'weapon_multiplier_plus'):
            features['weapon_damage_multiplier'] += v['percent'] / 100.
        elif kind == 'weapon_damage_plus': features['direct_damage'] += v['amount']
    return features


def _ir_proxy(action) -> dict:
    """Shape-aware optimizer priors from EXISTING GameIR (no class dispatch)."""
    roles = sorted({effect_role(e) or 'UNSUPPORTED_EFFECT' for e in action.effects})
    numeric = {'direct_damage':0., 'periodic_damage_total':0., 'direct_healing':0.,
               'resource_gain':0., 'on_next_swing_bonus_damage':0.}
    for e in action.effects:
        role = effect_role(e)
        if getattr(e, 'effect_type', None)=='queued_swing':
            # Conditional on the next eligible auto attack, not immediate DPS.
            numeric['on_next_swing_bonus_damage']+=float(e.bonus_damage)
        if role == 'direct_damage':
            if getattr(e,'base_min',None) is not None:
                numeric['direct_damage'] += (float(e.base_min)+float(e.base_max))/2.
            # Weapon damage and resource scaling require actor/gear state.
        elif role == 'periodic_damage':
            numeric['periodic_damage_total'] += float(getattr(e,'total_base_damage',0.))
        elif (getattr(e, 'effect_type', None) == 'periodic_resource'
              and role == 'resource' and getattr(e, 'operation', '') == 'add'):
            # Count only declared positive periodic gains; a channel consumes
            # its actual runtime duration and cooldown at paid evaluation.
            interval = float(e.tick_interval_s)
            if interval > 0:
                ticks = max(0, int((float(e.duration_s) + 1e-9) // interval))
                numeric['resource_gain'] += ticks * max(0., float(e.amount_per_tick))
        elif role == 'healing':
            numeric['direct_healing'] += float(getattr(e,'base_min',0.))
        elif role == 'resource':
            numeric['resource_gain'] += max(0.,float(getattr(e,'amount',0.)))
    costs = [{'resource':c.resource_id,'amount':float(c.amount)} for c in action.costs]
    return {'effect_roles':roles, 'features':numeric, 'costs':costs,
        'gcd_s':float(action.gcd_s),'cast_s':float(action.cast_time_s),
        'contextual_modifiers_required':sorted(set(
            x for x in roles if x not in ('direct_damage','periodic_damage','healing','resource')) |
            ({'queued_swing_timing_and_auto_hit'} if any(
                getattr(e,'effect_type',None)=='queued_swing' for e in action.effects) else set())),
        'unknown_gameplay_ceiling':bool(set(roles)-{'direct_damage','periodic_damage','healing','resource'}),
        'proxy_kind':'IR_EFFECT_VECTOR_L0_NOT_100_MOB_SCORE'}


def action_frontier(ir, *, class_key: str, level: int,
                    profile: str | None = None,
                    db_path: str | Path = DEFAULT_DB,
                    detail_observations_path: str | Path | None = None,
                    use_runes: bool = False) -> dict:
    """Audit checkpoint-dependent universe and expose cheap contextual proxies.

    `profile` cannot be interpreted without machine-readable spec constraints;
    never silently treat a spec checkpoint as unrestricted.
    """
    cls = class_key.strip().lower()
    if cls != str(ir.actor.metadata.get('class_key','')).lower() or level != int(ir.actor.metadata.get('level',-1)):
        raise ValueError('CHECKPOINT_IR_CLASS_LEVEL_MISMATCH')
    if not 1 <= int(level) <= 60: raise ValueError('LEVEL_OUT_OF_RANGE')
    path = Path(db_path)
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute('''SELECT spell_id,name,level_hint,rank_hint,source_url,
          raw_listview_json,batch_id FROM spell_index
          WHERE class_key=? AND kind='abilities' ORDER BY spell_id''',(cls,)).fetchall()
        web_l0_observations = load_observations(db,cls)
        if not rows:raise ValueError('NO_CANONICAL_SOURCE_INDEX_FOR_CLASS')
        # Verified talent grants are independent of the SoD Rune system.
        # Restrict them to the checkpoint level; unlevelled grants stay unknown.
        talent_grant_ids=set()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='verified_talent_granted_action_facts'").fetchone():
            for grant_id,grant_json in db.execute(
                    'SELECT spell_id,action_json FROM verified_talent_granted_action_facts WHERE class_key=?',(cls,)):
                grant=json.loads(grant_json)
                req=grant.get('required_level')
                if req is not None and int(req)<=level:
                    talent_grant_ids.add(int(grant_id))
        # The source-index table, not the name list, is the enumeration authority.
        source_sha=sha256(''.join(str(r['spell_id'])+r['raw_listview_json'] for r in rows).encode()).hexdigest()
    observed_details = load_detail_observations(detail_observations_path, rows) if detail_observations_path else {}
    acquisition = acquisition_frontier(class_key=cls,level=level,db_path=path)
    acquisition_by_id = {r['spell_id']:r for r in acquisition['records']}
    # Sibling rank text supplies a utility *category* when an unchanged
    # canonical index entry carries no tooltip, never its missing magnitude.
    # The original indexed name is an exact group key, not a fuzzy join or
    # permission to invent source-legal rank effects.
    text_by_name = {}
    for rawrow in rows:
        payload = json.loads(rawrow['raw_listview_json'])
        t = str(((payload.get('envChange') or {}).get('after') or {}).get('text') or '')
        if t.strip():
            text_by_name.setdefault(rawrow['name'], []).append((int(rawrow['spell_id']), t))
    sources={}
    ir_only=[]
    for action in ir.actions:
        ids=_source_spell_ids(action)
        if not ids:ir_only.append(action)
        for sid in ids:sources.setdefault(sid,[]).append(action)
    # WF328: derive L0 search admission from the very same mode-aware
    # source envelope that the real paid prefix/joint controller uses.  The
    # source-index inventory on its own is NOT executable coverage; this
    # cross-reference makes unadmitted, potentially legal actions explicit.
    from src.v2.source_budgeted_prefix import source_prefix_envelope
    search=source_prefix_envelope(ir,level=level)
    paid_opening=set(search['actions'])
    paid_mode_actions=set()
    paid_mode_entries=set()
    for path_row in search['mode_paths']:
        paid_mode_entries.add(path_row['entry'])
        paid_mode_actions.update(path_row['actions'])
    paid_search_actions=paid_opening | paid_mode_entries | paid_mode_actions
    records=[];excluded=[];possible=[];ranked=[]
    target_hp=float(representative_hp(level))
    for row in rows:
        row=dict(row)
        sid=int(row['spell_id'])
        if row['level_hint'] is not None and int(row['level_hint'])>level:
            excluded.append({'spell_id':sid,'reason':'ABOVE_CHECKPOINT_LEVEL'})
            continue
        role=classify_indexed_ability(row,row['raw_listview_json'])
        raw=json.loads(row['raw_listview_json'])
        after=(raw.get('envChange') or {}).get('after') or {}
        source_text = str(after.get('text') or '')
        effects=parse_effect_atoms(source_text)
        # A provenance-bound web-indexed observation may provide a *semantic*
        # L0 role when the canonical listview has no text. It is never a
        # substitute for authenticated spell detail or proof of acquisition.
        web_observation = web_l0_observations.get(sid)
        web_context = (source_context_evidence(web_observation['observed_text'],
            target_hp=float(representative_hp(level))) if web_observation else None)
        source_context = source_context_evidence(source_text, target_hp=float(representative_hp(level)))
        if not source_context['effect_candidates'] and web_context is not None:
            source_context = web_context
        sibling_context = []
        if not source_text.strip():
            for other_sid, other_text in text_by_name.get(row['name'], ()):
                if other_sid == sid:
                    continue
                observed = source_context_evidence(other_text, target_hp=float(representative_hp(level)))
                if observed['effect_candidates']:
                    sibling_context.append({'source_spell_id':other_sid,
                        'effect_role_candidates':sorted({x['kind'] for x in observed['effect_candidates']}),
                        'no_assumed_numeric_amount_or_rank_legality':True})
        matches=sources.get(sid,[])
        features=_features_from_atoms(effects['atoms'])
        # Reactive damage must not become unconditional one-cast DPS.
        if any(x['kind']=='retaliatory_damage' for x in source_context['effect_candidates']):
            features['direct_damage'] = max(0.,features['direct_damage'] -
                source_context['numeric_context_features']['reactive_damage_per_incoming_hit'])
        quantified_damage=(features['direct_damage'] + .5*features['periodic_damage_total'])
        # This is a contextual bound/ordering feature, not a simulated kill or
        # a claim that the action is legally acquired. The optimizer must keep
        # high-uncertainty candidates for later typed evaluation.
        proxy={'horizon_mobs':100, 'target_hp_per_mob':target_hp,
            'direct_and_discounted_dot_fraction_of_one_target':round(quantified_damage/max(1.,target_hp),6),
            'continuous_kill_value': 'POTENTIAL_DAMAGE' if quantified_damage else 'UNKNOWN_OR_NON_DAMAGE',
            'recovery_value':'POTENTIAL_HEAL_OR_ABSORB' if features['direct_healing'] or features['absorption'] else 'UNKNOWN_OR_NONE',
            'resource_sustain_value':'POTENTIAL_RESOURCE_GAIN' if features['resource_gain'] else 'UNKNOWN_OR_NONE',
            'survival_and_control_value':'UNRESOLVED_REQUIRES_CONTEXT',
            'uncertainty_must_not_be_pruned':True,
            'score_kind':'CHECKPOINT_CONTEXTUAL_L0_HEURISTIC_NOT_L2'}
        rec={'spell_id':sid,'name':row['name'],'source_level_hint':row['level_hint'],
            'source_rank_hint':row['rank_hint'],'source_role':role['role'],
            'source_learning_hints':raw.get('source'),
            'source_acquisition_category':acquisition_by_id[sid]['category'],
            'source_acquisition_evidence_status':acquisition_by_id[sid]['acquisition_evidence_status'],
            'source_url':row['source_url'],'source_index_batch':row['batch_id'],
            'source_row_sha256':sha256(row['raw_listview_json'].encode()).hexdigest(),
            'ir_action_ids':sorted(x.id for x in matches),
            'index_features':features, 'checkpoint_l0_context_proxy':proxy,
            'source_text_context_evidence':source_context,
            'web_indexed_l0_observation':({
                'capture_kind':web_observation['capture_kind'],
                'observed_url':web_observation['observed_url'],
                'observed_at':web_observation['observed_at'],
                'source_flags':web_observation['source_flags'],
                'proves_spell_acquisition':False,
                'proves_full_L2_effects':False,
            } if web_observation else None),
            'external_detail_l0_observation':observed_details.get(sid),
            'sibling_rank_context_only':sibling_context,
            'residual_source_text':effects['residual_text'],
            'index_text_present':bool(effects['normalized_text']),
            'l0_observed_atom_count':len(effects['atoms']),
            'index_provenance_tier':'SOURCE_INDEX_PARTIAL_NOT_L2',
            'ir_proxies':[_ir_proxy(action) for action in matches],
            'paid_search_action_ids':sorted(a.id for a in matches if a.id in paid_search_actions),
            'paid_search_admission':('PAID_EXECUTABLE_SOURCE_IR' if any(a.id in paid_search_actions for a in matches)
                else 'IR_CONTEXT_NONOFFENSIVE_OR_UNREACHABLE' if matches
                else 'NO_EXECUTABLE_IR_FOR_SOURCE_RANK')}
        flags=set(web_observation['source_flags']) if web_observation else set()
        details=observed_details.get(sid)
        if details is not None:
            flags.update(details.get('context_conditions',()))
            if details['observed_action_type'] in ('triggered_effect_not_player_cast','passive_modifier_not_cast'):
                flags.add('not_an_action')
        confirmed_talent_grant=sid in talent_grant_ids
        rec['use_runes']=bool(use_runes)
        rec['verified_talent_grant_exact_id_and_level']=confirmed_talent_grant
        rec['verified_talent_grant_exact_id']=confirmed_talent_grant
        if role['role']=='SOURCE_NAMED_EQUIPMENT_ENGRAVING_SETUP':
            rec.update(eligibility=('RUNE_SETUP_ACQUISITION_UNRESOLVED' if use_runes else
                                    'RUNE_ENGRAVING_DISABLED_BY_DEFAULT'),
                       l0_disposition=('CONTEXTUAL_SETUP_EFFECT_REQUIRES_RUNE_GRANT' if use_runes else
                                       'RUNE_ENGRAVING_NOT_A_LEGAL_ACTION'),
                       exploration_priority=('UNCERTAIN_NOT_ZERO' if use_runes else 'EXCLUDED_RUNE_SETUP'),
                       legal_combat_spell_proven=False)
        elif 'rune_grant_unverified' in flags and not confirmed_talent_grant and not use_runes:
            rec.update(eligibility='RUNE_CONDITIONAL_GRANT_DISABLED_TALENT_PATH_UNVERIFIED',
                       l0_disposition='NOT_FREE_ACTION_REQUIRES_VERIFIED_TALENT_GRANT',
                       exploration_priority='BLOCKED_RUNE_GRANT_NO_PROVEN_TALENT',
                       legal_combat_spell_proven=False)
        elif (flags.intersection({'not_an_action','passive_modifier',
                                  'trigger_or_component_unverified','proc_or_trigger_unverified'})
              and not matches):
            rec.update(eligibility='AUXILIARY_OR_PASSIVE_NOT_STANDALONE_ACTION',
                       l0_disposition='REQUIRES_PARENT_TRIGGER_OR_PASSIVE_EFFECT_COVERAGE',
                       exploration_priority='PARENT_INTEGRATION_PENDING',
                       legal_combat_spell_proven=False)
        elif role['role']=='ZERO_OR_UNKNOWN_LEVEL_PASSIVE_TALENT_CANDIDATE':
            rec.update(eligibility='PASSIVE_OR_TALENT_UNRESOLVED',
                       l0_disposition='TALENT_OR_PASSIVE_CONTEXT_NOT_FREE_BUTTON',
                       exploration_priority='UNCERTAIN_NOT_ZERO',
                       legal_combat_spell_proven=False)
        elif role['role']=='EXPLICITLY_REMOVED_FROM_SOURCE_CHANGESET':
            rec.update(eligibility='REMOVED_CHANGESET_BUILD_APPLICABILITY_UNRESOLVED',
                       l0_disposition='BLOCKED_REMOVED_VERSION_NOT_PROVEN',
                       exploration_priority='UNCERTAIN_NOT_ZERO',
                       legal_combat_spell_proven=False)
        else:
            rec.update(eligibility='POTENTIALLY_LEGAL_RANK_ACQUISITION_UNRESOLVED',
                       l0_disposition='IR_CONTEXTUAL_PROXY' if matches else
                                      ('INDEX_NUMERIC_PROXY_UNCERTAIN' if effects['atoms'] else
                                       'UNBOUNDED_EFFECT_EXPLORATION_PROXY'),
                       exploration_priority='UNCERTAIN_NOT_ZERO' if not matches else 'IR_EVALUABLE',
                       legal_combat_spell_proven=False)
            possible.append(sid)
            if matches or effects['atoms']:ranked.append(sid)
        records.append(rec)
    for action in ir_only:
        records.append({'ir_only_action_id':action.id,'name':action.name,
            'eligibility':'IR_CONTEXT_ONLY_NOT_SOURCE_INDEX_ROW',
            'l0_disposition':'IR_CONTEXTUAL_PROXY',
            'ir_proxies':[_ir_proxy(action)],
            'legal_combat_spell_proven':False,
            'exploration_priority':'IR_EVALUABLE'})
    counts=Counter(r['eligibility'] for r in records)
    text_scored=[r for r in records if r.get('eligibility')=='POTENTIALLY_LEGAL_RANK_ACQUISITION_UNRESOLVED'
                 and r['source_text_context_evidence']['effect_candidates']]
    web_scored=[r for r in text_scored if r.get('web_indexed_l0_observation') and not r['index_text_present']]
    sibling_scored=[r for r in records if r.get('eligibility')=='POTENTIALLY_LEGAL_RANK_ACQUISITION_UNRESOLVED'
                    and r['sibling_rank_context_only'] and not r['source_text_context_evidence']['effect_candidates']]
    index_scored=set(ranked)
    external_scored={r['spell_id'] for r in records if r.get('eligibility')=='POTENTIALLY_LEGAL_RANK_ACQUISITION_UNRESOLVED'
        and r.get('external_detail_l0_observation') and r['external_detail_l0_observation']['observed_effect_role']}
    assessed_by_evidence=index_scored | {r['spell_id'] for r in text_scored+sibling_scored} | external_scored
    nonindex=[r for r in records if 'ir_only_action_id' in r]
    not_proxy_scored=[r for r in records if r.get('l0_disposition')=='UNBOUNDED_EFFECT_EXPLORATION_PROXY']
    # A known mechanic missing a numeric tooltip is *not* proven worthless.
    search_admitted=[r for r in records if r.get('paid_search_admission')=='PAID_EXECUTABLE_SOURCE_IR']
    missing_ir=[r for r in records if r.get('source_role')=='UNRESOLVED_POSITIVE_LEVEL_ENTRY'
                and r.get('paid_search_admission')=='NO_EXECUTABLE_IR_FOR_SOURCE_RANK']
    return {'schema':'source_checkpoint_l0_v2_mode_search_admission',
        'paid_search_admitted_source_rows':len(search_admitted),
        'paid_mode_entry_count':len(paid_mode_entries),
        'paid_mode_actions_count':len(paid_mode_actions),
        'paid_mode_entry_ids':sorted(paid_mode_entries),
        'positive_level_source_ranks_unadmitted_missing_ir':len(missing_ir),
        'paid_search_admission_is_L2_coverage_proof':False,
        'checkpoint':{'class_key':cls,'level':level,'profile':profile or 'unrestricted'},
        'use_runes':bool(use_runes),
        'rune_engraving_rows_disabled':counts['RUNE_ENGRAVING_DISABLED_BY_DEFAULT'],
        'rune_conditional_grants_blocked_without_talent':counts['RUNE_CONDITIONAL_GRANT_DISABLED_TALENT_PATH_UNVERIFIED'],
        'auxiliary_nonbuttons_needing_parent_coverage':counts['AUXILIARY_OR_PASSIVE_NOT_STANDALONE_ACTION'],
        'verified_talent_grant_ids_in_source_data':len(talent_grant_ids),
        'source_index_sha256':source_sha,
        'source_acquisition_frontier':{k:v for k,v in acquisition.items() if k!='records'},
        'source_index_rows_all_levels':len(rows),
        'out_of_level_rows':len(excluded),
        'within_level_rows':len(records)-len(nonindex),
        'index_scope_by_type':dict(counts),
        'potentially_legal_positive_ranks':len(possible),
        'potential_ranks_with_numeric_or_ir_proxy':len(ranked),
        'potential_ranks_with_contextual_l0_proxy':len(possible),
        'potential_ranks_without_quantified_effect':len(possible)-len(ranked),
        'potential_ranks_with_source_text_context':len(text_scored),
        'web_indexed_observation_rows':len(web_l0_observations),
        'web_indexed_potential_rank_l0_roles':len(web_scored),
        'web_indexed_observations_are_L2_or_legality_proof':False,
        'potential_ranks_with_sibling_role_only':len(sibling_scored),
        'potential_ranks_with_external_detail_role':len(external_scored),
        'all_source_detail_roles_observed':len(observed_details),
        'external_observation_not_legal_or_L2_authority':True,
        'external_helper_or_passive_index_rows':sum(1 for r in records if r.get('external_detail_l0_observation') and r['external_detail_l0_observation']['observed_action_type'] in ('triggered_effect_not_player_cast','passive_modifier_not_cast')),
        'external_action_proposals_unadmitted_to_paid_search':sum(1 for r in records if r.get('external_detail_l0_observation') and r['external_detail_l0_observation']['observed_action_type'] in ('actor_action','talent_grant_action','conditional_granted_action') and r.get('paid_search_admission')!='PAID_EXECUTABLE_SOURCE_IR'),
        'potential_ranks_assessed_by_numeric_ir_or_text_role':len(assessed_by_evidence),
        'potential_ranks_unknown_role_and_amount':len(possible)-len(assessed_by_evidence),
        'ambiguous_proxy_rows':len(not_proxy_scored),
        'ir_only_context_actions':len(nonindex),
        'profile_constraint_applied':profile is None,
        'l0_proxies_are_search_scores':False,
        'complete_legal_spell_universe_proven':False,
        'PASS1':False,
        'blocker':'UNRESOLVED_LEGAL_ACQUISITION_AND_EFFECTS_NOT_ADMITTED_TO_JOINT_SEARCH',
        'records':records,'excluded_above_level':excluded}
