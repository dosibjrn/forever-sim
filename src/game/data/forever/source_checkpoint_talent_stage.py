"""Generic, version-scoped source talent rank/identity ingestion into GameIR.

An explicit SQLite stage carries a complete source catalogue plus typed L0
rank curves. Unknown executable semantics remain rank provenance, never
fabricated runtime modifiers. Default canonical SQLite is not changed.
"""
from __future__ import annotations
from dataclasses import replace
import hashlib, json, sqlite3
from src.game.model.ir import TalentDefinition,TalentRankDefinition,TalentModifier


def apply_staged_talent_catalogue(conn:sqlite3.Connection, class_key:str, level:int, talents):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoint_talent_source_catalogue'").fetchone():
        return tuple(talents),None
    rows=conn.execute('''SELECT * FROM checkpoint_talent_source_catalogue
        WHERE class_key=? AND min_level<=? ORDER BY min_level DESC''',(class_key.lower(),level)).fetchall()
    if not rows:return tuple(talents),None
    if len(rows)>1:raise ValueError('AMBIGUOUS_STAGED_TALENT_SOURCE')
    row=rows[0];raw=row['source_json'];data=json.loads(raw)
    if hashlib.sha256(raw.encode()).hexdigest()!=row['source_sha256']:
        raise ValueError('STAGED_TALENT_SOURCE_HASH_MISMATCH')
    if (data.get('class_key')!=class_key.lower() or data.get('source_build')!=row['source_build']
            or int(data.get('min_level',-1))!=int(row['min_level'])):
        raise ValueError('STAGED_TALENT_SOURCE_SCOPE_MISMATCH')
    entries=data['catalogue'];observations={r['talent_id']:r for r in data['observations']}
    unreachable={r['indexed_talent_id']:r for r in data.get('observed_unreachable_talent_positions',[])}
    if len(entries)!=len({r['talent_id'] for r in entries}):
        raise ValueError('DUPLICATE_STAGED_TALENT_ID')
    # Source facts are optional and keyed by the exact staged client build.
    # A compound control talent without its sourced duration stays L0-only.
    control_facts={}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sourced_talent_proc_control_facts'").fetchone():
        control_facts={r['talent_id']:dict(r) for r in conn.execute(
            'SELECT * FROM sourced_talent_proc_control_facts WHERE class_key=? AND source_build=?',
            (class_key.lower(),data['source_build']))}
    charge_facts={}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sourced_talent_charge_facts'").fetchone():
        charge_facts={r['talent_id']:dict(r) for r in conn.execute(
            'SELECT * FROM sourced_talent_charge_facts WHERE class_key=? AND source_build=?',
            (class_key.lower(),data['source_build']))}
    # A separate source record owns cross-build resource amounts. Rank chances
    # remain in the immutable staged talent catalogue; a later-build amount is
    # a real executable diagnostic but NOT 70338-certified without a bridge.
    critical_resource_facts={}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sourced_critical_resource_talent_facts'").fetchone():
        for fact in conn.execute('SELECT * FROM sourced_critical_resource_talent_facts WHERE class_key=?',
                                 (class_key.lower(),)):
            if fact['talent_id'] in critical_resource_facts:
                raise ValueError('DUPLICATE_CRITICAL_RESOURCE_SOURCE_FACT')
            critical_resource_facts[fact['talent_id']]=dict(fact)
    # Typed, source-versioned talent-granted resource actions. An earlier-build
    # mechanism can execute in an exploratory scenario but cannot certify the
    # currently staged source build without independent bridge verification.
    resource_actions={}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sourced_talent_resource_action_facts'").fetchone():
        for fact in conn.execute('SELECT * FROM sourced_talent_resource_action_facts WHERE class_key=?',
                                 (class_key.lower(),)):
            if fact['talent_id'] in resource_actions:
                raise ValueError('DUPLICATE_SOURCE_RESOURCE_ACTION')
            resource_actions[fact['talent_id']]=dict(fact)
    # Typed off-GCD next-cast effect grants are source facts, not talent-ID conditionals.
    next_cast_actions={}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sourced_talent_next_cast_action_facts'").fetchone():
        for entry_row in conn.execute('SELECT talent_id,fact_json FROM sourced_talent_next_cast_action_facts WHERE class_key=? AND source_build=?',
                                      (class_key.lower(),data['source_build'])):
            if entry_row['talent_id'] in next_cast_actions:raise ValueError('DUPLICATE_SOURCE_NEXT_CAST_ACTION')
            next_cast_actions[entry_row['talent_id']]=json.loads(entry_row['fact_json'])
    spatial_charge_actions={}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sourced_talent_spatial_charge_action_facts'").fetchone():
        for row_fact in conn.execute('SELECT talent_id,fact_json FROM sourced_talent_spatial_charge_action_facts WHERE class_key=? AND source_build=?',
                                     (class_key.lower(),data['source_build'])):
            if row_fact['talent_id'] in spatial_charge_actions:raise ValueError('DUPLICATE_SOURCE_CHARGE_ACTION')
            spatial_charge_actions[row_fact['talent_id']]=json.loads(row_fact['fact_json'])
    active_periodic_heal_actions={}

    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sourced_talent_active_periodic_heal_action_facts'").fetchone():
        for row_fact in conn.execute('SELECT talent_id,fact_json FROM sourced_talent_active_periodic_heal_action_facts WHERE class_key=? AND source_build=?',
                                     (class_key.lower(),data['source_build'])):
            if row_fact['talent_id'] in active_periodic_heal_actions:
                raise ValueError('DUPLICATE_SOURCE_ACTIVE_PERIODIC_HEAL_ACTION')
            active_periodic_heal_actions[row_fact['talent_id']]=json.loads(row_fact['fact_json'])
    old={t.id:t for t in talents};out=[];consumed=set()
    grant_rows = [json.loads(x[0]) for x in conn.execute(
        'SELECT action_json FROM verified_talent_granted_action_facts WHERE class_key=?',
        (class_key.lower(),))] if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_talent_granted_action_facts'").fetchone() else []
    retired=set(data.get('retired_indexed_talent_ids',()))
    if retired & {r['talent_id'] for r in entries}:
        raise ValueError('STAGED_TALENT_RETIRED_STILL_ACTIVE')
    if retired-set(old):raise ValueError('STAGED_TALENT_UNKNOWN_RETIRED_ID')
    for entry in entries:
        tid=entry['talent_id'];prior=entry.get('replaces_talent_id',tid)
        if prior not in old or prior in consumed:raise ValueError(f'STAGED_TALENT_SOURCE_ID_MISSING:{prior}')
        consumed.add(prior);t=old[prior]
        mapped_tree=data.get('source_tree_id_to_key',{}).get(t.tree_key.split(':',1)[-1])
        if entry['tree_key']!=t.tree_key and t.tree_key!='unresolved' and mapped_tree!=entry['tree_key']:
            raise ValueError(f'STAGED_TALENT_TREE_MISMATCH:{tid}')
        source_cap=int(entry['max_rank']);cap=source_cap;capture=observations.get(tid)
        deferred=False
        if cap!=t.max_rank and (not capture or int(capture['max_rank'])!=cap):
            position=unreachable.get(tid,{})
            tier=int(position.get('row',entry.get('row',t.metadata.get('row') if t.metadata.get('row') is not None else -1)))
            if tier<0 or tier*5+1<=level-9:
                raise ValueError(f'STAGED_TALENT_RANK_CURVE_MISSING:{tid}')
            # Not reachable in this checkpoint: preserve source rank cap and
            # identity, but do not invent an effect for any future rank.
            deferred=True
        if prior!=tid and not capture and not deferred:
            raise ValueError('STAGED_TALENT_RENAME_MISSING_RANK_CURVE')
        if capture and (capture['tree_key']!=entry['tree_key'] or int(capture['max_rank'])!=cap):
            raise ValueError('STAGED_TALENT_OBSERVATION_MISMATCH')
        if capture and (len(capture['rank_values'])!=cap or
                (capture.get('additional_rank_values') and len(capture['additional_rank_values'])!=cap)):
            raise ValueError('STAGED_TALENT_INCOMPLETE_RANKS')
        original={r.rank:r for r in t.ranks}
        changed=cap!=t.max_rank or prior!=tid or t.tree_key=='unresolved'
        rank_defs=[]
        for n in range(1,cap+1):
            previous=original.get(n)
            # On changed rank curves the old executable modifiers may be stale.
            # The sourced numeric L0 values are retained in provenance instead.
            modifiers=() if changed else (previous.modifiers if previous else ())
            # Bind a captured talent-granted spell family only when both
            # canonical rank rows and the exact source talent ID agree.
            grants = [g for g in grant_rows if g.get('family_key') == tid
                and str(g.get('grant_parent_spell_id',g.get('spell_id'))) ==
                    str(t.metadata.get('sqlite_spell_id'))]
            if grants and n == 1:
                if cap != 1 or len({str(g.get('grant_parent_spell_id',g.get('spell_id')))
                                    for g in grants}) != 1:
                    raise ValueError('STAGED_TALENT_GRANT_PARENT_OR_RANK_CONFLICT')
                if not any(m.kind == 'grant_source_action' for m in modifiers):
                    modifiers += (TalentModifier(kind='grant_source_action',
                        target_type='source_action',
                        target_id=str(grants[0].get('grant_parent_spell_id',grants[0]['spell_id'])),
                        value=1.0,provenance={'authority':'canonical_sqlite_source_rank_grant',
                            'source_url':capture['source_url'] if capture else entry['source_url']}),)
            # A sourced, already-ranked weapon action gated by this talent is
            # not a passive damage proxy. Publish the unlock generically from
            # the captured domain/target; actual numbers stay in the existing
            # source-ranked ActionDefinition and must not be double-credited.
            if (capture and capture.get('effect_domain') == 'attack_flat_weapon_addition'
                    and capture.get('additional_effect_domain') == 'normal_weapon_damage_multiplier'
                    and capture.get('target') == tid
                    and capture.get('additional_target') == tid):
                modifiers = modifiers + (TalentModifier(
                    kind='unlock_action_family', target_type='action_family',
                    target_id=str(capture['target']), value=1.0,
                    provenance={'authority':'staged_source_talent_observation',
                                'source_url':capture['source_url'],
                                'source_build':data['source_build'],
                                'effect_domain':capture['effect_domain'],
                                'additional_effect_domain':capture['additional_effect_domain']}),)
            # Source-verified per-level form stat conversion. Check the source
            # observed rank curve against its own observation level before
            # extending the formula to higher checkpoints.
            if (capture and capture.get('effect_domain') == 'form_melee_attack_power_from_level'):
                coefficient = float(capture.get('player_level_fraction_per_rank', 0.0))
                observation_level = int(data['min_level'])
                if coefficient <= 0 or any(abs(float(v) - coefficient*i*observation_level)>1e-7
                    for i,v in enumerate(capture['rank_values'],1)):
                    raise ValueError('FORM_AP_SOURCE_RANK_FORMULA_MISMATCH')
                stat = str(capture.get('target_stat') or '')
                if not stat: raise ValueError('FORM_AP_TARGET_STAT_MISSING')
                source_mode_ids = tuple(capture.get('source_mode_ids') or ())
                if not source_mode_ids or len(set(source_mode_ids)) != len(source_mode_ids):
                    raise ValueError('FORM_AP_SOURCE_MODE_SCOPE_MISSING')
                for mode_id in source_mode_ids:
                    modifiers += (TalentModifier(kind='mode_stat_flat',target_type='mode',
                        target_id=mode_id, value=coefficient*n*level,
                        provenance={'authority':'staged_source_talent_observation',
                            'source_url':capture['source_url'],
                            'source_build':data['source_build'],
                            'source_formula':capture.get('source_formula'),
                            'target_stat':stat,'effect_domain':capture['effect_domain'],
                            'source_observed_rank_value':float(capture['rank_values'][n-1]),
                            'source_observation_level':observation_level}),)
            # Source-observed conditional effect; the modifier stays generic.
            # A bleed-conditioned melee bonus is not a global weapon/attack
            # multiplier: it is evaluated at each real damage event against
            # the target's actual, source-tagged timed auras.
            if (capture and capture.get('effect_domain') == 'conditional_damage_pct'
                    and capture.get('condition') == 'target_has_bleed'
                    and capture.get('target') == 'melee_ability'):
                value = float(capture['rank_values'][n - 1])
                if not 0.0 < value <= 1.0:
                    raise ValueError('INVALID_SOURCE_CONDITIONAL_RANK_VALUE')
                modifiers += (TalentModifier(kind='conditional_target_aura_damage_pct',
                    target_type='action_filter', target_id='melee_ability', value=value,
                    provenance={'authority':'staged_source_talent_observation',
                        'source_url':capture['source_url'],
                        'source_build':data['source_build'],
                        'effect_domain':capture['effect_domain'],
                        'condition':capture['condition'],
                        'source_tooltip':capture.get('source_tooltips',[None]*cap)[n-1]}),)
            # Whole, sourced dual-clause incoming-avoidance talent. The source
            # owns all ranks, resource amount and form; this code is generic.
            if (capture and capture.get('effect_domain') == 'dodge_chance_bonus_fraction'
                    and capture.get('additional_effect_domain') == 'on_incoming_dodge_resource_proc_probability'):
                dodge=float(capture['rank_values'][n-1])
                chance=float(capture['additional_rank_values'][n-1])
                if not (0. < dodge <= 1. and 0. < chance <= 1. and
                        capture.get('target') == 'dodge_chance' and
                        capture.get('additional_target') == 'rage' and
                        float(capture.get('resource_per_proc',0.)) > 0 and
                        str(capture.get('required_mode_id'))):
                    raise ValueError('SOURCE_INCOMING_DODGE_DUAL_CLAUSE_INVALID')
                prov={'authority':'source_pinned_compound_dodge_proc',
                    'source_url':capture['source_url'], 'source_build':data['source_build'],
                    'mechanics_source_build':capture.get('mechanics_source_build'),
                    'unsupported_build_bridge':bool(capture.get('mechanics_build_bridge_unverified')),
                    'unsupported_expected_value_distribution':bool(capture.get(
                        'expected_value_proc_distribution_not_certified'))}
                modifiers += (TalentModifier(kind='actor_stat_flat',target_type='actor_stat',
                    target_id='dodge_chance',value=dodge,provenance=prov),
                    TalentModifier(kind='incoming_dodge_resource_gain',target_type='resource',
                    target_id=str(capture['additional_target']),value=chance,
                    provenance={**prov,'required_mode_id':str(capture['required_mode_id']),
                        'bonus_resource_amount':float(capture['resource_per_proc'])}))
            if (capture and capture.get('effect_domain') == 'healing_direct_crit_chance_bonus_fraction'
                    and capture.get('target')):
                value=float(capture['rank_values'][n-1])
                if not 0. < value <= 1.:raise ValueError('SOURCE_HEAL_CRIT_CURVE_INVALID')
                modifiers += (TalentModifier(kind='heal_crit_chance_bonus',target_type='action_family',
                    target_id=str(capture['target']),value=value,
                    provenance={'authority':'source_pinned_heal_crit',
                        'source_url':capture['source_url'],'source_build':data['source_build'],
                        'unsupported_prerequisite_rank_bridge':bool(capture.get(
                            'prerequisite_rank_build_bridge_unverified')),
                        'effect_domain':capture['effect_domain'],
                        'heal_crit_multiplier':float(capture.get('heal_crit_multiplier',0.)),
                        'heal_crit_multiplier_source_url':capture.get('heal_crit_multiplier_source_url'),
                        'heal_crit_multiplier_build_bridge_unverified':bool(capture.get(
                            'heal_crit_multiplier_build_bridge_unverified')),
                        'unsupported_heal_crit_multiplier_build_bridge':bool(capture.get(
                            'heal_crit_multiplier_build_bridge_unverified'))}),)
            provenance=dict(previous.provenance) if previous and not changed else {}
            if capture:
                provenance['checkpoint_source_l0']={
                    'source_url':capture['source_url'],'source_build':data['source_build'],
                    'effect_domain':capture['effect_domain'],'target':capture['target'],
                    'condition':capture.get('condition'),
                    'value':float(capture['rank_values'][n-1]),
                    'additional_effect_domain':capture.get('additional_effect_domain'),
                    'additional_target':capture.get('additional_target'),
                    'additional_value':(float(capture['additional_rank_values'][n-1])
                        if capture.get('additional_rank_values') else None),
                    'executable':bool(modifiers),
                    **({'spatial_charge_action_source':spatial_charge_actions[tid]}
                       if tid in spatial_charge_actions and
                          capture.get('effect_domain')=='charge_immobilize_interrupt_seconds' and
                          capture.get('target')==spatial_charge_actions[tid]['talent_effect_target']
                       else {}),
                    **({'active_periodic_heal_action_source':active_periodic_heal_actions[tid]}
                       if tid in active_periodic_heal_actions and
                          capture.get('effect_domain')=='instant_hot_full_remaining_heal_multiplier' and
                          capture.get('target')==active_periodic_heal_actions[tid]['talent_effect_target']
                       else {}),
                    **({'next_cast_action_source':next_cast_actions[tid]}
                       if tid in next_cast_actions and
                          capture.get('effect_domain')=='instant_next_nature_cast_count' and
                          capture.get('target')==next_cast_actions[tid]['source_talent_target']
                       else {}),
                    **({'resource_action_source':resource_actions[tid]}
                       if tid in resource_actions and
                          resource_actions[tid]['source_build']==data['source_build']
                          and capture.get('effect_domain')=='on_use_energy_restoration'
                          and capture.get('target')==resource_actions[tid]['family_key']
                       else {}),
                    **({'critical_resource_source':critical_resource_facts[tid]}
                       if tid in critical_resource_facts and
                          capture.get('effect_domain')=='critical_bear_rage_proc_probability' and
                          capture.get('additional_effect_domain')==
                              'critical_cat_bonus_combo_point_proc_probability' and
                          critical_resource_facts[tid]['target_build']==data['source_build']
                       else {}),
                    **({'charge_producer_family':charge_facts[tid]['producer_family'],
                        'charge_consumer_family':charge_facts[tid]['consumer_family'],
                        'charge_grant_per_cast':charge_facts[tid]['grant_per_cast'],
                        'charge_capacity':charge_facts[tid]['capacity'],
                        'charge_duration_s':charge_facts[tid]['duration_s'],
                        'charge_source_url':charge_facts[tid]['source_url'],
                        'charge_source_basis_url':charge_facts[tid]['source_basis_url']}
                       if tid in charge_facts and capture.get('effect_domain') ==
                           charge_facts[tid]['effect_domain'] and capture.get('target') ==
                           charge_facts[tid]['target'] and capture['source_url'] ==
                           charge_facts[tid]['source_url'] else {}),
                    **({'additional_control_id':control_facts[tid]['control_id'],
                        'additional_control_duration_s':control_facts[tid]['duration_s'],
                        'additional_control_source_url':control_facts[tid]['source_url'],
                        'additional_control_prevents_enemy_actions':bool(control_facts[tid]['prevents_enemy_actions']),
                        'additional_control_breaks_on_damage':bool(control_facts[tid]['breaks_on_damage'])}
                       if tid in control_facts and capture.get('additional_effect_domain') ==
                           control_facts[tid]['effect_domain'] and capture.get('additional_target') ==
                           control_facts[tid]['target'] and capture['source_url'] ==
                           control_facts[tid]['source_url'] else {})}
            rank_defs.append(TalentRankDefinition(rank=n,modifiers=modifiers,provenance=provenance))
        stage_row=entry.get('row',(capture or {}).get('row',t.metadata.get('row')))
        metadata={**t.metadata,**({'row':int(stage_row)} if stage_row is not None else {}),
            'rank_cap_verified':not deferred,
            'checkpoint_source_build':data['source_build'],
            'checkpoint_source_url':entry['source_url'],
            'checkpoint_source_rank_count':source_cap,
            'checkpoint_source_deferred_rank_curve':deferred,
            'checkpoint_source_prerequisite_rank_unverified':bool(
                capture and capture.get('prerequisite_rank_build_bridge_unverified')),
            'checkpoint_source_stage_sha256':row['source_sha256'],
            'checkpoint_source_l2_gap':changed and any(not r.modifiers for r in rank_defs),
            'checkpoint_source_identity_replaces':(prior if prior!=tid else None)}
        if capture:
            metadata['row']=int(capture['row'])
            metadata['tree_row_known']=True
        out.append(replace(t,id=tid,name=entry['name'],tree_key=entry['tree_key'],max_rank=cap,
            ranks=tuple(rank_defs),prerequisite=(capture.get('prerequisite') if capture and
                capture.get('prerequisite') else t.prerequisite),metadata=metadata))
    if consumed|retired!=set(old) or consumed&retired:
        raise ValueError('STAGED_TALENT_SOURCE_INVENTORY_MISMATCH')
    if set(observations)-{t.id for t in out}:raise ValueError('STAGED_TALENT_UNKNOWN_OBSERVATION')
    return tuple(out),{'build':data['source_build'],'source_sha256':row['source_sha256'],
        'catalogue_count':len(entries),'observed_rank_curves':len(observations),
        'source_url':data['source_url'],'min_level':data['min_level'],
        'replace_indexed_catalogue':bool(data.get('replace_indexed_catalogue')),
        'retired_count':len(retired),'points_per_row':data.get('points_per_row')}


