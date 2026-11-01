"""Shared canonical SQLite talent identity and verified-rank projection.

Unverified talents are *visible as non-executable definitions*, never omitted
or represented by fabricated zero-effect modifiers.
"""
from __future__ import annotations

from dataclasses import replace
import json
import sqlite3

from src.game.model.ir import TalentDefinition, TalentModifier, TalentRankDefinition
from .sqlite_talents import DEFAULT_DB, _slug, load_sqlite_talents
from .source_db_scope import active_ability_db


def source_enrich_indexed_talents(ir):
    if ir is None:
        return None
    class_key = str(ir.actor.metadata.get('class_key') or '').lower()
    with sqlite3.connect(active_ability_db(DEFAULT_DB)) as conn:
        indexed = conn.execute('''SELECT spell_id,name,source_url
            FROM spell_index WHERE class_key=? AND kind='talents' ''', (class_key,)).fetchall()
        granted_actions = []
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_talent_granted_action_facts'").fetchone():
            granted_actions = [json.loads(row[0]) for row in conn.execute(
                "SELECT action_json FROM verified_talent_granted_action_facts WHERE class_key=?", (class_key,))]
        staged_replacements=set()
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoint_talent_source_catalogue'").fetchone():
            for (raw,) in conn.execute('SELECT source_json FROM checkpoint_talent_source_catalogue WHERE class_key=? AND min_level<=?',
                                      (class_key,int(ir.actor.metadata.get('level',0)))):
                staged_replacements.update(r['replaces_talent_id'] for r in json.loads(raw)['catalogue']
                    if r.get('replaces_talent_id'))
        captured = []
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_talent_rank_facts'").fetchone():
            captured = conn.execute('''SELECT spell_id,talent_name,tree_key,tree_row,tree_col,
                rank,max_rank,trait_id,modifier_json,rank_source_url,tree_source_url,
                captured_at,capture_id FROM verified_talent_rank_facts WHERE class_key=?
                ORDER BY spell_id,rank''', (class_key,)).fetchall()
    verified = {}
    for row in captured:
        verified.setdefault(int(row[0]), []).append(row)
    existing = {t.id: t for t in ir.talents}
    # Explicit, source-versioned complete catalogue: replace the indexed
    # identity-only placeholders rather than appending stale client entries.
    # The source stage is still read through canonical SQLite -> GameIR.
    with sqlite3.connect(active_ability_db(DEFAULT_DB)) as staged_conn:
        has_stage=bool(staged_conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                   "AND name='checkpoint_talent_source_catalogue'").fetchone())
        stage_rows=(staged_conn.execute('SELECT source_json FROM checkpoint_talent_source_catalogue '
            'WHERE class_key=? AND min_level<=?',(class_key,int(ir.actor.metadata.get('level',0)))).fetchall()
            if has_stage else [])
    if len(stage_rows)>1:raise ValueError('AMBIGUOUS_STAGED_TALENT_SOURCE')
    if stage_rows and json.loads(stage_rows[0][0]).get('replace_indexed_catalogue'):
        data=json.loads(stage_rows[0][0])
        inventory=load_sqlite_talents(class_key,level=int(ir.actor.metadata['level']),
            action_families=(a.family_key for a in ir.actions),
            mode_labels={m.label.lower().replace(' ','_'):m.id for m in ir.modes})
        talents=[]
        for t in inventory.talents:
            previous=existing.get(t.id)
            if previous and previous.tree_key==t.tree_key and previous.max_rank==t.max_rank:
                old_ranks={r.rank:r for r in previous.ranks}
                ranks=tuple(replace(r,modifiers=old_ranks[r.rank].modifiers)
                    if r.rank in old_ranks and old_ranks[r.rank].modifiers else r for r in t.ranks)
                t=replace(t,ranks=ranks)
            talents.append(t)
        if {t.id for t in talents}!={r['talent_id'] for r in data['catalogue']}:
            raise ValueError('STAGED_TALENT_REPLACEMENT_IDENTITY_MISMATCH')
        rules={'points_per_row':int(data['points_per_row']),
               'authority':'source_versioned_checkpoint_talent_catalogue',
               'source_url':data['source_url'],
               'source_build':data['source_build']}
        return replace(ir,talents=tuple(talents),
            provenance={**ir.provenance,'talent_tree_rules':rules,
                'talent_source_families':[t.id for t in talents],
                'staged_talent_source_build':data['source_build'],
                'staged_talent_retired_ids':data.get('retired_indexed_talent_ids',[]),
                'talent_sqlite_coverage':{'expected':len(talents),
                    'source_l0_reachable_families':len(data['observations']),
                    'source_l0_only':True,'complete_at_stage':True}},
            source_facts=(*ir.source_facts,{'family':'talent_granted_action_facts',
                'actions':granted_actions,'authority':'canonical_sqlite_verified_source'}),
            unsupported_semantics=(*ir.unsupported_semantics,{
                'code':'staged_source_talent_l0_only',
                'source_version':data['source_build'],
                'indexed_families':len(talents)}))
    # Shared rank-capture loader already powers Druid. Reuse its full-rank
    # parser for native classes before the identity-only fallback; never
    # replace an existing verified native capture with a secondary source.
    captured_inventory = load_sqlite_talents(class_key,
        action_families=(a.family_key for a in ir.actions),
        mode_labels={m.label.lower().replace(' ','_'):m.id for m in ir.modes},
        level=int(ir.actor.metadata.get('level', 0)))
    position_staged = [t for t in captured_inventory.talents
        if t.metadata.get('source_position_only')]
    if position_staged:
        if len(position_staged) != len(captured_inventory.talents):
            raise ValueError('STAGED_TALENT_PARTIAL_POSITION_INVENTORY')
        build = position_staged[0].metadata['checkpoint_source_build']
        if any(t.metadata['checkpoint_source_build'] != build for t in position_staged):
            raise ValueError('STAGED_TALENT_MIXED_POSITION_BUILDS')
        rule = captured_inventory.tree_rule or {}
        position_metadata = next(b['source_position_stage'] for b in captured_inventory.blockers
            if 'source_position_stage' in b)
        return replace(ir, talents=tuple(captured_inventory.talents),
            provenance={**ir.provenance, 'talent_tree_rules': {
                **rule, 'points_per_row': int(position_metadata['points_per_row']),
                'authority': 'versioned_sqlite_source_talent_positions',
                'source_build': build},
                'staged_talent_position_build': build,
                'staged_talent_position_count': len(position_staged)},
            unsupported_semantics=(*ir.unsupported_semantics, {
                'code': 'source_position_only_rank_effects_not_scored',
                'source_build': build, 'talents': len(position_staged)}))
    secondary = {t.id:t for t in captured_inventory.talents
        if t.metadata.get('rank_cap_verified') and t.ranks
        and all(r.modifiers for r in t.ranks)}
    added, gaps = [], []
    for spell_id, name, url in indexed:
        key = _slug(name)
        if key in staged_replacements:
            continue  # Explicit versioned source replacement, not a free old talent.
        if key in existing:
            continue
        rows = verified.get(int(spell_id), ())
        if not rows and key in secondary:
            added.append(secondary[key])
            continue
        if not rows:
            gaps.append({'talent_id': key, 'spell_id': spell_id,
                         'reason': 'missing_verified_rank_tree_and_prerequisite_facts',
                         'source_url': url})
            added.append(TalentDefinition(id=key,name=name,tree_key='unresolved',
                max_rank=0,ranks=(),provenance=({'source_url':url,
                    'authority':'indexed_identity_only'},),
                metadata={'class_key':class_key,'row':None,'source_status':'rank_not_verified'}))
            continue
        max_rank=int(rows[0][6])
        if ([int(r[5]) for r in rows] != list(range(1,max_rank+1))
                or any(int(r[6]) != max_rank for r in rows)):
            gaps.append({'talent_id':key,'reason':'non_contiguous_verified_rank_curve'})
            added.append(TalentDefinition(id=key,name=name,tree_key='unresolved',max_rank=0,
                                          provenance=({'source_url':url},)))
            continue
        rank_defs=[]
        for row in rows:
            source={'source_url':row[9],'tree_source_url':row[10],
                    'captured_at':row[11],'capture_id':row[12],
                    'trait_id':int(row[7]),'rank':int(row[5])}
            mods=tuple(TalentModifier(kind=m['kind'],target_type=m['target_type'],
                target_id=m['target_id'],value=float(m['value']),provenance=source)
                for m in json.loads(row[8]))
            rank_defs.append(TalentRankDefinition(rank=int(row[5]),modifiers=mods,
                                                  provenance=source))
        added.append(TalentDefinition(id=key,name=name,tree_key=str(rows[0][2]),
            max_rank=max_rank,ranks=tuple(rank_defs),
            provenance=({'source_url':url,'rank_source_url':rows[0][9],
                'tree_source_url':rows[0][10],'capture_id':rows[0][12]},),
            metadata={'class_key':class_key,'row':int(rows[0][3]),
                      'col':int(rows[0][4]),'source_status':'verified_rank_curve'}))
    # Do not duplicate Druid's existing fully indexed 52-family inventory.
    if not added:
        if granted_actions and not any(f.get('family')=='talent_granted_action_facts'
                                       for f in ir.source_facts if isinstance(f,dict)):
            return replace(ir,source_facts=(*ir.source_facts,{
                'family':'talent_granted_action_facts',
                'actions':granted_actions,'authority':'canonical_sqlite_verified_source'}))
        return ir
    rules=dict(ir.provenance.get('talent_tree_rules') or {})
    if captured_inventory.tree_rule is not None:
        rules.update(captured_inventory.tree_rule)
    if any(t.metadata.get('row') is not None for t in added):
        rules.setdefault('points_per_row',5)
        rules.setdefault('authority','source_calculator_row_gates')
    return replace(ir,talents=(*ir.talents,*added),
        provenance={**ir.provenance,'talent_tree_rules':rules,
            'talent_source_families':[t.id for t in (*ir.talents,*added)],
            'talent_sqlite_coverage':{'expected':len(indexed),
                'executable_verified':sum(any(r.modifiers for r in t.ranks)
                    for t in (*ir.talents,*added)), 'complete':not gaps,
                'blockers':gaps}},
        source_facts=(*ir.source_facts, {'family':'talent_granted_action_facts',
            'actions':granted_actions,'authority':'canonical_sqlite_verified_source'}),
        unsupported_semantics=(*ir.unsupported_semantics,{
            'code':'source_talent_rank_coverage_incomplete',
            'indexed_families':len(indexed),'missing_rank_families':len(gaps)}))