def source_enrich_control_target_caps(ir, *, class_key: str, db_path):
    """Attach attested baseline control target caps from this source SQLite.

    A talent observation requiring a control cap must not silently become an
    unlimited control when its matching baseline source evidence is absent.
    """
    import re
    from pathlib import Path
    from src.game.model.ir import ControlEffect
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoint_talent_source_catalogue'").fetchone():
            return ir
        rows=db.execute('SELECT source_build,source_json FROM checkpoint_talent_source_catalogue WHERE class_key=?',
            (class_key.lower(),)).fetchall()
        expected={}
        for row in rows:
            for obs in json.loads(row['source_json']).get('observations',[]):
                if obs.get('effect_domain')=='extra_concurrent_rooted_targets':
                    expected[(row['source_build'],obs['target'])]=obs
        if not expected:
            return ir
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sourced_control_target_cap_facts'").fetchone():
            raise ValueError('SOURCE_CONTROL_TARGET_CAP_BASELINE_MISSING')
        facts=db.execute('SELECT * FROM sourced_control_target_cap_facts WHERE class_key=?',
            (class_key.lower(),)).fetchall()
        found=set();by_family={}
        for row in facts:
            key=(row['source_build'],row['action_family'])
            if key not in expected or key in found:
                raise ValueError('SOURCE_CONTROL_TARGET_CAP_SCOPE_CONFLICT')
            found.add(key)
            if (type(row['base_max_targets']) is not int or not 1<=row['base_max_targets']<=16
                    or not row['control_id'] or not str(row['source_url']).startswith('https://')):
                raise ValueError('INVALID_SOURCE_CONTROL_TARGET_CAP')
            # This capture's rank text is the baseline proof, not an assumed
            # default from Classic or an optimizer-side constant.
            source=db.execute('SELECT raw_listview_json FROM spell_index WHERE class_key=? AND spell_id=?',
                (class_key.lower(),row['source_spell_id'])).fetchone()
            if not source or row['evidence_text'] not in source[0]:
                raise ValueError('SOURCE_CONTROL_TARGET_CAP_EVIDENCE_MISSING')
            match=re.fullmatch(r'only have ([0-9]+) target',row['evidence_text'])
            if not match or int(match.group(1))!=row['base_max_targets']:
                raise ValueError('SOURCE_CONTROL_TARGET_CAP_EVIDENCE_CONFLICT')
            family=row['action_family'];control=row['control_id']
            if not any(a.family_key==family and any(isinstance(e,ControlEffect) and e.control_id==control
                       for e in a.effects) for a in ir.actions):
                raise ValueError('SOURCE_CONTROL_TARGET_CAP_ACTION_MISSING')
            by_family[family]={'control_id':control,'max_targets':int(row['base_max_targets']),
                'base_max_targets':int(row['base_max_targets']),'source_build':row['source_build'],
                'base_source_url':row['source_url'],'source_spell_id':row['source_spell_id']}
        if found!=set(expected):
            raise ValueError('SOURCE_CONTROL_TARGET_CAP_BASELINE_MISSING')
    actions=[]
    for action in ir.actions:
        fact=by_family.get(action.family_key)
        if fact and any(isinstance(e,ControlEffect) and e.control_id==fact['control_id']
                        for e in action.effects):
            action=replace(action,metadata={**dict(action.metadata),
                'source_control_target_caps':{fact['control_id']:dict(fact)}})
        actions.append(action)
    return replace(ir,actions=tuple(actions),source_facts=(*ir.source_facts,
        {'fact_kind':'source_control_target_caps','source_builds':sorted({x[0] for x in found}),
         'source_action_families':sorted(by_family)}))
